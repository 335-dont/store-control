"""Server-scoped catalog snapshot; deliberately separate from legacy global tables."""
import json
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import String, Integer, JSON, select
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base, get_db
from .auth import session_user, managed_guilds, require_same_origin

router = APIRouter(prefix='/api/store', tags=['store'])

class GuildStore(Base):
    __tablename__ = 'guild_stores'
    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

class CatalogItem(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    emoji: str = Field(default='📁', max_length=500)

class ProductItem(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    catalogId: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    emoji: str = Field(default='📦', max_length=500)
    price: float = Field(ge=0.1, le=9999999999)
    stock: int = Field(ge=0, le=1000000000)
    unlimited: bool = False
    active: bool = True

class Snapshot(BaseModel):
    catalogs: list[CatalogItem] = Field(max_length=1000)
    products: list[ProductItem] = Field(max_length=10000)

    @model_validator(mode='after')
    def valid_relations(self):
        ids = [c.id for c in self.catalogs]
        pids = [p.id for p in self.products]
        if len(ids) != len(set(ids)) or len(pids) != len(set(pids)):
            raise ValueError('IDs duplicados')
        if any(p.catalogId not in ids for p in self.products):
            raise ValueError('Produto com catálogo inexistente')
        return self

class Update(BaseModel):
    revision: int = Field(ge=0)
    data: Snapshot

async def authorize(request: Request):
    user = session_user(request)
    if not user:
        raise HTTPException(401, 'Faça login com Discord')
    from .auth import signer
    try:
        gid = signer().loads(request.cookies.get('sc_guild', ''), max_age=604800)
    except Exception:
        raise HTTPException(403, 'Selecione um servidor')
    if not isinstance(gid, str) or not gid.isdecimal():
        raise HTTPException(403, 'Selecione um servidor válido')
    if request.headers.get('x-store-guild') != gid:
        raise HTTPException(409, 'Servidor alterado. Recarregue os dados.')
    allowed = await managed_guilds(request)
    if not any(str(g['id']) == gid for g in allowed):
        raise HTTPException(403, 'Sem permissão para este servidor')
    return gid

@router.get('/snapshot')
async def read_store(request: Request, db: Session = Depends(get_db)):
    gid = await authorize(request)
    row = db.get(GuildStore, gid)
    return {'revision': row.revision if row else 0, 'data': row.payload if row else {'catalogs': [], 'products': []}}

@router.put('/snapshot')
async def write_store(request: Request, update: Update, db: Session = Depends(get_db)):
    require_same_origin(request)
    gid = await authorize(request)
    # Lock existing row. For first write, unique key protects simultaneous creation.
    row = db.scalar(select(GuildStore).where(GuildStore.guild_id == gid).with_for_update())
    if row is None:
        if update.revision != 0:
            raise HTTPException(409, 'Estoque alterado em outro dispositivo. Recarregue a página.')
        row = GuildStore(guild_id=gid, revision=1, payload=update.data.model_dump())
        db.add(row)
    else:
        if row.revision != update.revision:
            raise HTTPException(409, 'Estoque alterado em outro dispositivo. Recarregue a página.')
        row.revision += 1
        row.payload = update.data.model_dump()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, 'Conflito de gravação. Recarregue a página.')
    return {'revision': row.revision}
