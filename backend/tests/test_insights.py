from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.orders_api import GuildOrder
from app.insights import BuyerProfile, avatar_url, insights
from app.store import GuildStore
import pytest


def test_discord_avatar_urls():
    assert 'https://cdn.discordapp.com/avatars/123456/abc.png?size=128' == avatar_url('123456', 'abc')
    assert '/avatars/123456/a_abc.gif?size=128' in avatar_url('123456', 'a_abc')
    assert '/embed/avatars/' in avatar_url('123456', '')


@pytest.mark.asyncio
async def test_insights_approved_only(monkeypatch):
    async def guild(_request):
        return '100'
    monkeypatch.setattr('app.insights.authorize', guild)
    monkeypatch.delenv('DISCORD_BOT_TOKEN', raising=False)
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine, tables=[GuildStore.__table__, GuildOrder.__table__, BuyerProfile.__table__])
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        for status, amount, idx, guild_id in [('approved', 4000, 'a', '100'),
                                               ('delivered', 2000, 'b', '100'),
                                               ('rejected', 5000, 'c', '100'),
                                               ('approved', 9000, 'd', '200')]:
            db.add(GuildOrder(id=idx,guild_id=guild_id,buyer_id='999',status=status,
                items=[{'product_id':'p','name':'Iceflake','emoji':'❄️','quantity':2,'unit_price_cents':amount//2}],
                total_cents=amount,created_at=now,expires_at=now+timedelta(minutes=15)))
        db.commit()
        result=await insights(object(), db)
        assert result['summary']['orders']==3
        assert result['summary']['paid_orders']==2
        assert result['summary']['revenue_cents']==6000
        assert result['summary']['sold_units']==4
        assert result['summary']['clients']==1
        assert result['top_products'][0]['quantity']==4
        assert result['clients'][0]['total_cents']==6000
    engine.dispose()
