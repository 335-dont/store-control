"""Discord OAuth2 authentication; server-side token exchange, signed HttpOnly session."""
import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet
from base64 import urlsafe_b64encode
from sqlalchemy import select
from .db import SessionLocal
from .models import DiscordCredential
from urllib.parse import urlencode, urlsplit
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

router = APIRouter(prefix='/auth')
DISCORD_API = 'https://discord.com/api/v10'

def signer():
    secret = os.getenv('SESSION_SECRET', '')
    if len(secret) < 32:
        raise HTTPException(503, 'SESSION_SECRET não configurado (mínimo 32 caracteres)')
    return URLSafeTimedSerializer(secret, salt='store-control-discord-v1')

def settings():
    client = os.getenv('DISCORD_CLIENT_ID', '')
    secret = os.getenv('DISCORD_CLIENT_SECRET', '')
    redirect = os.getenv('DISCORD_REDIRECT_URI', '')
    if not all((client, secret, redirect)) or not redirect.startswith('https://'):
        raise HTTPException(503, 'OAuth Discord não configurado')
    return client, secret, redirect

def cipher():
    secret = os.getenv('SESSION_SECRET', '')
    if len(secret) < 32:
        raise HTTPException(503, 'SESSION_SECRET não configurado')
    return Fernet(urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))

def save_credentials(user_id, access, refresh, expires_in):
    with SessionLocal() as db:
        row = db.get(DiscordCredential, str(user_id)) or DiscordCredential(user_id=str(user_id))
        row.access_token = cipher().encrypt(access.encode()).decode()
        row.refresh_token = cipher().encrypt(refresh.encode()).decode()
        row.expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(0, int(expires_in) - 60))
        db.add(row)
        db.commit()

async def discord_token(user_id):
    with SessionLocal() as db:
        row = db.get(DiscordCredential, str(user_id))
        if not row:
            raise HTTPException(401, 'Conecte novamente sua conta Discord para selecionar servidores')
        try:
            access = cipher().decrypt(row.access_token.encode()).decode()
            refresh = cipher().decrypt(row.refresh_token.encode()).decode()
        except Exception:
            raise HTTPException(401, 'Sessão Discord precisa ser renovada')
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires > datetime.now(timezone.utc):
            return access
    client, secret, _ = settings()
    async with httpx.AsyncClient(timeout=12) as http:
        r = await http.post('https://discord.com/api/oauth2/token', data={
            'client_id': client, 'client_secret': secret,
            'grant_type': 'refresh_token', 'refresh_token': refresh})
    if r.status_code != 200:
        raise HTTPException(401, 'A autorização do Discord expirou. Entre novamente.')
    data = r.json()
    save_credentials(user_id, data['access_token'], data.get('refresh_token', refresh), data['expires_in'])
    return data['access_token']

def session_user(request: Request):
    cookie = request.cookies.get('sc_session')
    if not cookie:
        return None
    try:
        data = signer().loads(cookie, max_age=60*60*24*7)
        if isinstance(data, dict) and data.get('id'):
            return data
    except (BadSignature, SignatureExpired, HTTPException):
        pass
    return None

@router.get('/login')
def login():
    client, _, redirect = settings()
    state = secrets.token_urlsafe(24)
    state_cookie = signer().dumps(state)
    url = 'https://discord.com/oauth2/authorize?' + urlencode({
        'client_id': client, 'redirect_uri': redirect, 'response_type': 'code',
        'scope': 'identify guilds', 'state': state
    })
    response = RedirectResponse(url, status_code=302)
    response.set_cookie('sc_oauth_state', state_cookie, max_age=600, secure=True,
                        httponly=True, samesite='lax', path='/')
    return response

@router.get('/callback')
async def callback(request: Request, code: str = '', state: str = ''):
    client, secret, redirect = settings()
    signed_state = request.cookies.get('sc_oauth_state', '')
    try:
        expected = signer().loads(signed_state, max_age=600)
    except (BadSignature, SignatureExpired):
        raise HTTPException(400, 'Estado OAuth inválido ou expirado')
    if not code or not secrets.compare_digest(state, expected):
        raise HTTPException(400, 'Estado OAuth não confere')
    async with httpx.AsyncClient(timeout=12) as http:
        token_response = await http.post('https://discord.com/api/oauth2/token', data={
            'client_id': client, 'client_secret': secret, 'grant_type': 'authorization_code',
            'code': code, 'redirect_uri': redirect
        })
        if token_response.status_code != 200:
            raise HTTPException(400, 'Falha na autenticação do Discord')
        token_data = token_response.json()
        token = token_data.get('access_token')
        user_response = await http.get(f'{DISCORD_API}/users/@me', headers={'Authorization': f'Bearer {token}'})
        if user_response.status_code != 200:
            raise HTTPException(502, 'Não foi possível consultar o perfil do Discord')
        user = user_response.json()
    save_credentials(user['id'], token, token_data['refresh_token'], token_data['expires_in'])
    # Não guardar access_token no cookie ou expor credenciais do Discord ao frontend.
    profile = {key: user.get(key) for key in ('id', 'username', 'global_name', 'avatar', 'discriminator')}
    response = RedirectResponse('/', status_code=303)
    response.set_cookie('sc_session', signer().dumps(profile), max_age=604800,
                        secure=True, httponly=True, samesite='lax', path='/')
    response.delete_cookie('sc_oauth_state', path='/')
    return response

