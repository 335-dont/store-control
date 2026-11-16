"""Browser Push subscriptions by authenticated Discord manager and server."""
import hashlib
import json
import logging
import os
import time
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, JSON, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import require_same_origin, session_user
from .db import Base, SessionLocal, get_db
from .store import authorize

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/store/push', tags=['web-push'])
_test_last = {}
_test_lock = threading.Lock()


class PushSubscription(Base):
    __tablename__ = 'guild_web_push_subscriptions'
    endpoint_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    subscription: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SubscriptionPayload(BaseModel):
    endpoint: str = Field(min_length=30, max_length=2048)
    keys: dict[str, str]


def _validate_payload(payload: SubscriptionPayload):
    from urllib.parse import urlsplit
    parsed = urlsplit(payload.endpoint)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, 'Endpoint HTTPS inválido')
    if parsed.hostname not in {'web.push.apple.com', 'fcm.googleapis.com', 'updates.push.services.mozilla.com'} and not (
        parsed.hostname.endswith('.push.apple.com') or parsed.hostname.endswith('.push.services.mozilla.com')
    ):
        raise HTTPException(422, 'Provedor de push desconhecido')
    for key in ('p256dh', 'auth'):
        value = payload.keys.get(key, '')
        if not value or len(value) > 512:
            raise HTTPException(422, 'Chave de push inválida')


def _vapid_ready():
    return bool(os.getenv('WEB_PUSH_VAPID_PUBLIC_KEY') and os.getenv('WEB_PUSH_VAPID_PRIVATE_KEY')
                and os.getenv('WEB_PUSH_VAPID_SUBJECT'))


@router.get('/config')
async def push_config(request: Request):
    await authorize(request)
    return {'enabled': _vapid_ready(), 'public_key': os.getenv('WEB_PUSH_VAPID_PUBLIC_KEY', '') if _vapid_ready() else ''}


@router.get('/subscriptions')
async def subscription_count(request: Request, db: Session = Depends(get_db)):
    gid = await authorize(request)
    uid = str(session_user(request)['id'])
    rows = db.scalars(select(PushSubscription).where(PushSubscription.guild_id == gid, PushSubscription.user_id == uid)).all()
    return {'count': len(rows)}


class SubscriptionCheck(BaseModel):
    endpoint: str = Field(min_length=30, max_length=2048)


@router.post('/subscriptions/check')
async def check_push(request: Request, payload: SubscriptionCheck, db: Session = Depends(get_db)):
    require_same_origin(request)
    gid = await authorize(request)
    uid = str(session_user(request)['id'])
    key = hashlib.sha256(payload.endpoint.encode()).hexdigest()
    return {'registered': db.get(PushSubscription, (key, uid, gid)) is not None}


@router.post('/subscriptions')
async def register_push(request: Request, payload: SubscriptionPayload, db: Session = Depends(get_db)):
    require_same_origin(request)
    guild_id = await authorize(request)
    if not _vapid_ready():
        raise HTTPException(503, 'Configure as chaves VAPID no serviço web')
    _validate_payload(payload)
    uid = str(session_user(request)['id'])
    identifier = hashlib.sha256(payload.endpoint.encode()).hexdigest()
    record = db.get(PushSubscription, (identifier, uid, guild_id))
    # Each user can subscribe the same device to multiple authorized servers.
    if record:
        record.subscription = payload.model_dump()
    else:
        db.add(PushSubscription(endpoint_hash=identifier, guild_id=guild_id, user_id=uid,
                                subscription=payload.model_dump(), created_at=datetime.now(timezone.utc)))
    db.commit()
    return {'ok': True}


@router.delete('/subscriptions')
async def remove_push(request: Request, payload: SubscriptionPayload, db: Session = Depends(get_db)):
    require_same_origin(request)
    gid = await authorize(request)
    uid = str(session_user(request)['id'])
    record = db.get(PushSubscription, (hashlib.sha256(payload.endpoint.encode()).hexdigest(), uid, gid))
    if record and record.user_id == uid and record.guild_id == gid:
        db.delete(record)
        db.commit()
    return {'ok': True}


