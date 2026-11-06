"""Etapa 4.2: painel público e carrinho privado (prévia, sem cobrança)."""
import asyncio
import logging
from decimal import Decimal

import discord
import httpx
from discord import app_commands

LOG = logging.getLogger(__name__)
MARKER = 'store-control-cart-owner:'
MAX_LINES = 20
SC_CART_UX_V2 = True


def reais(value):
    return ('R$ ' + format(Decimal(str(value)), '.2f')).replace('.', ',')


class CartState:
    def __init__(self, owner_id, guild_id):
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.items = {}
        self.lock = asyncio.Lock()
        self.message_id = None


class Shop:
    def __init__(self, client, tree, api_url, key):
        self.client = client
        self.tree = tree
        self.api_url = api_url
        self.key = key
        self.carts = {}
        self.creation_locks = {}
        client.add_view(ShopPanel(self))
        self.install_command()

    async def fetch(self, guild_id):
        async with httpx.AsyncClient(timeout=12) as http:
            r = await http.get(f'{self.api_url}/api/bot/guilds/{guild_id}/stock', headers={'X-Bot-Key': self.key})
            r.raise_for_status()
            return r.json()

    async def update_cart(self, interaction, cart, data):
        channel = interaction.channel or await self.client.fetch_channel(interaction.channel_id)
        if cart.message_id is None:
            async for message in channel.history(limit=40):
                if message.author.id == self.client.user.id and message.components:
                    cart.message_id = message.id
                    break
        if cart.message_id is None:
            raise RuntimeError('Mensagem principal do carrinho não encontrada')
        message = await channel.fetch_message(cart.message_id)
        await message.edit(embed=self.cart_embed(cart, data))

    def install_command(self):
        @self.tree.command(name='publicar_loja', description='Publica o painel de compras neste canal')
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def publicar_loja(interaction: discord.Interaction):
            if not interaction.user.guild_permissions.manage_guild:
                return await interaction.response.send_message('Apenas administradores podem publicar a loja.', ephemeral=True)
            embed = discord.Embed(title='🛒 Loja MM2', description='Escolha uma opção abaixo para começar.', color=0xC3A06B)
            embed.add_field(name='Comprar MM2', value='Abra seu carrinho privado.', inline=False)
            embed.add_field(name='Histórico de Compras', value='Disponível em uma próxima etapa.', inline=False)
            embed.add_field(name='Visualizar Estoque', value='Consulte os itens disponíveis.', inline=False)
            try:
                await interaction.channel.send(embed=embed, view=ShopPanel(self))
                await interaction.response.send_message('Painel publicado neste canal.', ephemeral=True)
            except discord.HTTPException:
                await interaction.response.send_message('Não consegui publicar. Verifique minhas permissões.', ephemeral=True)

    async def restore(self):
        # Reinicialização: recupera canais para evitar duplicações. Carrinhos não finalizados
        # recomeçam vazios (não há persistência de itens nesta etapa).
        for guild in self.client.guilds:
            for channel in guild.text_channels:
                if not (channel.topic or '').startswith(MARKER):
                    continue
                try:
                    owner = int(channel.topic[len(MARKER):].strip())
                except ValueError:
                    continue
                if channel.id not in self.carts:
                    cart = CartState(owner, guild.id)
                    self.carts[channel.id] = cart
                    try:
                        async for message in channel.history(limit=20):
                            if message.author.id == self.client.user.id and message.components:
                                cart.message_id = message.id
                                self.client.add_view(CartView(self, cart), message_id=message.id)
                                break
                    except discord.HTTPException:
                        LOG.warning('Não foi possível restaurar controles do canal %s', channel.id)

    async def find_existing(self, guild, owner):
        for channel in guild.text_channels:
            if channel.topic == f'{MARKER}{owner}':
                return channel
        return None

    def cart_embed(self, cart, data):
        products = {p['id']: p for p in data.get('products', [])}
        lines = []
        total = Decimal('0')
        for pid, qty in cart.items.items():
            product = products.get(pid)
            if product:
                subtotal = Decimal(str(product['price'])) * qty
                total += subtotal
                lines.append(f"{product.get('emoji') or '📦'} **{product['name']}** ×{qty} — {reais(subtotal)}")
            else:
                lines.append(f'⚠️ Item indisponível ({pid}) ×{qty}')
        if len(lines) > MAX_LINES:
            lines = lines[:MAX_LINES] + ['… Outros itens no carrinho']
        embed = discord.Embed(title='🛒 Carrinho MM2', description='\n'.join(lines)[:3500] or 'Seu carrinho está vazio. Selecione uma categoria.', color=0xC3A06B)
        embed.add_field(name='Total estimado', value=reais(total), inline=False)
        embed.set_footer(text='Prévia • sem cobrança, pedido ou reserva de estoque')
        return embed


