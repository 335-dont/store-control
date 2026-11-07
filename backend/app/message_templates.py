"""Templates por servidor; esta API não altera automaticamente embeds do bot."""
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column, Session
from .db import Base, get_db
from .store import authorize
from .auth import require_same_origin

router = APIRouter(tags=['message-templates'])
KEYS = {'shop','cart','stock','pix','review','approved','rejected','delivery','ticket','logs','expired','order'}

class GuildMessageTemplates(Base):
    __tablename__ = 'guild_message_templates'
    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    templates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

class Template(BaseModel):
    title: str = Field(default='', max_length=256)
    description: str = Field(default='', max_length=4096)
    color: str = Field(default='#5865F2', pattern=r'^#[0-9a-fA-F]{6}$')
    footer: str = Field(default='', max_length=2048)
    image: str = Field(default='', max_length=2048)
    thumbnail: str = Field(default='', max_length=2048)

class Payload(BaseModel):
    templates: dict[str, Template]

@router.get('/api/store/message-templates')
async def get_templates(request: Request, db: Session = Depends(get_db)):
    guild_id = await authorize(request)
    row = db.get(GuildMessageTemplates, guild_id)
    return {'templates': row.templates if row else {}}

@router.put('/api/store/message-templates')
async def put_templates(request: Request, payload: Payload, db: Session = Depends(get_db)):
    require_same_origin(request)
    guild_id = await authorize(request)
    if len(payload.templates) > len(KEYS) or set(payload.templates) - KEYS:
        raise HTTPException(422, 'Tipo de mensagem inválido')
    for t in payload.templates.values():
        for url in (t.image, t.thumbnail):
            if url and (not url.startswith('https://') or len(url)>2048):
                raise HTTPException(422, 'Imagens devem usar HTTPS')
    data = {key: value.model_dump() for key, value in payload.templates.items()}
    row = db.get(GuildMessageTemplates, guild_id)
    if row: row.templates = data
    else: db.add(GuildMessageTemplates(guild_id=guild_id, templates=data))
    db.commit()
    return {'templates': data}
