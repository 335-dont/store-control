"""Run with: python -m unittest discover -s backend/tests (from repository root)."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SESSION_SECRET'] = 'test-session-secret-with-at-least-32-characters'
os.environ['DISCORD_REDIRECT_URI'] = 'https://shop.example/auth/callback'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import auth
from app.db import Base
from app.models import DiscordCredential

class AuthTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, DISCORD_REDIRECT_URI='https://shop.example/auth/callback')
        self.env.start()
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db_patch = patch.object(auth, 'SessionLocal', self.sessions)
        self.db_patch.start()
        app = FastAPI()
        app.include_router(auth.router)
        self.client = TestClient(app, base_url='https://shop.example')
        self.client.cookies.set('sc_session', auth.signer().dumps({'id': '42', 'username': 'tester'}), domain='shop.example', path='/')
        self.headers = {'Origin': 'https://shop.example', 'Accept': 'application/json'}
    def tearDown(self):
        self.client.close()
        self.db_patch.stop()
        self.env.stop()
        self.engine.dispose()
    def test_selection_returns_json_and_persists_cookie(self):
        with patch.object(auth, 'managed_guilds', AsyncMock(return_value=[{'id': '123'}])):
            response = self.client.post('/auth/guilds/123/select', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'selected_guild_id': '123'})
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('Secure', response.headers['set-cookie'])
        self.assertEqual(self.client.get('/auth/selected-guild').json()['selected_guild_id'], '123')
    def test_non_admin_cannot_select(self):
        with patch.object(auth, 'managed_guilds', AsyncMock(return_value=[])):
            self.assertEqual(self.client.post('/auth/guilds/123/select', headers=self.headers).status_code, 403)
    def test_logout_behind_http_proxy_and_removes_credentials(self):
        auth.save_credentials('42', 'access', 'refresh', 3600)
        # Internal connection is HTTP while the actual public origin remains HTTPS.
        with TestClient(self.client.app, base_url='http://internal:8000') as internal:
            response = internal.post('/auth/logout', headers={**self.headers, 'Cookie': 'sc_session='+auth.signer().dumps({'id':'42'})})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True})
        for name in ('sc_session', 'sc_guild', 'sc_oauth_state'):
            self.assertTrue(any(name+'=' in c and 'Max-Age=0' in c for c in response.headers.get_list('set-cookie')))
        with self.sessions() as db:
            self.assertIsNone(db.get(DiscordCredential, '42'))
    def test_logout_clears_browser_session(self):
        self.assertEqual(self.client.post('/auth/logout', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get('/auth/me').status_code, 401)
    def test_form_logout_redirect(self):
        response=self.client.post('/auth/logout', headers={'Origin':'https://shop.example'}, follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers['location'],'/')
    def test_rejects_cross_origin_and_missing_origin(self):
        for path in ('/auth/logout', '/auth/guilds/123/select'):
            for origin in ('https://evil.example', 'https://shop.example.evil.example', 'null', 'http://shop.example'):
                self.assertEqual(self.client.post(path, headers={'Origin':origin}).status_code,403)
            self.assertEqual(self.client.post(path).status_code,403)
    def test_referer_fallback_and_explicit_null_rejected(self):
        self.assertEqual(self.client.post('/auth/logout',headers={'Referer':'https://shop.example/dashboard','Accept':'application/json'}).status_code,200)
        self.assertEqual(self.client.post('/auth/logout',headers={'Referer':'https://shop.example/','Origin':'null'}).status_code,403)
    def test_unauthenticated_selection(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/auth/guilds/123/select',headers=self.headers).status_code,401)

if __name__ == '__main__': unittest.main()
