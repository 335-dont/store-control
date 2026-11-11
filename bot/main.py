"""Bot Discord: estoque e painel de carrinho (etapa 4.2)."""
import asyncio
import logging
import os
from decimal import Decimal, InvalidOperation
import discord
import httpx
from discord import app_commands
from cart import Shop, OrderTicketView

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ['DISCORD_BOT_TOKEN']
API_URL = os.environ['STORE_API_URL'].rstrip('/')
INTERNAL_KEY = os.environ['BOT_INTERNAL_KEY']
if not API_URL.startswith('https://'):
    raise RuntimeError('STORE_API_URL deve usar HTTPS')
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
shop = Shop(client, tree, API_URL, INTERNAL_KEY)
client.add_view(OrderTicketView(shop))
client.add_view(OrderTicketView(shop,approved=True))

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
        data = await shop.fetch(guild.id)
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
    await shop.restore()
    if not getattr(client,'_eleve_task',None) or client._eleve_task.done():
        client._eleve_task=asyncio.create_task(panel_update_worker())

async def panel_update_worker():
    await client.wait_until_ready()
    while not client.is_closed():
        try:await shop.process_panel_updates()
        except (httpx.HTTPError,ValueError):logging.exception('Sincronizacao temporariamente indisponivel')
        await asyncio.sleep(10)

async def main():
    async with client:
        await client.login(TOKEN)
        await tree.sync()
        await client.connect(reconnect=True)

if __name__ == '__main__':
    asyncio.run(main())
