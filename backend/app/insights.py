"""Server-scoped commerce insights, backed by real GuildOrder rows."""
import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, get_db
from .orders_api import GuildOrder
from .store import authorize, GuildStore

router = APIRouter(prefix='/api/store/insights', tags=['insights'])
PAID = frozenset({'approved', 'delivered'})


class BuyerProfile(Base):
    __tablename__ = 'guild_buyer_profiles'
    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    buyer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, default='')
    avatar_hash: Mapped[str] = mapped_column(String(128), nullable=False, default='')
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def avatar_url(buyer_id, avatar):
    if avatar:
        ext = 'gif' if avatar.startswith('a_') else 'png'
        return f'https://cdn.discordapp.com/avatars/{buyer_id}/{avatar}.{ext}?size=128'
    # Discord's default avatar CDN is public and needs no token.
    try:
        index = (int(buyer_id) >> 22) % 6
    except ValueError:
        index = 0
    return f'https://cdn.discordapp.com/embed/avatars/{index}.png'


async def fill_missing_profiles(db: Session, guild_id: str, buyer_ids: list[str]):
    """Best-effort, bounded lookup of historic clients, cached to limit Discord calls."""
    token = os.getenv('DISCORD_BOT_TOKEN', '').strip()
    if not token:
        return
    known = {p.buyer_id: p for p in db.scalars(select(BuyerProfile).where(
        BuyerProfile.guild_id == guild_id, BuyerProfile.buyer_id.in_(buyer_ids))).all()}
    now = datetime.now(timezone.utc)
    due = []
    for uid in buyer_ids:
        row = known.get(uid)
        if row:
            checked = row.checked_at.replace(tzinfo=timezone.utc) if row.checked_at.tzinfo is None else row.checked_at
            if checked > now - timedelta(hours=24):
                continue
        due.append(uid)
        if len(due) == 8:
            break
    if not due:
        return
    async with httpx.AsyncClient(timeout=3) as client:
        async def lookup(uid):
            try:
                response = await client.get(f'https://discord.com/api/v10/users/{uid}',
                                            headers={'Authorization': f'Bot {token}'})
                if response.status_code == 429:
                    return uid, None, True
                if response.status_code != 200:
                    return uid, None, False
                data = response.json()
                if str(data.get('id')) != uid:
                    return uid, None, False
                return uid, data, False
            except (httpx.HTTPError, ValueError):
                return uid, None, True
        # Bounded lookup; a slow Discord response must not block the dashboard.
        import asyncio
        semaphore = asyncio.Semaphore(3)
        async def limited(uid):
            async with semaphore:
                return await lookup(uid)
        results = await asyncio.gather(*(limited(uid) for uid in due))
    changed = False
    for uid, data, temporary in results:
        if temporary:
            continue
        row = known.get(uid) or BuyerProfile(guild_id=guild_id, buyer_id=uid,
                                               username='', avatar_hash='', checked_at=now)
        if data:
            row.username = str(data.get('global_name') or data.get('username') or '')[:100]
            row.avatar_hash = str(data.get('avatar') or '')[:128]
        row.checked_at = now
        db.add(row)
        changed = True
    if changed:
        db.commit()


@router.get('')
async def insights(request: Request, db: Session = Depends(get_db)):
    guild_id = await authorize(request)
    # Paginate order history; the UI is explicit when the cap is reached.
    rows = db.scalars(select(GuildOrder).where(GuildOrder.guild_id == guild_id)
                      .order_by(GuildOrder.created_at.desc()).limit(2001)).all()
    truncated = len(rows) > 2000
    rows = rows[:2000]
    buyer_ids = list(dict.fromkeys(o.buyer_id for o in rows))
    await fill_missing_profiles(db, guild_id, buyer_ids)
    profiles = {p.buyer_id: p for p in db.scalars(select(BuyerProfile).where(
        BuyerProfile.guild_id == guild_id, BuyerProfile.buyer_id.in_(buyer_ids))).all()} if buyer_ids else {}

    orders = []
    daily = {}
    product_sales = {}
    clients = {}
    total_revenue = 0
    sold_units = 0
    paid_orders = 0
    for o in rows:
        p = profiles.get(o.buyer_id)
        display = p.username if p and p.username else f'Usuário {o.buyer_id[-6:]}'
        avatar = avatar_url(o.buyer_id, p.avatar_hash if p else '')
        paid = o.status in PAID
        order_items = [dict(line) for line in (o.items or [])]
        record = {'id': o.id, 'buyer_id': o.buyer_id, 'buyer_name': display,
                  'buyer_avatar': avatar, 'status': o.status, 'items': order_items,
                  'total_cents': o.total_cents, 'created_at': o.created_at.isoformat(),
                  'expires_at': o.expires_at.isoformat()}
        orders.append(record)
        buyer = clients.setdefault(o.buyer_id, {'buyer_id': o.buyer_id,
            'name': display, 'avatar_url': avatar, 'orders': 0, 'paid_orders': 0,
            'total_cents': 0, 'sold_units': 0, 'last_order': o.created_at.isoformat()})
        buyer['orders'] += 1
        if paid:
            paid_orders += 1
            total_revenue += o.total_cents
            buyer['paid_orders'] += 1
            buyer['total_cents'] += o.total_cents
            day = o.created_at.strftime('%Y-%m-%d')
            daily[day] = daily.get(day, 0) + o.total_cents
            for line in order_items:
                quantity = int(line.get('quantity', 0))
                sold_units += quantity
                buyer['sold_units'] += quantity
                key = str(line.get('product_id') or line.get('name') or '')
                product = product_sales.setdefault(key, {'id': key, 'name': line.get('name') or 'Produto',
                    'emoji': line.get('emoji') or '📦', 'quantity': 0, 'revenue_cents': 0})
                product['quantity'] += quantity
                product['revenue_cents'] += int(line.get('unit_price_cents', 0)) * quantity

    store = db.get(GuildStore, guild_id)
    products = ((store.payload or {}).get('products') or []) if store else []
    stats = {'orders': len(rows), 'paid_orders': paid_orders,
             'awaiting': sum(o.status == 'awaiting_payment' for o in rows),
             'review': sum(o.status == 'payment_review' for o in rows),
             'delivered': sum(o.status == 'delivered' for o in rows),
             'clients': len(clients), 'sold_units': sold_units, 'revenue_cents': total_revenue,
             'active_products': sum(bool(p.get('active')) for p in products),
             'available_units': sum(int(p.get('stock') or 0) for p in products if not p.get('unlimited'))}
    return {'orders': orders, 'clients': sorted(clients.values(),
            key=lambda x: (-x['total_cents'], x['name'])), 'summary': stats,
            'daily': daily, 'top_products': sorted(product_sales.values(),
            key=lambda x: -x['revenue_cents'])[:20], 'truncated': truncated}