@router.get('/me')
def me(request: Request):
    user = session_user(request)
    if not user:
        raise HTTPException(401, 'Faça login com Discord')
    avatar = user.get('avatar')
    extension = 'gif' if avatar and avatar.startswith('a_') else 'png'
    user['avatar_url'] = (f'https://cdn.discordapp.com/avatars/{user["id"]}/{avatar}.{extension}?size=128'
                          if avatar else None)
    return user

def require_same_origin(request: Request):
    # Use the configured public OAuth origin behind a TLS-terminating proxy.
    # Never trust arbitrary X-Forwarded-Host or X-Forwarded-Proto values here.
    public_url = os.getenv('DISCORD_REDIRECT_URI', '').strip()
    expected_url = public_url or str(request.base_url)
    def origin_tuple(value):
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                return None
            return (parsed.scheme.lower(), parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80))
        except ValueError:
            return None
    expected = origin_tuple(expected_url)
    origin = request.headers.get('origin')
    source = origin if origin is not None else request.headers.get('referer', '')
    if not expected or origin_tuple(source) != expected:
        raise HTTPException(403, 'Origem não autorizada')

@router.post('/logout')
def logout(request: Request):
    require_same_origin(request)
    user = session_user(request)
    if user:
        with SessionLocal() as db:
            row = db.get(DiscordCredential, str(user['id']))
            if row:
                db.delete(row)
                db.commit()
    response = (JSONResponse({'ok': True}) if 'application/json' in request.headers.get('accept', '')
                else RedirectResponse('/', status_code=303))
    response.delete_cookie('sc_oauth_state', path='/')
    response.delete_cookie('sc_session', path='/')
    response.delete_cookie('sc_guild', path='/')
    return response

ADMINISTRATOR = 0x8
MANAGE_GUILD = 0x20

async def managed_guilds(request: Request):
    user = session_user(request)
    if not user:
        raise HTTPException(401, 'Faça login com Discord')
    token = await discord_token(user['id'])
    async with httpx.AsyncClient(timeout=15) as http:
        result = await http.get(f'{DISCORD_API}/users/@me/guilds',
                                headers={'Authorization': f'Bearer {token}'})
    if result.status_code == 401:
        raise HTTPException(401, 'Autorização Discord expirada. Entre novamente.')
    if result.status_code != 200:
        raise HTTPException(502, 'Discord indisponível para listar servidores')
    return [g for g in result.json() if g.get('owner') or int(g.get('permissions', '0')) & (ADMINISTRATOR | MANAGE_GUILD)]

@router.get('/guilds')
async def guilds(request: Request):
    allowed = await managed_guilds(request)
    client = os.getenv('DISCORD_CLIENT_ID', '')
    # Sem token de bot, não afirmar se está instalado.
    bot_token = os.getenv('DISCORD_BOT_TOKEN', '')
    bot_guild_ids = None
    if bot_token:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(f'{DISCORD_API}/users/@me/guilds',
                               headers={'Authorization': f'Bot {bot_token}'})
        if r.status_code == 200:
            bot_guild_ids = {str(g['id']) for g in r.json()}
    result = []
    for g in allowed:
        gid = str(g['id'])
        icon = g.get('icon')
        ext = 'gif' if icon and icon.startswith('a_') else 'png'
        result.append({
            'id': gid, 'name': g['name'],
            'icon_url': f'https://cdn.discordapp.com/icons/{gid}/{icon}.{ext}?size=128' if icon else None,
            'bot_installed': None if bot_guild_ids is None else gid in bot_guild_ids,
            'invite_url': ('https://discord.com/oauth2/authorize?' + urlencode({
                'client_id': client, 'scope': 'bot applications.commands',
                'permissions': '0', 'guild_id': gid, 'disable_guild_select': 'true'
            })) if client else None
        })
    return result

@router.post('/guilds/{guild_id}/select')
async def select_guild(guild_id: str, request: Request):
    require_same_origin(request)
    if not guild_id.isdecimal():
        raise HTTPException(400, 'Servidor inválido')
    allowed = await managed_guilds(request)
    if not any(str(g['id']) == guild_id for g in allowed):
        raise HTTPException(403, 'Você não administra esse servidor')
    response = JSONResponse({'selected_guild_id': guild_id})
    response.set_cookie('sc_guild', signer().dumps(guild_id),
                        secure=True, httponly=True, samesite='lax', max_age=604800, path='/')
    return response

@router.get('/selected-guild')
def selected_guild(request: Request):
    if not session_user(request):
        raise HTTPException(401, 'Faça login com Discord')
    signed = request.cookies.get('sc_guild', '')
    try:
        return {'selected_guild_id': signer().loads(signed, max_age=604800)}
    except (BadSignature, SignatureExpired):
        return {'selected_guild_id': None}
