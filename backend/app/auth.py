"""Discord OAuth2 authentication; server-side token exchange, signed HttpOnly session."""
import os
import secrets
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
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
        token = token_response.json().get('access_token')
        user_response = await http.get(f'{DISCORD_API}/users/@me', headers={'Authorization': f'Bearer {token}'})
        if user_response.status_code != 200:
            raise HTTPException(502, 'Não foi possível consultar o perfil do Discord')
        user = user_response.json()
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

@router.post('/logout')
def logout(request: Request):
    # Same-origin POST is required; browser's session cookie cannot be read by JS.
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Origem não autorizada')
    response = RedirectResponse('/', status_code=303)
    response.delete_cookie('sc_session', path='/')
    return response
