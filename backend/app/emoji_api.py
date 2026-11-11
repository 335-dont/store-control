"""Discord application emoji management. Authenticated site users only."""
import base64
import os
import re
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from .store import authorize
from .auth import require_same_origin

router = APIRouter(prefix='/api/store/application-emojis', tags=['application-emojis'])
NAME = re.compile(r'^[a-zA-Z0-9_]{2,32}$')
MIME = {'image/png':'png', 'image/gif':'gif', 'image/webp':'webp'}
MAX_BYTES = 256 * 1024

class EmojiUpload(BaseModel):
    name: str = Field(min_length=2, max_length=32)
    data: str = Field(max_length=400000)

async def discord_request(method, endpoint, payload=None):
    token = os.getenv('DISCORD_BOT_TOKEN', '').strip()
    app_id = os.getenv('DISCORD_APPLICATION_ID', '').strip()
    if not token or not app_id or not app_id.isdecimal():
        raise HTTPException(503, 'Configure DISCORD_BOT_TOKEN e DISCORD_APPLICATION_ID no Railway (serviço web)')
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            response = await client.request(method, f'https://discord.com/api/v10/applications/{app_id}/emojis{endpoint}',
                headers={'Authorization':f'Bot {token}'}, json=payload)
        except httpx.RequestError:
            raise HTTPException(502, 'Não foi possível conectar ao Discord')
    if response.status_code == 429:
        raise HTTPException(429, 'Limite temporário do Discord. Aguarde antes de tentar novamente.')
    if response.status_code in (401,403):
        try:
            error = response.json()
        except ValueError:
            error = {}
        code = error.get('code', 'desconhecido') if isinstance(error, dict) else 'desconhecido'
        if response.status_code == 401:
            raise HTTPException(503, f'Discord HTTP 401 (código {code}): token do bot inválido ou expirado no serviço web. Confira DISCORD_BOT_TOKEN.')
        raise HTTPException(503, f'Discord HTTP 403 (código {code}): acesso negado aos emojis da aplicação. Confirme que DISCORD_APPLICATION_ID pertence ao mesmo bot do token e que a aplicação tem acesso ao recurso.')
    if response.status_code >= 400:
        detail = response.json().get('message', 'Erro do Discord') if response.headers.get('content-type','').startswith('application/json') else 'Erro do Discord'
        raise HTTPException(400 if response.status_code < 500 else 502, f'Discord: {detail}')
    return response.json() if response.content else {}

def as_emoji(e):
    eid=str(e['id'])
    animated=bool(e.get('animated'))
    return {'id':eid, 'name':e['name'], 'animated':animated,
        'code':f"<{'a' if animated else ''}:{e['name']}:{eid}>",
        'url':f'https://cdn.discordapp.com/emojis/{eid}.{"gif" if animated else "png"}'}

@router.get('')
async def list_emojis(request:Request):
    await authorize(request)
    result=await discord_request('GET','')
    return {'emojis':[as_emoji(e) for e in result.get('items',[])]}

@router.post('')
async def create_emoji(request:Request, payload:EmojiUpload):
    require_same_origin(request)
    await authorize(request)
    if not NAME.fullmatch(payload.name):
        raise HTTPException(422,'Nome: 2 a 32 letras, números ou _')
    try:
        head,encoded=payload.data.split(',',1)
        mime=head.removeprefix('data:').split(';',1)[0]
        if mime not in MIME or ';base64' not in head:
            raise ValueError()
        raw=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError):
        raise HTTPException(422,'Imagem inválida; envie PNG, GIF ou WebP')
    if not raw or len(raw)>MAX_BYTES:
        raise HTTPException(422,'Imagem deve ter até 256 KB')
    if not ((mime=='image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or
            (mime=='image/gif' and raw[:6] in (b'GIF87a',b'GIF89a')) or
            (mime=='image/webp' and raw.startswith(b'RIFF') and raw[8:12]==b'WEBP')):
        raise HTTPException(422,'Formato da imagem não corresponde ao arquivo')
    e=await discord_request('POST','',{'name':payload.name,'image':payload.data})
    return {'emoji':as_emoji(e)}

@router.delete('/{emoji_id}')
async def delete_emoji(emoji_id:str,request:Request):
    require_same_origin(request)
    await authorize(request)
    if not emoji_id.isdecimal() or len(emoji_id)>22:
        raise HTTPException(422,'ID inválido')
    await discord_request('DELETE','/'+emoji_id)
    return {'ok':True}
