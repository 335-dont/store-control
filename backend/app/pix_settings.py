"""Configuração Pix por servidor, protegida por sessão Discord ou chave interna do bot."""
import os
import secrets
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlparse, parse_qs
from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base, get_db
from .store import authorize
from .auth import require_same_origin

router = APIRouter(tags=['pix'])
class GuildPix(Base):
    __tablename__ = 'guild_pix_settings'
    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

class PixInput(BaseModel):
    key: str = Field(default='', max_length=140)
    name: str = Field(default='', max_length=25)
    city: str = Field(default='', max_length=15)
    delivery_role_id: str = Field(default='', pattern=r'^$|^\d{15,22}$')
    deliveries_channel_id: str = Field(default='', pattern=r'^$|^\d{15,22}$')
    private_server_url: str = Field(default='', max_length=500)

    @field_validator('private_server_url')
    @classmethod
    def validate_private_server_url(cls, value):
        value = value.strip()
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.scheme != 'https' or parsed.hostname not in ('www.roblox.com', 'roblox.com'):
            raise ValueError('Use um link HTTPS do Roblox')
        if not ((parsed.path.rstrip('/') == '/share' and parse_qs(parsed.query).get('code'))
                or (parsed.path.startswith('/games/') and ('privateServerLinkCode=' in parsed.query or 'linkCode=' in parsed.query))):
            raise ValueError('Informe um link de convite para servidor privado do Roblox')
        return value

def read_pix(db, gid):
    obj=db.get(GuildPix,gid)
    return PixInput.model_validate(obj.payload if obj else {}).model_dump()

@router.get('/api/store/pix')
async def get_pix(request: Request, db: Session=Depends(get_db)):
    gid=await authorize(request)
    return read_pix(db,gid)

@router.put('/api/store/pix')
async def put_pix(request: Request, payload: PixInput, db: Session=Depends(get_db)):
    require_same_origin(request)
    gid=await authorize(request)
    data=payload.model_dump()
    data={k:v.strip() for k,v in data.items()}
    if data['key'] and (not data['name'] or not data['city']):
        raise HTTPException(422,'Informe nome e cidade do recebedor')
    obj=db.get(GuildPix,gid)
    if obj: obj.payload=data
    else: db.add(GuildPix(guild_id=gid,payload=data))
    db.commit()
    return data

@router.get('/api/bot/guilds/{guild_id}/pix')
def bot_pix(guild_id: str, x_bot_key: str|None=Header(default=None), db: Session=Depends(get_db)):
    expected=os.getenv('BOT_INTERNAL_KEY','')
    if not expected or not x_bot_key or not secrets.compare_digest(expected,x_bot_key):
        raise HTTPException(401,'Bot não autorizado')
    if not guild_id.isdecimal() or len(guild_id)>32: raise HTTPException(422,'Servidor inválido')
    return read_pix(db,guild_id)
