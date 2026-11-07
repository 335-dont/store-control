"""Etapa 4.3A: pedidos e reserva atomica de estoque por servidor.

Apenas API interna. O bot Discord sera integrado na etapa 4.3B.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import os
import secrets
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from .db import Base, get_db
from .store import GuildStore, Snapshot

router = APIRouter(prefix='/api/bot', tags=['bot-orders'])


def utcnow():
    return datetime.now(timezone.utc)


class GuildOrder(Base):
    __tablename__ = 'guild_orders'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    buyer_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='awaiting_payment')
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OrderLine(BaseModel):
    product_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=1000000)


class CreateOrder(BaseModel):
    buyer_id: str = Field(pattern=r'^\d{1,32}$')
    items: list[OrderLine] = Field(min_length=1, max_length=100)
    reservation_minutes: int = Field(default=15, ge=1, le=1440)


class ChangeStatus(BaseModel):
    status: str


def require_bot_key(x_bot_key: str | None = Header(default=None)):
    expected = os.getenv('BOT_INTERNAL_KEY', '')
    if not expected or not x_bot_key or not secrets.compare_digest(x_bot_key, expected):
        raise HTTPException(401, 'Bot não autorizado')


def validate_guild(guild_id):
    if not guild_id.isdecimal() or len(guild_id) > 32:
        raise HTTPException(422, 'Servidor inválido')


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def lock_store(db, guild_id):
    row = db.scalar(select(GuildStore).where(GuildStore.guild_id == guild_id).with_for_update())
    if row is None:
        raise HTTPException(409, 'Loja sem estoque cadastrado')
    return row


def expire_locked(db, store, now):
    """Expira reservas vencidas sob lock do mesmo estoque usado na compra."""
    pending = db.scalars(select(GuildOrder).where(
        GuildOrder.guild_id == store.guild_id,
        GuildOrder.status == 'awaiting_payment',
        GuildOrder.expires_at <= now,
    ).with_for_update()).all()
    if not pending:
        return 0
    snapshot = Snapshot.model_validate(store.payload).model_dump()
    products = {p['id']: p for p in snapshot['products']}
    for order in pending:
        for line in order.items:
            p = products.get(line['product_id'])
            if p and not p['unlimited']:
                p['stock'] += line['quantity']
        order.status = 'expired'
    store.payload = snapshot
    store.revision += 1
    return len(pending)


def output(order):
    return {'id': order.id, 'guild_id': order.guild_id, 'buyer_id': order.buyer_id,
            'status': order.status, 'items': order.items,
            'total': f'{Decimal(order.total_cents) / 100:.2f}',
            'expires_at': order.expires_at.isoformat(),
            'created_at': order.created_at.isoformat()}


@router.post('/guilds/{guild_id}/orders', dependencies=[Depends(require_bot_key)], status_code=201)
def create_order(guild_id: str, payload: CreateOrder, db: Session = Depends(get_db)):
    validate_guild(guild_id)
    ids = [line.product_id for line in payload.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, 'Produtos repetidos no pedido')
    try:
        store = lock_store(db, guild_id)
        now = utcnow()
        expire_locked(db, store, now)
        snapshot = Snapshot.model_validate(store.payload).model_dump()
        products = {p['id']: p for p in snapshot['products']}
        lines = []
        total = 0
        for line in payload.items:
            p = products.get(line.product_id)
            if not p or not p['active']:
                raise HTTPException(409, f'Produto indisponível: {line.product_id}')
            if not p['unlimited'] and p['stock'] < line.quantity:
                raise HTTPException(409, f'Estoque insuficiente: {p["name"]}')
            unit_cents = cents(p['price'])
            total += unit_cents * line.quantity
            lines.append({'product_id': p['id'], 'name': p['name'],
                          'emoji': p.get('emoji') or '📦',
                          'quantity': line.quantity, 'unit_price_cents': unit_cents})
        for line in payload.items:
            if not products[line.product_id]['unlimited']:
                products[line.product_id]['stock'] -= line.quantity
        store.payload = snapshot
        store.revision += 1
        order = GuildOrder(id=str(uuid.uuid4()), guild_id=guild_id,
                           buyer_id=payload.buyer_id, status='awaiting_payment',
                           items=lines, total_cents=total,
                           expires_at=now + timedelta(minutes=payload.reservation_minutes),
                           created_at=now)
        db.add(order)
        db.commit()
        return output(order)
    except Exception:
        db.rollback()
        raise


@router.get('/guilds/{guild_id}/orders/{order_id}', dependencies=[Depends(require_bot_key)])
def read_order(guild_id: str, order_id: str, db: Session = Depends(get_db)):
    validate_guild(guild_id)
    try:
        store = lock_store(db, guild_id)
        expire_locked(db, store, utcnow())
        order = db.get(GuildOrder, order_id)
        if not order or order.guild_id != guild_id:
            raise HTTPException(404, 'Pedido não encontrado')
        db.commit()
        return output(order)
    except Exception:
        db.rollback()
        raise


@router.post('/guilds/{guild_id}/orders/{order_id}/status', dependencies=[Depends(require_bot_key)])
def change_status(guild_id: str, order_id: str, payload: ChangeStatus, db: Session = Depends(get_db)):
    """Operação interna: bot deve validar o papel do usuário antes de chamar."""
    validate_guild(guild_id)
    allowed = {'awaiting_payment': {'payment_review', 'approved', 'rejected', 'cancelled'},
               'payment_review': {'approved', 'rejected'},
               'approved': {'delivered'}}
    try:
        store = lock_store(db, guild_id)
        expire_locked(db, store, utcnow())
        order = db.scalar(select(GuildOrder).where(
            GuildOrder.id == order_id, GuildOrder.guild_id == guild_id).with_for_update())
        if not order:
            raise HTTPException(404, 'Pedido não encontrado')
        # A confirmação do staff independe do botão 'Já paguei'.
        # Aprovação repetida é idempotente para recuperar uma embed perdida.
        if payload.status == 'approved' and order.status == 'approved':
            db.commit()
            return output(order)
        if payload.status not in allowed.get(order.status, set()):
            raise HTTPException(409, 'Transição de status inválida')
        if payload.status in {'cancelled', 'rejected'}:
            snapshot = Snapshot.model_validate(store.payload).model_dump()
            products = {p['id']: p for p in snapshot['products']}
            for line in order.items:
                p = products.get(line['product_id'])
                if p and not p['unlimited']:
                    p['stock'] += line['quantity']
            store.payload = snapshot
            store.revision += 1
        order.status = payload.status
        db.commit()
        return output(order)
    except Exception:
        db.rollback()
        raise


@router.post('/orders/expire', dependencies=[Depends(require_bot_key)])
def expire_all(db: Session = Depends(get_db)):
    """Acionado periodicamente pelo bot/cron na 4.3B; também há expiração sob demanda."""
    total = 0
    guild_ids = db.scalars(select(GuildOrder.guild_id).where(
        GuildOrder.status == 'awaiting_payment', GuildOrder.expires_at <= utcnow()).distinct()).all()
    for guild_id in guild_ids:
        try:
            store = lock_store(db, guild_id)
            total += expire_locked(db, store, utcnow())
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
    return {'expired': total}
