from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.push_notifications import PushSubscription
from app.orders_api import GuildOrder, ChangeStatus, change_status
from app.store import GuildStore


def test_push_is_emitted_once_for_new_approval():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(GuildStore(guild_id='111', revision=1, payload={'catalogs':[], 'products':[]}))
        db.add(GuildOrder(id='new-order', guild_id='111', buyer_id='222', status='awaiting_payment',
                          items=[], total_cents=2300, expires_at=datetime.now(timezone.utc)+timedelta(minutes=20),
                          created_at=datetime.now(timezone.utc)))
        db.commit()
        bg=BackgroundTasks()
        response=change_status('111', 'new-order', ChangeStatus(status='approved'), db, bg)
        assert response['status']=='approved'
        assert len(bg.tasks)==1
        bg2=BackgroundTasks()
        change_status('111', 'new-order', ChangeStatus(status='approved'), db, bg2)
        assert len(bg2.tasks)==0
        bg3=BackgroundTasks()
        change_status('111', 'new-order', ChangeStatus(status='delivered'), db, bg3)
        assert len(bg3.tasks)==0


def test_subscriptions_isolated_by_guild_and_account():
    engine=create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for guild,user in [('1','88'),('2','88'),('1','99')]:
            db.add(PushSubscription(guild_id=guild,user_id=user,endpoint_hash='testhash',
                     subscription={'endpoint':'https://web.push.apple.com/path','keys':{'p256dh':'x','auth':'y'}},
                     created_at=datetime.now(timezone.utc)))
        db.commit()
        assert db.query(PushSubscription).filter(PushSubscription.guild_id=='1').count()==2
        assert db.get(PushSubscription,('testhash','88','2')) is not None
