"""Discord bot: read-only stock preview. No purchase/reservation actions."""
import asyncio
import logging
import os
from decimal import Decimal, InvalidOperation

import discord
import httpx
from discord import app_commands

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ['DISCORD_BOT_TOKEN']
API_URL = os.environ['STORE_API_URL'].rstrip('/')
INTERNAL_KEY = os.environ['BOT_INTERNAL_KEY']
if not API_URL.startswith('https://'):
    raise RuntimeError('STORE_API_URL deve usar HTTPS')

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def money(value):
    try:
        return f'R$ {Decimal(str(value)):.2f}'.replace('.', ',')
    except (InvalidOperation, ValueError):
        return 'Preço indisponível'


@tree.command(name='estoque', description='Consultar o estoque disponível neste servidor')
@app_commands.guild_only()
async def estoque(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    if guild is None:
        await interaction.followup.send('Use este comando dentro de um servidor.', ephemeral=True)
        return
    try:
        async with httpx.AsyncClient(timeout=12) as http:
            response = await http.get(
                f'{API_URL}/api/bot/guilds/{guild.id}/stock',
                headers={'X-Bot-Key': INTERNAL_KEY},
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        logging.exception('Falha ao consultar estoque do servidor %s', guild.id)
        await interaction.followup.send('Não foi possível consultar o estoque agora. Tente novamente.', ephemeral=True)
        return

    products = data.get('products', [])
    catalogs = {c['id']: c['name'] for c in data.get('catalogs', [])}
    if not products:
        await interaction.followup.send('Nenhum produto disponível neste servidor.', ephemeral=True)
        return

    lines = []
    for p in products:
        quantity = '∞' if p.get('unlimited') else str(p['stock'])
        lines.append(f"• {p['name']} — {money(p['price'])} | Qtd: {quantity} | {catalogs.get(p['catalogId'], 'Catálogo')}")
    # Discord limits message content to 2000 characters; show a bounded preview.
    message = '**Estoque disponível**\n'
    shown = 0
    for line in lines:
        if len(message) + len(line) + 2 > 1850:
            break
        message += line + '\n'
        shown += 1
    if shown < len(lines):
        message += f'\n… e mais {len(lines) - shown} produto(s).'
    await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


@client.event
async def on_ready():
    logging.info('Bot conectado como %s (%s)', client.user, client.user.id)


async def main():
    async with client:
        await client.login(TOKEN)
        await tree.sync()
        await client.connect(reconnect=True)


if __name__ == '__main__':
    asyncio.run(main())