def _send_to_endpoint(info, payload):
    from pywebpush import webpush
    webpush(subscription_info=info, data=payload,
            vapid_private_key=os.environ['WEB_PUSH_VAPID_PRIVATE_KEY'],
            vapid_claims={'sub': os.environ['WEB_PUSH_VAPID_SUBJECT']}, timeout=8)


@router.post('/test')
async def test_push(request: Request, payload: SubscriptionCheck, db: Session = Depends(get_db)):
    """Send a test notification only to devices saved by this user in this guild."""
    require_same_origin(request)
    gid = await authorize(request)
    uid = str(session_user(request)['id'])
    if not _vapid_ready():
        raise HTTPException(503, 'Chaves VAPID não configuradas')
    endpoint_key = hashlib.sha256(payload.endpoint.encode()).hexdigest()
    selected = db.get(PushSubscription, (endpoint_key, uid, gid))
    rows = [selected] if selected else []
    if not rows:
        raise HTTPException(409, 'Este iPhone não está inscrito neste servidor. Toque em Ativar notificações.')
    now = time.monotonic()
    throttle_key = (gid, uid)
    with _test_lock:
        if now - _test_last.get(throttle_key, -1000) < 60:
            raise HTTPException(429, 'Espere um minuto antes de testar novamente.')
        _test_last[throttle_key] = now
    message = json.dumps({'title':'🔔 Teste de notificação — Eleve',
                          'body':'Se você recebeu este aviso, o envio push está funcionando.',
                          'url':'/', 'tag':'eleve-test'}, ensure_ascii=False)
    delivered, failed, failure_codes = 0, 0, []
    for row in rows[:5]:
        try:
            await run_in_threadpool(_send_to_endpoint, row.subscription, message)
            delivered += 1
        except Exception as exc:
            failed += 1
            code = getattr(getattr(exc, 'response', None), 'status_code', None)
            failure_codes.append(str(code) if code is not None else type(exc).__name__)
            logger.warning('Falha no push de teste (HTTP %s, %s)', code, type(exc).__name__)
            if code in (404, 410):
                db.delete(row)
    db.commit()
    return {'sent':delivered, 'failed':failed, 'registered':len(rows), 'failure_codes':failure_codes,
            'message':('Enviado ao serviço push. Verifique o iPhone.' if delivered else
                       'Falha no envio. Confira os logs do backend no Railway.')}


def dispatch_approved_push(guild_id: str, order_id: str, total_cents: int):
    """Called after commit, only on a real transition into approved."""
    if not _vapid_ready():
        return
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.error('Dependência pywebpush não instalada')
        return
    with SessionLocal() as db:
        subscriptions = db.scalars(select(PushSubscription).where(PushSubscription.guild_id == guild_id)).all()
        records = [(r.endpoint_hash, r.user_id, r.subscription) for r in subscriptions]
    # Mensagem de push compacta, sem número do pedido ou textos extras.
    amount = f'{total_cents / 100:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    payload = json.dumps({'title': 'Venda Aprovada!', 'body': f'Valor: R$ {amount}',
                          'url': '/?view=pedidos', 'tag': f'paid-{order_id}'}, ensure_ascii=False)
    logger.info('Push pagamento aprovado: servidor=%s pedido=%s dispositivos=%d', guild_id, order_id[:8], len(records))
    for key, uid, info in records:
        try:
            _send_to_endpoint(info, payload)
            logger.info('Push de pedido enviado ao provedor: servidor=%s pedido=%s', guild_id, order_id[:8])
        except WebPushException as exc:
            code = getattr(getattr(exc, 'response', None), 'status_code', None)
            if code in (404, 410):
                with SessionLocal() as db:
                    row = db.get(PushSubscription, (key, uid, guild_id))
                    if row:
                        db.delete(row)
                        db.commit()
            else:
                logger.warning('Falha ao enviar push (%s) para um dispositivo: %s', code, type(exc).__name__)
        except Exception:
            logger.exception('Erro inesperado ao enviar notificação de pagamento')
