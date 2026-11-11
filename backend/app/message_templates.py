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

# Read-only bot endpoint, authenticated with the existing internal key.
from .loyalty import require_key
from .orders_api import validate_guild

@router.get('/api/bot/guilds/{guild_id}/message-templates', dependencies=[Depends(require_key)])
def bot_message_templates(guild_id: str, db: Session = Depends(get_db)):
    validate_guild(guild_id)
    row = db.get(GuildMessageTemplates, guild_id)
    return {'templates': row.templates if row else {}}

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


from datetime import datetime, timezone
from .loyalty import require_key
class PanelUpdate(Base):
    __tablename__='discord_panel_updates'
    guild_id: Mapped[str] = mapped_column(String(32),primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(32))
    message_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24),default='pending')
    detail: Mapped[str] = mapped_column(String(250),default='')

class PanelTarget(BaseModel):
    channel_id: str = Field(pattern=r'^\d{17,22}$')
    message_id: str = Field(pattern=r'^\d{17,22}$')

@router.post('/api/store/panel-update')
async def request_panel_update(request:Request,payload:PanelTarget,db:Session=Depends(get_db)):
    require_same_origin(request)
    guild_id=await authorize(request)
    if db.get(GuildMessageTemplates,guild_id) is None:
        raise HTTPException(400,'Salve o modelo antes de publicar')
    row=db.get(PanelUpdate,guild_id)
    if row is None:
        row=PanelUpdate(guild_id=guild_id,channel_id=payload.channel_id,message_id=payload.message_id,status='pending',detail='')
        db.add(row)
    else:
        row.channel_id=payload.channel_id;row.message_id=payload.message_id;row.status='pending';row.detail=''
    db.commit()
    return {'status':'pending'}

@router.get('/api/store/panel-update')
async def get_panel_update(request:Request,db:Session=Depends(get_db)):
    guild_id=await authorize(request)
    row=db.get(PanelUpdate,guild_id)
    return {'status':row.status,'detail':row.detail} if row else {'status':'idle','detail':''}

@router.get('/api/bot/panel-updates',dependencies=[Depends(require_key)])
def pending_updates(db:Session=Depends(get_db)):
    rows=db.query(PanelUpdate).filter(PanelUpdate.status=='pending').limit(20).all()
    return {'jobs':[{'guild_id':r.guild_id,'channel_id':r.channel_id,'message_id':r.message_id} for r in rows]}

class PanelResult(BaseModel):
    status:str
    detail:str=''

@router.post('/api/bot/panel-updates/{guild_id}/result',dependencies=[Depends(require_key)])
def update_result(guild_id:str,payload:PanelResult,db:Session=Depends(get_db)):
    row=db.get(PanelUpdate,guild_id)
    if row is None:raise HTTPException(404,'Nao encontrado')
    if payload.status not in ('done','error'):raise HTTPException(422,'Status invalido')
    row.status=payload.status;row.detail=payload.detail[:250];db.commit()
    return {'ok':True}

