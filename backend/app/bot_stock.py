"""Read-only, guild-scoped stock endpoint for the Discord bot service."""
import os
import secrets
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from .db import get_db
from .store import GuildStore, Snapshot

router = APIRouter(prefix='/api/bot', tags=['bot'])


def require_bot_key(x_bot_key: str | None = Header(default=None)):
    expected = os.getenv('BOT_INTERNAL_KEY', '')
    if not expected or not x_bot_key or not secrets.compare_digest(x_bot_key, expected):
        raise HTTPException(status_code=401, detail='Bot não autorizado')


@router.get('/guilds/{guild_id}/stock', dependencies=[Depends(require_bot_key)])
def read_guild_stock(guild_id: str, db: Session = Depends(get_db)):
    if not guild_id.isdecimal() or len(guild_id) > 32:
        raise HTTPException(status_code=422, detail='Servidor inválido')
    row = db.get(GuildStore, guild_id)
    if row is None:
        return {'guild_id': guild_id, 'revision': 0, 'catalogs': [], 'products': []}
    snapshot = Snapshot.model_validate(row.payload)
    return {
        'guild_id': guild_id,
        'revision': row.revision,
        'catalogs': [c.model_dump() for c in snapshot.catalogs],
        'products': [p.model_dump() for p in snapshot.products if p.active and (p.unlimited or p.stock > 0)],
    }
