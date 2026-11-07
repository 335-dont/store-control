# This file is installed as bot/loyalty.py by apply_stage45.py.
import logging
import discord
import httpx
LOG = logging.getLogger(__name__)

async def fetch_client(shop, guild_id, buyer_id):
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(f'{shop.api_url}/api/bot/guilds/{guild_id}/loyalty/clients/{buyer_id}',
                           headers={'X-Bot-Key': shop.key})
        r.raise_for_status()
        return r.json()

async def sync_member(shop, guild, buyer_id):
    """Assign highest eligible purchase role, remove only configured purchase roles."""
    data = await fetch_client(shop, guild.id, buyer_id)
    member = guild.get_member(int(buyer_id))
    if member is None:
        try: member = await guild.fetch_member(int(buyer_id))
        except (discord.NotFound, discord.Forbidden): return None
    configured = {int(t['role_id']) for t in data['tiers']}
    eligible = [t for t in data['tiers'] if data['total_cents'] >= t['minimum_cents']]
    target_id = int(max(eligible, key=lambda t: t['minimum_cents'])['role_id']) if eligible else None
    bot_member = guild.me
    if not bot_member or not bot_member.guild_permissions.manage_roles:
        LOG.warning('Sem permissão Gerenciar Cargos em %s', guild.id)
        return None
    removable = [r for r in member.roles if r.id in configured and r.id != target_id and r < bot_member.top_role]
    target = guild.get_role(target_id) if target_id else None
    if target and target >= bot_member.top_role:
        LOG.warning('Cargo %s acima do bot em %s', target.id, guild.id)
        target = None
    if removable: await member.remove_roles(*removable, reason='Atualização de fidelidade Store Control')
    if target and target not in member.roles:
        await member.add_roles(target, reason='Faixa de compras Store Control')
    return target

async def sync_all(shop, guild):
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(f'{shop.api_url}/api/bot/guilds/{guild.id}/loyalty/clients',
                           headers={'X-Bot-Key': shop.key})
        r.raise_for_status()
        data = r.json()
    count = 0
    for client in data['clients']:
        try:
            await sync_member(shop, guild, client['buyer_id'])
            count += 1
        except (discord.HTTPException, httpx.HTTPError, ValueError):
            LOG.exception('Falha na sincronização de %s', client['buyer_id'])
    return count