class ShopPanel(discord.ui.View):
    def __init__(self, shop):
        super().__init__(timeout=None)
        self.shop = shop

    @discord.ui.button(label='Comprar MM2', emoji='🛒', style=discord.ButtonStyle.secondary, custom_id='sc42:buy')
    async def buy(self, interaction, button):
        if interaction.guild is None:
            return await interaction.response.send_message('Use dentro do servidor.', ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        lock = self.shop.creation_locks.setdefault((interaction.guild.id, interaction.user.id), asyncio.Lock())
        async with lock:
            existing = await self.shop.find_existing(interaction.guild, interaction.user.id)
            if existing:
                return await interaction.followup.send(f'Você já tem um carrinho: {existing.mention}', ephemeral=True)
            try:
                data = await self.shop.fetch(interaction.guild.id)
                if not data.get('products'):
                    return await interaction.followup.send('Não há produtos disponíveis.', ephemeral=True)
                bot_member = interaction.guild.me
                if bot_member is None:
                    return await interaction.followup.send('Não foi possível verificar as permissões do bot.', ephemeral=True)
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                    bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
                }
                channel = await interaction.guild.create_text_channel(
                    name=f'carrinho-{interaction.user.id}', topic=f'{MARKER}{interaction.user.id}',
                    overwrites=overwrites, reason='Carrinho privado MM2')
                cart = CartState(interaction.user.id, interaction.guild.id)
                self.shop.carts[channel.id] = cart
                message = await channel.send(interaction.user.mention, embed=self.shop.cart_embed(cart, data),
                                   view=CartView(self.shop, cart), allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                cart.message_id = message.id
                await interaction.followup.send(f'Seu carrinho: {channel.mention}', ephemeral=True)
            except (httpx.HTTPError, ValueError):
                LOG.exception('Consulta de estoque falhou')
                await interaction.followup.send('Falha ao consultar o estoque. Tente novamente.', ephemeral=True)
            except discord.HTTPException:
                LOG.exception('Criação do carrinho falhou')
                await interaction.followup.send('Falha ao criar o canal. Verifique a permissão Gerenciar Canais.', ephemeral=True)

    @discord.ui.button(label='Histórico de Compras', emoji='📜', style=discord.ButtonStyle.secondary, custom_id='sc42:history')
    async def history(self, interaction, button):
        await interaction.response.send_message('O histórico estará disponível na etapa de pedidos.', ephemeral=True)

    @discord.ui.button(label='Visualizar Estoque da Loja', emoji='📦', style=discord.ButtonStyle.secondary, custom_id='sc42:stock')
    async def view_stock(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            data = await self.shop.fetch(interaction.guild_id)
            if not data.get('products'):
                return await interaction.followup.send('Nenhum produto disponível.', ephemeral=True)
            await interaction.followup.send('Selecione uma categoria:', view=StockCategories(data, interaction.user.id), ephemeral=True)
        except (httpx.HTTPError, ValueError):
            await interaction.followup.send('Falha ao consultar o estoque.', ephemeral=True)


class StockCategories(discord.ui.View):
    def __init__(self, data, owner):
        super().__init__(timeout=180)
        self.owner = owner
        self.data = data
        cats = [c for c in data['catalogs'] if any(p['catalogId'] == c['id'] for p in data['products'])][:25]
        self.add_item(StockCategorySelect(self, cats))


class StockCategorySelect(discord.ui.Select):
    def __init__(self, parent, cats):
        self.parent = parent
        super().__init__(placeholder='Selecione uma categoria', options=[discord.SelectOption(label=c['name'][:100], value=c['id']) for c in cats])

    async def callback(self, interaction):
        if interaction.user.id != self.parent.owner:
            return await interaction.response.send_message('Esta consulta é privada.', ephemeral=True)
        products = [p for p in self.parent.data['products'] if p['catalogId'] == self.values[0]]
        lines = [f"{p.get('emoji') or '📦'} **{p['name']}** — {reais(p['price'])} | Qtd: {'∞' if p.get('unlimited') else p['stock']}" for p in products]
        content = '\n'.join(lines)
        if len(content) > 3800:
            content = content[:3790] + '…'
        await interaction.response.edit_message(embed=discord.Embed(title='📦 Estoque da loja', description=content or 'Sem produtos.'), view=self.parent)


class CartView(discord.ui.View):
    def __init__(self, shop, cart):
        super().__init__(timeout=None)
        self.shop = shop
        self.cart = cart

    async def interaction_check(self, interaction):
        if interaction.user.id != self.cart.owner_id:
            await interaction.response.send_message('Este carrinho pertence a outro cliente.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Adicionar produto', emoji='➕', style=discord.ButtonStyle.secondary, custom_id='sc42:cart:add')
    async def add(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        try:
            data = await self.shop.fetch(self.cart.guild_id)
            if not data['products']:
                return await interaction.followup.send('Sem produtos disponíveis.', ephemeral=True)
            await interaction.followup.send('Escolha uma categoria:', view=CartCategories(self.shop, self.cart, data), ephemeral=True)
        except (httpx.HTTPError, ValueError):
            await interaction.followup.send('Falha ao consultar estoque.', ephemeral=True)

    @discord.ui.button(label='Remover produto', emoji='➖', style=discord.ButtonStyle.secondary, custom_id='sc42:cart:remove')
    async def remove(self, interaction, button):
        if not self.cart.items:
            return await interaction.response.send_message('Carrinho vazio.', ephemeral=True)
        try:
            data = await self.shop.fetch(self.cart.guild_id)
        except (httpx.HTTPError, ValueError):
            return await interaction.response.send_message('Falha ao consultar produtos.', ephemeral=True)
        await interaction.response.send_message('Selecione um item para remover uma unidade:', view=RemoveView(self.shop, self.cart, data), ephemeral=True)

    @discord.ui.button(label='Finalizar pedido', emoji='💳', style=discord.ButtonStyle.secondary, custom_id='sc42:cart:checkout')
    async def checkout(self, interaction, button):
        await interaction.response.send_message('Pagamento e finalização serão habilitados na próxima etapa. Nenhum estoque foi reservado.', ephemeral=True)

    @discord.ui.button(label='Fechar carrinho', emoji='🗑️', style=discord.ButtonStyle.secondary, custom_id='sc42:cart:close')
    async def close(self, interaction, button):
        await interaction.response.send_message('Fechando seu carrinho...', ephemeral=True)
        try:
            await interaction.channel.delete(reason='Cliente fechou o carrinho')
            self.shop.carts.pop(interaction.channel_id, None)
        except discord.HTTPException:
            LOG.exception('Falha ao fechar carrinho')


class CartCategories(discord.ui.View):
    def __init__(self, shop, cart, data):
        super().__init__(timeout=180)
        cats = [c for c in data['catalogs'] if any(p['catalogId'] == c['id'] for p in data['products'])][:25]
        self.add_item(CartCategorySelect(shop, cart, data, cats))


class CartCategorySelect(discord.ui.Select):
    def __init__(self, shop, cart, data, cats):
        self.shop, self.cart, self.data = shop, cart, data
        super().__init__(placeholder='Selecione uma categoria', options=[discord.SelectOption(label=c['name'][:100], value=c['id']) for c in cats])

    async def callback(self, interaction):
        if interaction.user.id != self.cart.owner_id:
            return await interaction.response.send_message('Sem permissão.', ephemeral=True)
        products = [p for p in self.data['products'] if p['catalogId'] == self.values[0]][:25]
        view = discord.ui.View(timeout=180)
        select = discord.ui.Select(placeholder='Adicionar uma unidade de...', options=[discord.SelectOption(label=p['name'][:100], value=p['id'], description=f"{reais(p['price'])} • Qtd: {'∞' if p.get('unlimited') else p['stock']}"[:100]) for p in products])
        async def picked(i):
            if i.user.id != self.cart.owner_id:
                return await i.response.send_message('Sem permissão.', ephemeral=True)
            pid = select.values[0]
            try:
                latest = await self.shop.fetch(self.cart.guild_id)
            except (httpx.HTTPError, ValueError):
                return await i.response.send_message('Falha ao consultar estoque.', ephemeral=True)
            p = next((x for x in latest['products'] if x['id'] == pid), None)
            if p is None:
                return await i.response.send_message('Produto indisponível.', ephemeral=True)
            async with self.cart.lock:
                current = self.cart.items.get(pid, 0)
                if not p.get('unlimited') and current >= p['stock']:
                    return await i.response.send_message('Limite de estoque atingido.', ephemeral=True)
                self.cart.items[pid] = current + 1
            try:
                await self.shop.update_cart(i, self.cart, latest)
            except (discord.HTTPException, RuntimeError):
                LOG.exception('Falha ao atualizar carrinho')
                return await i.response.edit_message(content='Produto adicionado, mas a embed não foi atualizada.', view=None)
            await i.response.edit_message(content=f"✅ {p.get('emoji') or '📦'} {p['name']} adicionado! Selecione outro produto se desejar.", view=view)
        select.callback = picked
        view.add_item(select)
        await interaction.response.edit_message(content='Escolha um produto:', view=view)


class RemoveView(discord.ui.View):
    def __init__(self, shop, cart, data):
        super().__init__(timeout=180)
        products = {p['id']: p for p in data.get('products', [])}
        options = [discord.SelectOption(
            label=products[pid]['name'][:100] if pid in products else 'Produto indisponível',
            value=pid,
            description=(f"No carrinho: {qty} • {reais(products[pid]['price'])}" if pid in products else f"No carrinho: {qty}")[:100],
            emoji=(products[pid].get('emoji') or None) if pid in products else None,
        ) for pid, qty in list(cart.items.items())[:25]]
        select = discord.ui.Select(placeholder='Remover uma unidade de...', options=options)
        async def picked(interaction):
            if interaction.user.id != cart.owner_id:
                return await interaction.response.send_message('Sem permissão.', ephemeral=True)
            pid = select.values[0]
            async with cart.lock:
                qty = cart.items.get(pid, 0)
                if qty <= 1:
                    cart.items.pop(pid, None)
                else:
                    cart.items[pid] = qty - 1
            try:
                latest = await shop.fetch(cart.guild_id)
                await shop.update_cart(interaction, cart, latest)
            except (httpx.HTTPError, ValueError, discord.HTTPException, RuntimeError):
                LOG.exception('Falha ao atualizar carrinho após remoção')
                return await interaction.response.edit_message(content='Unidade removida, mas a embed não foi atualizada.', view=None)
            await interaction.response.edit_message(content='✅ Unidade removida. Use Remover produto para outra remoção.', view=None)
        select.callback = picked
        self.add_item(select)
