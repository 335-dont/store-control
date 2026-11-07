"""Regression: staff can approve without buyer pressing 'Já paguei'."""
import os
import sys
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault('DATABASE_URL', 'sqlite://')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db import Base
from app.store import GuildStore
from app.orders_api import GuildOrder, ChangeStatus, change_status, utcnow


def test_direct_approval_is_idempotent():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = utcnow()
        db.add(GuildStore(guild_id='123', revision=1, payload={'catalogs': [], 'products': []}))
        db.add(GuildOrder(id='order-1', guild_id='123', buyer_id='456', status='awaiting_payment',
                          items=[], total_cents=2100, expires_at=now+timedelta(minutes=20), created_at=now))
        db.commit()
        assert change_status('123', 'order-1', ChangeStatus(status='approved'), db)['status'] == 'approved'
        assert change_status('123', 'order-1', ChangeStatus(status='approved'), db)['status'] == 'approved'
    engine.dispose()


def test_direct_rejection_restores_stock():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = utcnow()
        db.add(GuildStore(guild_id='123', revision=1, payload={
            'catalogs': [{'id': 'c', 'name': 'Itens'}],
            'products': [{'id': 'p', 'catalogId': 'c', 'name': 'Item', 'price': 5.0, 'stock': 1}]}))
        db.add(GuildOrder(id='order-2', guild_id='123', buyer_id='456', status='awaiting_payment',
                          items=[{'product_id': 'p', 'quantity': 2}], total_cents=1000,
                          expires_at=now+timedelta(minutes=20), created_at=now))
        db.commit()
        assert change_status('123', 'order-2', ChangeStatus(status='rejected'), db)['status'] == 'rejected'
        assert db.get(GuildStore, '123').payload['products'][0]['stock'] == 3
    engine.dispose()
