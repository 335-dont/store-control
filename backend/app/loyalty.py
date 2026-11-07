"""Cargos de fidelidade por servidor; somente pedidos entregues contam."""
import os
import secrets
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import JSON, String, select, func
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base, get_db
from .store import authorize
from .auth import require_same_origin
from .orders_api import GuildOrder, validate_guild

router = APIRouter(tags=['loyalty'])

class GuildLoyalty(Base):
    __tablename__ = 'guild_loyalty_settings'
    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tiers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

class Tier(BaseModel):
    role_id: str = Field(pattern=r'^\d{15,22}$')
    minimum_cents: int = Field(ge=1, le=1000000000)

class Settings(BaseModel):
    tiers: list[Tier] = Field(default_factory=list, max_length=30)

def require_key(x_bot_key: str | None = Header(default=None)):
    key = os.getenv('BOT_INTERNAL_KEY', '')
    if not key or not x_bot_key or not secrets.compare_digest(key, x_bot_key):
        raise HTTPException(401, 'Bot não autorizado')

def get_tiers(db, guild_id):
    row = db.get(GuildLoyalty, guild_id)
    return row.tiers if row else []

@router.get('/api/store/loyalty')
async def read_settings(request: Request, db: Session = Depends(get_db)):
    guild_id = await authorize(request)
    return {'tiers': get_tiers(db, guild_id)}

@router.put('/api/store/loyalty')
async def save_settings(request: Request, payload: Settings, db: Session = Depends(get_db)):
    require_same_origin(request)
    guild_id = await authorize(request)
    tiers = [x.model_dump() for x in payload.tiers]
    if len({x['role_id'] for x in tiers}) != len(tiers):
        raise HTTPException(422, 'Cargo repetido')
    if len({x['minimum_cents'] for x in tiers}) != len(tiers):
        raise HTTPException(422, 'Valor mínimo repetido')
    tiers.sort(key=lambda x: x['minimum_cents'])
    row = db.get(GuildLoyalty, guild_id)
    if row: row.tiers = tiers
    else: db.add(GuildLoyalty(guild_id=guild_id, tiers=tiers))
    db.commit()
    return {'tiers': tiers}

@router.get('/api/bot/guilds/{guild_id}/loyalty', dependencies=[Depends(require_key)])
def bot_settings(guild_id: str, db: Session = Depends(get_db)):
    validate_guild(guild_id)
    return {'tiers': get_tiers(db, guild_id)}

@router.get('/api/bot/guilds/{guild_id}/loyalty/clients', dependencies=[Depends(require_key)])
def bot_clients(guild_id: str, db: Session = Depends(get_db)):
    validate_guild(guild_id)
    totals = db.execute(select(GuildOrder.buyer_id, func.sum(GuildOrder.total_cents))
        .where(GuildOrder.guild_id == guild_id, GuildOrder.status == 'delivered')
        .group_by(GuildOrder.buyer_id)).all()
    return {'tiers': get_tiers(db, guild_id), 'clients': [
        {'buyer_id': buyer, 'total_cents': int(total)} for buyer, total in totals]}

@router.get('/api/bot/guilds/{guild_id}/loyalty/clients/{buyer_id}', dependencies=[Depends(require_key)])
def bot_client(guild_id: str, buyer_id: str, db: Session = Depends(get_db)):
    validate_guild(guild_id)
    if not buyer_id.isdecimal() or len(buyer_id) > 32:
        raise HTTPException(422, 'Cliente inválido')
    total = db.scalar(select(func.coalesce(func.sum(GuildOrder.total_cents), 0))
        .where(GuildOrder.guild_id == guild_id, GuildOrder.buyer_id == buyer_id,
               GuildOrder.status == 'delivered'))
    return {'buyer_id': buyer_id, 'total_cents': int(total or 0), 'tiers': get_tiers(db, guild_id)}

@router.get('/api/store/loyalty/clients')
async def web_clients(request: Request, db: Session = Depends(get_db)):
    guild_id = await authorize(request)
    totals = db.execute(select(GuildOrder.buyer_id, func.sum(GuildOrder.total_cents))
        .where(GuildOrder.guild_id == guild_id, GuildOrder.status == 'delivered')
        .group_by(GuildOrder.buyer_id).order_by(func.sum(GuildOrder.total_cents).desc()).limit(200)).all()
    return {'clients': [{'buyer_id': buyer, 'total_cents': int(total)} for buyer, total in totals]}
