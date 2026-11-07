"""Etapa 4.2: painel público e carrinho privado (prévia, sem cobrança)."""
import asyncio
import logging
import io
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import re
import qrcode
from pix_code import pix_code
from decimal import Decimal

import discord
import httpx
from loyalty import sync_member, sync_all, fetch_client
from discord import app_commands

LOG = logging.getLogger(__name__)
MARKER = 'store-control-cart-owner:'
MAX_LINES = 20
SC_CART_NAV_V3 = True
SC_CART_UX_V2 = True


def reais(value):
    return ('R$ ' + format(Decimal(str(value)), '.2f')).replace('.', ',')


def channel_name(status, user):
    labels={'cart':'🛒・carrinho','awaiting_payment':'🟡・pendente',
            'payment_review':'🔵・analise','approved':'🟢・aprovado',
            'rejected':'🔴・rejeitado','cancelled':'⚫・cancelado',
            'expired':'⚫・expirado','delivered':'✅・entregue'}
    username=re.sub(r'[^a-z0-9_-]+','-',str(user).lower()).strip('-')[:40] or 'cliente'
    return f'{labels.get(status,"🛒・carrinho")}-{username}'

async def prune_cart(shop, cart, data):
    products={str(p['id']):p for p in data.get('products',[])}
    removed=[]
    async with cart.lock:
        for pid,qty in list(cart.items.items()):
            p=products.get(str(pid))
            if not p or (not p.get('unlimited') and int(p.get('stock',0))<qty):
                removed.append(cart.names.get(str(pid),'Produto indisponível'))
                cart.items.pop(pid,None)
    return removed

class CartState:
    def __init__(self, owner_id, guild_id):
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.items = {}
        self.names = {}
        self.lock = asyncio.Lock()
        self.message_id = None
        self.stage = 'categories'
        self.category_id = None
        self.selected_id = None


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

    async def fetch_pix(self,guild_id):
        async with httpx.AsyncClient(timeout=12) as http:
            r=await http.get(f'{self.api_url}/api/bot/guilds/{guild_id}/pix',headers={'X-Bot-Key':self.key})
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
        await message.edit(embed=self.cart_embed(cart, data), view=CartView(self, cart, data))

    def install_command(self):
        @self.tree.command(name='sincronizar_cargos', description='Sincroniza os cargos de compras dos clientes com pedidos entregues')
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def sincronizar_cargos(interaction: discord.Interaction):
            if not interaction.user.guild_permissions.manage_guild:
                return await interaction.response.send_message('Apenas administradores podem sincronizar.', ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            try:
                count = await sync_all(self, interaction.guild)
                await interaction.followup.send(f'Sincronização concluída: {count} clientes verificados.', ephemeral=True)
            except (httpx.HTTPError, discord.HTTPException, ValueError):
                LOG.exception('Falha na sincronização de cargos')
                await interaction.followup.send('Não foi possível sincronizar. Verifique o backend e as permissões do bot.', ephemeral=True)
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
        # Reagenda fechamentos pendentes após reinício do processo.
        for guild in self.client.guilds:
            for channel in guild.text_channels:
                match = re.search(r';close_at:(\d+);close_status:(rejected|delivered)$', channel.topic or '')
                if match and (channel.topic or '').startswith('sc-order:'):
                    deadline, status = int(match.group(1)), match.group(2)
                    asyncio.create_task(self.close_channel_at(channel, deadline, status))
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
                                self.client.add_view(CartView(self, cart, await self.fetch(guild.id)), message_id=message.id)
                                break
                    except discord.HTTPException:
                        LOG.warning('Não foi possível restaurar controles do canal %s', channel.id)

    async def close_channel_at(self, channel, deadline, status):
        await asyncio.sleep(max(0, deadline - time.time()))
        try:
            # Evita excluir um canal reaproveitado ou cujo estado mudou.
            topic = channel.topic or ''
            if topic.endswith(f';close_at:{deadline};close_status:{status}') and topic.startswith('sc-order:'):
                await channel.delete(reason=f'Pedido {status} finalizado no Store Control')
        except discord.NotFound:
            pass
        except discord.HTTPException:
            LOG.exception('Falha ao encerrar canal %s', channel.id)

    async def close_channel_at_untracked(self, channel, seconds, status):
        await asyncio.sleep(seconds)
        try:
            topic = channel.topic or ''
            if not topic.startswith('sc-order:') or ';buyer:' not in topic:
                return
            order_id = topic[len('sc-order:'):].split(';buyer:', 1)[0]
            async with httpx.AsyncClient(timeout=15) as http:
                r = await http.get(
                    f'{self.api_url}/api/bot/guilds/{channel.guild.id}/orders/{order_id}',
                    headers={'X-Bot-Key': self.key})
                r.raise_for_status()
            if r.json().get('status') == status:
                await channel.delete(reason=f'Pedido {status} concluído')
        except discord.NotFound:
            pass
        except (discord.HTTPException, httpx.HTTPError, ValueError):
            LOG.exception('Não foi possível encerrar ticket %s', channel.id)

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
                lines.append('⚠️ Produto indisponível — atualize o carrinho')
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
                settings = await self.shop.fetch_pix(interaction.guild.id)
                role_id = settings.get('delivery_role_id', '')
                role = interaction.guild.get_role(int(role_id)) if role_id.isdecimal() else None
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                channel = await interaction.guild.create_text_channel(
                    name=channel_name('cart', interaction.user.name), topic=f'{MARKER}{interaction.user.id}',
                    overwrites=overwrites, reason='Carrinho privado MM2')
                cart = CartState(interaction.user.id, interaction.guild.id)
                self.shop.carts[channel.id] = cart
                message = await channel.send(interaction.user.mention, embed=self.shop.cart_embed(cart, data),
                                   view=CartView(self.shop, cart, data), allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
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


def menu_emoji(value):
    if not value:
        return None
    try:
        return discord.PartialEmoji.from_str(str(value))
    except (ValueError, TypeError):
        return None


class CartView(discord.ui.View):
    """Uma única mensagem editável para todas as etapas do carrinho."""
    def __init__(self, shop, cart, data=None):
        super().__init__(timeout=None)
        self.shop, self.cart = shop, cart
        self.data = data or {'catalogs': [], 'products': []}
        self.build()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.cart.owner_id:
            await interaction.response.send_message('Este carrinho pertence a outro cliente.', ephemeral=True)
            return False
        return True

    def build(self):
        self.clear_items()
        stage = self.cart.stage
        data = self.data
        if stage == 'categories':
            cats = [c for c in data.get('catalogs', []) if any(
                str(p.get('catalogId')) == str(c['id']) for p in data.get('products', []))][:25]
            if cats:
                menu = discord.ui.Select(placeholder='Selecione uma categoria',
                    custom_id='sc43:category', options=[discord.SelectOption(
                        label=c['name'][:100], value=str(c['id']),
                        emoji=menu_emoji(c.get('emoji'))) for c in cats], row=0)
                menu.callback = self.category_selected
                self.add_item(menu)
            if self.cart.items:
                self.button('Ver Carrinho', 'sc43:summary', self.summary, row=1)
        elif stage == 'products':
            products = [p for p in data.get('products', []) if
                str(p.get('catalogId')) == str(self.cart.category_id)][:25]
            if products:
                menu = discord.ui.Select(placeholder='Marque os produtos e confirme a seleção',
                    custom_id='sc43:product', min_values=1, max_values=len(products),
                    options=[discord.SelectOption(
                        label=p['name'][:100], value=str(p['id']),
                        description=(f"Valor: {reais(p['price'])} | Estoque: " +
                            ('∞' if p.get('unlimited') else str(p.get('stock', 0))))[:100],
                        emoji=menu_emoji(p.get('emoji') or '📦')) for p in products], row=0)
                menu.callback = self.product_selected
                self.add_item(menu)
            self.button('Voltar', 'sc43:back', self.back, row=1)
            self.button('Prosseguir ao Carrinho', 'sc43:summary', self.summary, row=1)
        elif stage == 'edit':
            products = {str(p['id']): p for p in data.get('products', [])}
            entries = [(str(pid), qty) for pid, qty in self.cart.items.items() if qty > 0][:25]
            if entries:
                menu = discord.ui.Select(
                    placeholder='Selecione um produto para editar a quantidade',
                    custom_id='sc43:edit', options=[discord.SelectOption(
                        label=products[pid]['name'][:100] if pid in products else 'Produto indisponível',
                        value=pid, description=f'No carrinho: {qty}',
                        emoji=menu_emoji(products[pid].get('emoji')) if pid in products else None)
                        for pid, qty in entries], row=0)
                menu.callback = self.edit_selected
                self.add_item(menu)
            self.button('Continuar Comprando', 'sc43:continue', self.continue_buying, row=1)
            self.button('Finalizar Pedido', 'sc43:checkout', self.checkout, row=1)
            if entries:
                self.button('Esvaziar Carrinho', 'sc43:empty', self.empty, row=2)
        elif stage == 'quantity':
            pid = str(self.cart.selected_id)
            product = next((p for p in data.get('products', []) if str(p['id']) == pid), None)
            if product:
                maximum = 23 if product.get('unlimited') else max(0, min(23, int(product.get('stock', 0))))
                current = self.cart.items.get(pid, 0)
                choices = sorted(set([0, current] + list(range(1, maximum + 1))))[:25]
                menu = discord.ui.Select(
                    placeholder='Escolha a quantidade (0 remove o produto)',
                    custom_id='sc43:quantity', options=[discord.SelectOption(
                        label=f'{n} unidade(s)', value=str(n),
                        description='Remover do carrinho' if n == 0 else
                            reais(Decimal(str(product['price'])) * n)) for n in choices], row=0)
                menu.callback = self.quantity_selected
                self.add_item(menu)
            self.button('Voltar ao Carrinho', 'sc43:quantity-back', self.summary, row=1)

    def button(self, label, custom_id, callback, row):
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary,
                                   custom_id=custom_id, row=row)
        button.callback = callback
        self.add_item(button)

    async def show(self, interaction, data=None):
        if data is None:
            data = await self.shop.fetch(self.cart.guild_id)
        removed = await prune_cart(self.shop, self.cart, data)
        self.data = data
        self.build()
        embed = self.shop.cart_embed(self.cart, data)
        if self.cart.stage == 'categories':
            embed.add_field(name='Categorias', value='Selecione uma categoria abaixo para começar.', inline=False)
        elif self.cart.stage == 'products':
            category = next((c for c in data.get('catalogs', []) if
                str(c['id']) == str(self.cart.category_id)), None)
            embed.add_field(name='Produtos disponíveis', value='Categoria: **' +
                (category['name'] if category else 'Selecionada') +
                '**\nSelecione um produto para adicioná-lo.', inline=False)
        elif self.cart.stage == 'quantity':
            product = next((p for p in data.get('products', []) if
                str(p['id']) == str(self.cart.selected_id)), None)
            embed.add_field(name='Editar quantidade', value=(product['name'] if product else 'Produto') +
                '\nEscolha 0 para remover do carrinho.', inline=False)
        await interaction.response.edit_message(embed=embed, view=self)
        if removed:
            await interaction.followup.send('Itens removidos por falta de estoque: ' + ', '.join(removed)[:1500], ephemeral=True)

    async def category_selected(self, interaction):
        self.cart.category_id = self.children[0].values[0]
        self.cart.stage = 'products'
        try:
            await self.show(interaction)
        except (httpx.HTTPError, ValueError):
            await interaction.response.send_message('Falha ao consultar estoque.', ephemeral=True)

    async def product_selected(self, interaction):
        selected = list(self.children[0].values)
        try:
            latest = await self.shop.fetch(self.cart.guild_id)
            products = {str(p['id']): p for p in latest.get('products', [])}
            async with self.cart.lock:
                invalid = [pid for pid in selected if pid not in products or
                    (not products[pid].get('unlimited') and
                     self.cart.items.get(pid, 0) >= int(products[pid].get('stock', 0)))]
                if invalid:
                    return await interaction.response.send_message(
                        'Um ou mais produtos estão esgotados ou atingiram o limite disponível. Atualize e tente novamente.',
                        ephemeral=True)
                for pid in selected:
                    self.cart.items[pid] = self.cart.items.get(pid, 0) + 1
                    self.cart.names[pid] = products[pid]['name']
            await self.show(interaction, latest)
        except (httpx.HTTPError, ValueError):
            if not interaction.response.is_done():
                await interaction.response.send_message('Falha ao consultar estoque.', ephemeral=True)

    async def back(self, interaction):
        self.cart.stage = 'categories'
        await self.show(interaction)

    async def summary(self, interaction):
        self.cart.stage = 'edit'
        await self.show(interaction)

    async def continue_buying(self, interaction):
        self.cart.stage = 'categories'
        await self.show(interaction)

    async def edit_selected(self, interaction):
        pid = self.children[0].values[0]
        product = next((p for p in self.data.get('products', []) if str(p['id']) == str(pid)), None)
        if product is None:
            return await interaction.response.send_message('Produto não encontrado. Tente novamente.', ephemeral=True)
        await interaction.response.send_modal(QuantityModal(self.shop, self.cart, pid, product))

    async def quantity_selected(self, interaction):
        pid = str(self.cart.selected_id)
        quantity = int(self.children[0].values[0])
        try:
            latest = await self.shop.fetch(self.cart.guild_id)
            product = next((p for p in latest.get('products', []) if str(p['id']) == pid), None)
            if quantity and (not product or (not product.get('unlimited') and
                quantity > int(product.get('stock', 0)))):
                return await interaction.response.send_message('Quantidade indisponível no estoque.', ephemeral=True)
            async with self.cart.lock:
                if quantity == 0:
                    self.cart.items.pop(pid, None)
                else:
                    self.cart.items[pid] = quantity
            self.cart.stage = 'edit'
            await self.show(interaction, latest)
        except (httpx.HTTPError, ValueError):
            await interaction.response.send_message('Falha ao consultar estoque.', ephemeral=True)

    async def checkout(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        latest=await self.shop.fetch(self.cart.guild_id)
        removed=await prune_cart(self.shop,self.cart,latest)
        if removed:
            await self.shop.update_cart(interaction,self.cart,latest)
            return await interaction.followup.send('Produtos removidos por falta de estoque: '+', '.join(removed)[:1500]+'. Confira o carrinho antes de finalizar.',ephemeral=True)
        async with self.cart.lock:
            if not self.cart.items:
                return await interaction.followup.send('Seu carrinho está vazio.',ephemeral=True)
            lines=[{'product_id':str(pid),'quantity':qty} for pid,qty in self.cart.items.items() if qty>0]
            try:
                async with httpx.AsyncClient(timeout=20) as http:
                    response=await http.post(f'{self.shop.api_url}/api/bot/guilds/{self.cart.guild_id}/orders',
                        headers={'X-Bot-Key':self.shop.key},json={'buyer_id':str(self.cart.owner_id),'items':lines,'reservation_minutes':15})
                if response.status_code==409:
                    return await interaction.followup.send('Estoque insuficiente ou alterado. Confira os produtos.',ephemeral=True)
                response.raise_for_status()
                order=response.json()
            except (httpx.HTTPError,ValueError):
                LOG.exception('Falha ao reservar pedido')
                return await interaction.followup.send('Não foi possível reservar os produtos.',ephemeral=True)
            channel=interaction.channel
            try:
                # Garante que a mensagem principal possa ser editada depois da reserva.
                pix=await self.shop.fetch_pix(self.cart.guild_id)
                role_id = pix.get('delivery_role_id', '')
                role = interaction.guild.get_role(int(role_id)) if role_id.isdecimal() else None
                if role:
                    await channel.set_permissions(role, view_channel=True, send_messages=True, read_message_history=True, reason='Equipe de entregas Store Control')
                embed=order_embed(order)
                qr_file=None
                if pix.get('key'):
                    code=pix_code(pix['key'],pix['name'],pix['city'],order['total'])
                    qr=qrcode.QRCode(border=2,box_size=8);qr.add_data(code);qr.make(fit=True)
                    image=qr.make_image(fill_color='black',back_color='white')
                    buffer=io.BytesIO();image.save(buffer,format='PNG');buffer.seek(0)
                    qr_file=discord.File(buffer,filename='pix.png')
                    embed.set_image(url='attachment://pix.png')
                    # O código completo é enviado somente pelo botão privado de copiar.
                else:
                    embed.add_field(name='Pix',value='Aguardando a equipe configurar a chave Pix no painel web.',inline=False)
                # Apaga componentes do carrinho e transforma a mensagem em pedido.
                message=await channel.fetch_message(self.cart.message_id)
                await message.edit(embed=embed,view=OrderTicketView(self.shop),attachments=[qr_file] if qr_file else [])
                await channel.edit(name=channel_name('awaiting_payment',interaction.user.name),
                    topic=f'sc-order:{order["id"]};buyer:{self.cart.owner_id}',reason='Pedido aguardando pagamento')
                self.shop.carts.pop(channel.id,None)
                self.cart.items.clear()
                await interaction.followup.send('Pedido reservado neste mesmo canal. Prazo inicial de pagamento: 15 minutos.',ephemeral=True)
            except Exception:
                LOG.exception('Falha ao transformar carrinho em pedido')
                try:
                    async with httpx.AsyncClient(timeout=15) as http:
                        cancel=await http.post(f'{self.shop.api_url}/api/bot/guilds/{self.cart.guild_id}/orders/{order["id"]}/status',
                            headers={'X-Bot-Key':self.shop.key},json={'status':'cancelled'})
                        cancel.raise_for_status()
                except Exception:
                    LOG.exception('RESERVA %s pode exigir intervenção manual',order['id'])
                    return await interaction.followup.send('Erro na preparação do pagamento. Avise a equipe e informe o pedido '+order['id'],ephemeral=True)
                await interaction.followup.send('Não foi possível preparar o pagamento. Reserva cancelada.',ephemeral=True)

    async def empty(self, interaction):
        async with self.cart.lock:
            self.cart.items.clear()
        self.cart.stage = 'categories'
        await self.show(interaction)


SC_CART_MULTI_MODAL_V1 = True


class QuantityModal(discord.ui.Modal):
    def __init__(self, shop, cart, product_id, product):
        super().__init__(title='Editar quantidade', timeout=300)
        self.shop = shop
        self.cart = cart
        self.product_id = str(product_id)
        self.product_name = product['name']
        self.quantity = discord.ui.TextInput(
            label='Quantidade desejada (0 remove)',
            placeholder='Digite um número inteiro, por exemplo: 3',
            default=str(cart.items.get(self.product_id, 0)),
            min_length=1, max_length=9,
            style=discord.TextStyle.short, required=True)
        self.add_item(self.quantity)

    async def on_submit(self, interaction):
        if interaction.user.id != self.cart.owner_id:
            return await interaction.response.send_message('Este carrinho pertence a outro cliente.', ephemeral=True)
        try:
            qty = int(str(self.quantity.value).strip())
        except ValueError:
            return await interaction.response.send_message('Digite somente um número inteiro.', ephemeral=True)
        if qty < 0:
            return await interaction.response.send_message('A quantidade não pode ser negativa.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            latest = await self.shop.fetch(self.cart.guild_id)
            product = next((p for p in latest.get('products', []) if str(p['id']) == self.product_id), None)
            if qty > 0 and (product is None or (not product.get('unlimited') and qty > int(product.get('stock', 0)))):
                return await interaction.followup.send('Quantidade indisponível no estoque.', ephemeral=True)
            async with self.cart.lock:
                if qty == 0:
                    self.cart.items.pop(self.product_id, None)
                else:
                    self.cart.items[self.product_id] = qty
                self.cart.stage = 'edit'
            channel = interaction.channel or await self.shop.client.fetch_channel(interaction.channel_id)
            if self.cart.message_id is None:
                async for msg in channel.history(limit=40):
                    if msg.author.id == self.shop.client.user.id and msg.components:
                        self.cart.message_id = msg.id
                        break
            if self.cart.message_id is None:
                return await interaction.followup.send('Mensagem principal não encontrada.', ephemeral=True)
            message = await channel.fetch_message(self.cart.message_id)
            view = CartView(self.shop, self.cart, latest)
            await message.edit(embed=self.shop.cart_embed(self.cart, latest), view=view)
            await interaction.followup.send(
                'Produto removido do carrinho.' if qty == 0 else
                f'Quantidade de {self.product_name} atualizada para {qty}.', ephemeral=True)
        except (httpx.HTTPError, ValueError, discord.HTTPException):
            LOG.exception('Erro ao atualizar quantidade do carrinho')
            await interaction.followup.send('Não foi possível atualizar a quantidade. Tente novamente.', ephemeral=True)


# SC_ORDER_43B — tickets e fluxo manual de pagamento

def order_embed(order):
    status_names = {
        'awaiting_payment': 'Aguardando pagamento',
        'payment_review': 'Pagamento em análise',
        'approved': 'Pagamento aprovado',
        'rejected': 'Pagamento rejeitado',
        'cancelled': 'Cancelado',
        'expired': 'Expirado',
        'delivered': 'Entregue',
    }
    lines = [f"📦 **{item['name']}** ×{item['quantity']} — {reais(Decimal(item['unit_price_cents'])*item['quantity']/100)}" for item in order.get('items', [])]
    embed = discord.Embed(
        title='🛒 Pedido Store Control',
        description='\n'.join(lines)[:3500] or 'Sem produtos', color=0xC3A06B)
    embed.add_field(name='Total', value=f"R$ {order['total'].replace('.', ',')}", inline=True)
    embed.add_field(name='Situação', value=status_names.get(order['status'], order['status']), inline=True)
    embed.add_field(name='Pedido', value=f"`{order['id']}`", inline=False)
    embed.set_footer(text='Pagamento manual • a equipe confirma o recebimento')
    return embed


class StaffActionSelect(discord.ui.Select):
    def __init__(self, view, approved=False):
        self.ticket_view = view
        options = ([
            discord.SelectOption(label='Enviar link do servidor privado', value='link', emoji='🔗'),
            discord.SelectOption(label='Notificar cliente', value='notify', emoji='🔔'),
            discord.SelectOption(label='Produto entregue', value='delivered', emoji='📦'),
        ] if approved else [
            discord.SelectOption(label='Aprovar Pagamento', value='approved', emoji='✅'),
            discord.SelectOption(label='Rejeitar Pagamento', value='rejected', emoji='❌'),
        ])
        super().__init__(placeholder='Ações do Entregador', custom_id='sc44:staff:approved' if approved else 'sc44:staff:payment', options=options, row=0)

    async def callback(self, interaction):
        if not await self.ticket_view.is_staff(interaction):
            return await interaction.response.send_message('Você não tem permissão para esta ação.', ephemeral=True)
        action=self.values[0]
        if action == 'delivered':
            return await interaction.response.send_modal(DeliveryProofModal(self.ticket_view))
        if action in ('approved','rejected'):
            order,buyer=await self.ticket_view.get_order(interaction)
            expected=('awaiting_payment', 'payment_review')
            if order['status'] not in expected:
                return await interaction.response.send_message('A situação do pedido mudou. Atualize a mensagem.',ephemeral=True)
            await interaction.response.send_message(
                f'Confirma **{ {"approved":"aprovar o pagamento","rejected":"rejeitar o pagamento","delivered":"marcar como entregue"}[action] }** do pedido de <@{buyer}>?',
                view=ConfirmAction(self.ticket_view,action,order['id'],interaction.user.id),ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
        elif action=='link':
            await self.ticket_view.send_saved_private_server(interaction)
        elif action=='notify':
            order,buyer=await self.ticket_view.get_order(interaction)
            if order['status']!='approved':
                return await interaction.response.send_message('O pedido ainda não foi aprovado.',ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            try:
                user=await interaction.client.fetch_user(buyer)
                await user.send(f'🔔 O entregador está chamando você para receber o pedido **{order["id"][:8]}** no servidor {interaction.guild.name}.')
                await interaction.followup.send('Cliente notificado por mensagem privada.',ephemeral=True)
            except discord.HTTPException:
                await interaction.followup.send('Não foi possível enviar DM ao cliente.',ephemeral=True)


class ConfirmAction(discord.ui.View):
    def __init__(self,ticket,action,order_id,staff_id):
        super().__init__(timeout=120)
        self.ticket=ticket;self.action=action;self.order_id=order_id;self.staff_id=staff_id

    @discord.ui.button(label='Confirmar',style=discord.ButtonStyle.success)
    async def confirm(self,interaction,button):
        if interaction.user.id!=self.staff_id or not await self.ticket.is_staff(interaction):
            return await interaction.response.send_message('Confirmação restrita ao funcionário.',ephemeral=True)
        self.stop()
        await self.ticket.change(interaction,self.action,expected_id=self.order_id)

    @discord.ui.button(label='Cancelar',style=discord.ButtonStyle.secondary)
    async def cancel(self,interaction,button):
        if interaction.user.id!=self.staff_id:
            return await interaction.response.send_message('Esta confirmação não é sua.',ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content='Ação cancelada.',view=None)


class DeliveryProofModal(discord.ui.Modal, title='Comprovantes de Entrega'):
    def __init__(self, ticket):
        super().__init__(timeout=300)
        self.ticket = ticket
        self.proofs = discord.ui.FileUpload(
            custom_id='sc44c:proofs', required=False, min_values=0, max_values=5)
        self.add_item(discord.ui.Label(
            text='Comprovantes da entrega (opcional)',
            description='Envie prints PNG, JPG, JPEG ou WEBP', component=self.proofs))

    async def on_submit(self, interaction):
        if not await self.ticket.is_staff(interaction):
            return await interaction.response.send_message('Acesso negado.', ephemeral=True)
        files = list(self.proofs.values or [])
        if any(not (f.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')))
               for f in files):
            return await interaction.response.send_message('Envie apenas imagens PNG, JPG, JPEG ou WEBP.', ephemeral=True)
        await self.ticket.change(interaction, 'delivered', proofs=files)


class PrivateServerModal(discord.ui.Modal,title='Enviar servidor privado'):
    link=discord.ui.TextInput(label='Link do servidor privado Roblox',placeholder='https://www.roblox.com/...',max_length=500)
    username=discord.ui.TextInput(label='Usuário Roblox (opcional)',required=False,max_length=50)

    def __init__(self,ticket):
        super().__init__(timeout=180)
        self.ticket=ticket

    async def on_submit(self,interaction):
        if not await self.ticket.is_staff(interaction):
            return await interaction.response.send_message('Acesso negado.',ephemeral=True)
        order,buyer=await self.ticket.get_order(interaction)
        if order['status']!='approved':
            return await interaction.response.send_message('O pagamento não está aprovado.',ephemeral=True)
        url=str(self.link.value).strip()
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in ('roblox.com','www.roblox.com') or not parsed.path.startswith('/games/'):
            return await interaction.response.send_message('Informe um link HTTPS válido de servidor privado no roblox.com/games/.',ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        embed=discord.Embed(title='🎮 Servidor privado disponível',description='O entregador enviou o acesso para receber seus produtos.',color=0x57F287)
        if str(self.username.value).strip():
            embed.add_field(name='Usuário Roblox',value=discord.utils.escape_markdown(str(self.username.value).strip()),inline=False)
        view=discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label='Entrar no servidor privado',url=url))
        await interaction.channel.send(content=f'<@{buyer}>',embed=embed,view=view,allowed_mentions=discord.AllowedMentions(users=True,roles=False,everyone=False))
        await interaction.followup.send('Link enviado ao comprador.',ephemeral=True)


class OrderTicketView(discord.ui.View):
    def __init__(self,shop,approved=False):
        super().__init__(timeout=None)
        self.shop=shop
        self.approved=approved
        self.add_item(StaffActionSelect(self,approved=approved))
        if not approved:
            copy=discord.ui.Button(label='Copiar e Colar',emoji='🔗',style=discord.ButtonStyle.secondary,custom_id='sc44:copy',row=1)
            copy.callback=self.copy_pix
            self.add_item(copy)
            paid=discord.ui.Button(label='Já paguei — Chamar Entregadores',emoji='💳',style=discord.ButtonStyle.secondary,custom_id='sc44:paid',row=1)
            paid.callback=self.paid
            self.add_item(paid)

    async def get_order(self,interaction):
        topic=getattr(interaction.channel,'topic','') or ''
        if not topic.startswith('sc-order:') or ';buyer:' not in topic:
            raise ValueError('Canal sem pedido')
        oid,buyer=topic[len('sc-order:'):].split(';buyer:',1)
        async with httpx.AsyncClient(timeout=15) as http:
            r=await http.get(f'{self.shop.api_url}/api/bot/guilds/{interaction.guild_id}/orders/{oid}',headers={'X-Bot-Key':self.shop.key})
            r.raise_for_status()
        return r.json(),int(buyer)

    async def is_staff(self,interaction):
        if not interaction.guild or not isinstance(interaction.user,discord.Member):return False
        if interaction.user.guild_permissions.manage_guild:return True
        try:
            settings=await self.shop.fetch_pix(interaction.guild_id)
            role=settings.get('delivery_role_id')
            return bool(role and any(str(r.id)==str(role) for r in interaction.user.roles))
        except httpx.HTTPError:return False

    async def send_saved_private_server(self, interaction):
        # Responder imediatamente; buscar dados e publicar pode levar mais de 3 segundos.
        await interaction.response.defer(ephemeral=True)
        try:
            order, buyer = await self.get_order(interaction)
            if order['status'] != 'approved':
                return await interaction.followup.send('O pagamento ainda não foi aprovado.', ephemeral=True)
            settings = await self.shop.fetch_pix(interaction.guild_id)
            url = (settings.get('private_server_url') or '').strip()
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname not in ('www.roblox.com', 'roblox.com') or not url:
                return await interaction.followup.send('Cadastre primeiro o link do servidor privado no painel web, em Configuração Pix.', ephemeral=True)
            embed = discord.Embed(
                title='Store Control',
                description=('• Entre em um de nossos servidores VIP abaixo\n'
                             '• Ao entrar em nosso servidor, avise o entregador neste canal '
                             'e aguarde seu produto ser entregue!\n\n'
                             f'> {url}'),
                color=0xD6B37A)
            # Foto do funcionário que enviou o link, como na referência.
            # display_avatar funciona tanto com avatar personalizado quanto com o padrão.
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_footer(text=f'Store Control © {datetime.now(timezone.utc).year} • Entrega manual')
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label='Entrar no Servidor', emoji='🔰', url=url))
            await interaction.channel.send(content=f'<@{buyer}>', embed=embed, view=view,
                                           allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
            await interaction.followup.send('Link salvo enviado ao comprador.', ephemeral=True)
        except (ValueError, httpx.HTTPError, discord.HTTPException):
            LOG.exception('Erro ao enviar servidor privado salvo')
            await interaction.followup.send('Não foi possível enviar o link. Verifique as configurações.', ephemeral=True)

    async def paid(self,interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            order,buyer=await self.get_order(interaction)
            if interaction.user.id!=buyer:
                return await interaction.followup.send('Apenas o comprador pode confirmar.',ephemeral=True)
            if order['status']=='payment_review':
                return await interaction.followup.send('A equipe já foi notificada.',ephemeral=True)
            if order['status']!='awaiting_payment':
                return await interaction.followup.send('Pedido não está aguardando pagamento.',ephemeral=True)
            async with httpx.AsyncClient(timeout=15) as http:
                r=await http.post(f'{self.shop.api_url}/api/bot/guilds/{interaction.guild_id}/orders/{order["id"]}/status',headers={'X-Bot-Key':self.shop.key},json={'status':'payment_review'})
                r.raise_for_status()
            settings=await self.shop.fetch_pix(interaction.guild_id)
            role=settings.get('delivery_role_id','')
            mention=f'<@&{role}>' if role and role.isdecimal() and interaction.guild.get_role(int(role)) else ''
            await interaction.channel.send(f'{mention} <@{buyer}> informou que realizou o pagamento. Envie o comprovante neste canal e aguarde a equipe.',allowed_mentions=discord.AllowedMentions(users=True,roles=bool(mention),everyone=False))
            await interaction.followup.send('Equipe notificada. Envie o comprovante aqui.',ephemeral=True)
        except (ValueError,httpx.HTTPError,discord.HTTPException):
            LOG.exception('Falha ao notificar pagamento')
            await interaction.followup.send('Não foi possível notificar a equipe.',ephemeral=True)

    async def copy_pix(self,interaction):
        try:
            order,buyer=await self.get_order(interaction)
            if interaction.user.id!=buyer:
                return await interaction.response.send_message('Somente o comprador pode copiar o Pix.',ephemeral=True)
            settings=await self.shop.fetch_pix(interaction.guild_id)
            code=pix_code(settings['key'],settings['name'],settings['city'],order['total'])
            await interaction.response.send_message(code,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        except (ValueError,httpx.HTTPError,KeyError):
            LOG.exception('Falha ao gerar Pix')
            await interaction.response.send_message('Não foi possível gerar o Pix.',ephemeral=True)

    async def change(self, interaction, status, expected_id=None, proofs=None):
        # Responde à interação antes de qualquer operação de rede potencialmente lenta.
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        try:
            if not await self.is_staff(interaction):
                return await interaction.followup.send('Acesso negado.', ephemeral=True)
            order, buyer = await self.get_order(interaction)
            if expected_id and order['id'] != expected_id:
                return await interaction.followup.send('O pedido foi alterado.', ephemeral=True)
            expected = ('approved',) if status == 'delivered' else ('awaiting_payment', 'payment_review')
            if order['status'] not in expected:
                if status == 'approved' and order['status'] == 'approved':
                    await interaction.followup.send('Pagamento já aprovado. Restaurando a mensagem.', ephemeral=True)
                    await self.publish_approved(interaction.channel, order, buyer)
                    return
                return await interaction.followup.send(f'Pedido em situação {order["status"]}; ação indisponível.', ephemeral=True)
            async with httpx.AsyncClient(timeout=15) as http:
                r = await http.post(
                    f'{self.shop.api_url}/api/bot/guilds/{interaction.guild_id}/orders/{order["id"]}/status',
                    headers={'X-Bot-Key': self.shop.key}, json={'status': status})
            if r.status_code == 409:
                # Pode ser uma versão antiga da API no Railway ou uma ação concorrente.
                # Consultar o estado real evita acusar outro funcionário indevidamente.
                latest, _ = await self.get_order(interaction)
                if status == 'approved' and latest['status'] == 'approved':
                    await interaction.followup.send('Pagamento já aprovado. Recuperando a mensagem de entrega.', ephemeral=True)
                    await self.publish_approved(interaction.channel, latest, buyer)
                    return
                detail = r.text[:350]
                LOG.warning('Transição recusada: pedido=%s atual=%s destino=%s resposta=%s', order['id'], latest['status'], status, detail)
                return await interaction.followup.send(
                    f'Não foi possível {"aprovar" if status == "approved" else "atualizar"} o pedido (status atual: {latest["status"]}). '
                    'Confirme que o backend da Etapa 4.4F foi publicado no Railway.', ephemeral=True)
            r.raise_for_status()
            updated = r.json()
            # Nunca bloquear a resposta do funcionário aguardando PATCH de canal (429).
            if status == 'approved':
                await interaction.followup.send('Pagamento aprovado. Limpando o ticket e publicando a compra confirmada.', ephemeral=True)
                await self.publish_approved(interaction.channel, updated, buyer)
            elif status == 'rejected':
                asyncio.create_task(self.shop.close_channel_at_untracked(interaction.channel, 15, 'rejected'))
                await interaction.followup.send('Pagamento rejeitado. Ticket será encerrado em 15 segundos.', ephemeral=True)
                try:
                    await interaction.channel.send('❌ Pagamento rejeitado. Este canal será fechado em **15 segundos**.')
                except discord.HTTPException:
                    LOG.exception('Falha ao notificar rejeição')
            elif status == 'delivered':
                asyncio.create_task(self.shop.close_channel_at_untracked(interaction.channel, 45, 'delivered'))
                await interaction.followup.send('Entrega registrada. Ticket será encerrado em 45 segundos.', ephemeral=True)
                try:
                    await sync_member(self.shop, interaction.guild, buyer)
                except (discord.HTTPException, httpx.HTTPError, ValueError):
                    LOG.exception('Não foi possível sincronizar cargo de compras do cliente %s', buyer)
                await self.delivery_log(interaction, updated, buyer, proofs=proofs)
                try:
                    await interaction.channel.send('✅ Pedido entregue! Este canal será fechado em **45 segundos**.')
                except discord.HTTPException:
                    LOG.exception('Falha ao notificar entrega')
        except (ValueError, httpx.HTTPError, discord.HTTPException):
            LOG.exception('Erro na atualização do pedido')
            await interaction.followup.send('Não foi possível concluir a ação. Confira o estado do pedido.', ephemeral=True)

    async def publish_approved(self, channel, order, buyer):
        """Publica a fase de entrega independentemente do clique em Já paguei.

        Discord pode impor rate limits a exclusões; nunca deixa a compra aprovada
        sem a mensagem da nova fase caso a limpeza seja parcialmente bloqueada.
        """
        removed = 0
        failed = 0
        try:
            # Em canais recém-criados, bulk delete é mais econômico. A biblioteca
            # faz a exclusão individual das mensagens antigas, se necessário.
            removed = len(await channel.purge(limit=None, bulk=True,
                reason='Limpeza do ticket após aprovação de pagamento'))
        except (discord.Forbidden, discord.HTTPException) as exc:
            LOG.warning('Limpeza em lote falhou no ticket %s: %s. Tentando individualmente.', channel.id, exc)
            try:
                async for message in channel.history(limit=None):
                    try:
                        await message.delete()
                        removed += 1
                    except (discord.Forbidden, discord.HTTPException):
                        failed += 1
            except (discord.Forbidden, discord.HTTPException):
                LOG.exception('Não foi possível concluir a limpeza do ticket %s', channel.id)
                failed += 1
        # Embed própria da fase de entrega, sem Pix/QR e sem campos técnicos.
        lines = [f"• 📦 **{item['name']}** ({item['quantity']}x) — "
                 f"{reais(Decimal(item['unit_price_cents']) * item['quantity'] / 100)}"
                 for item in order.get('items', [])]
        embed = discord.Embed(
            title='Compra Confirmada',
            description=('✅ Um dos produtos que você adquiriu possui entrega manual. '
                         'Basta aguardar um de nossos entregadores para receber sua compra.\n\n'
                         '**🛍️ Produtos Adquiridos**\n' + ('\n'.join(lines) or 'Nenhum produto') +
                         f'\n\n**💰 Total:** R$ {order["total"].replace(".", ",")}\n\n'
                         f'**👤 Comprador**\n<@{buyer}>\n\n'
                         '**📦 Entrega**\nAssim que um entregador assumir seu pedido, '
                         'ele enviará uma mensagem neste canal e realizará a entrega.'),
            color=0xD6B37A)
        embed.set_footer(text=f'Store Control © {datetime.now(timezone.utc).year}')
        try:
            await channel.send(embed=embed, view=OrderTicketView(self.shop, approved=True))
            # Renomear somente se necessário, para reduzir PATCHs e rate limits.
            desired_name = channel_name('approved', channel.name.split('-', 1)[-1])
            if not channel.name.startswith('🟢'):
                try:
                    await channel.edit(name=desired_name, reason='Pagamento aprovado')
                except discord.HTTPException:
                    LOG.warning('Canal %s aprovado, mas renomeação foi limitada pelo Discord', channel.id)
            LOG.info('Pedido %s aprovado: %s mensagens removidas, %s falhas', order['id'], removed, failed)
        except discord.HTTPException:
            LOG.exception('Falha ao publicar embed de entrega no ticket %s', channel.id)
            try:
                await channel.send('⚠️ Pagamento aprovado, mas não foi possível publicar a embed. Avise a equipe.')
            except discord.HTTPException:
                LOG.exception('Falha até no aviso de publicação do ticket %s', channel.id)

    async def delivery_log(self, interaction, order, buyer, proofs=None):
        """Recibo de entrega com cargo e emojis do catálogo, no layout de referência."""
        try:
            settings = await self.shop.fetch_pix(interaction.guild_id)
            cid = str(settings.get('deliveries_channel_id') or '').strip()
            channel = interaction.guild.get_channel(int(cid)) if cid.isdecimal() else None
            if not isinstance(channel, discord.TextChannel):
                LOG.warning('Canal de entregas não configurado no servidor %s', interaction.guild_id)
                return

            member = interaction.guild.get_member(buyer)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(buyer)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    member = None
            user = member
            if user is None:
                try:
                    user = await self.shop.client.fetch_user(buyer)
                except (discord.NotFound, discord.HTTPException):
                    user = None

            # Exibe somente o cargo de compras correspondente ao total entregue.
            role_text = ''
            try:
                loyalty = await fetch_client(self.shop, interaction.guild_id, buyer)
                eligible = [t for t in loyalty['tiers'] if loyalty['total_cents'] >= t['minimum_cents']]
                if eligible:
                    chosen = max(eligible, key=lambda t: t['minimum_cents'])
                    role = interaction.guild.get_role(int(chosen['role_id']))
                    if role is not None and member is not None and role in member.roles:
                        role_text = f' {role.mention}'
            except (httpx.HTTPError, ValueError, KeyError):
                LOG.exception('Falha ao obter cargo de compras para entrega')

            items = order.get('items') or []
            # Pedidos antigos podem não ter emoji salvo. Recupera do catálogo
            # atual apenas quando necessário; pedidos novos preservam o original.
            missing_emoji = any(not item.get('emoji') for item in items)
            emojis_by_id = {}
            if missing_emoji:
                try:
                    stock = await self.shop.fetch(interaction.guild_id)
                    payload = stock.get('data', stock)
                    emojis_by_id = {str(p.get('id')): p.get('emoji') for p in payload.get('products', [])}
                except (httpx.HTTPError, ValueError, TypeError, KeyError):
                    LOG.warning('Não foi possível recuperar emojis do estoque para entrega %s', order.get('id'))

            lines = []
            for item in items:
                name = discord.utils.escape_markdown(str(item.get('name') or 'Produto'))
                qty = int(item.get('quantity') or 0)
                cents = int(item.get('unit_price_cents') or 0)
                subtotal = Decimal(cents * qty) / Decimal(100)
                price = reais(subtotal)
                emoji = str(item.get('emoji') or emojis_by_id.get(str(item.get('product_id'))) or '📦').strip()
                # Não permite que conteúdo do catálogo insira menções ou quebras extras.
                emoji = emoji.splitlines()[0][:120] if emoji else '📦'
                lines.append(f'• {emoji} **{name}** ({qty}x) - `{price}`')

            products = '\n'.join(lines) or 'Nenhum produto informado'
            # Discord limita a descrição a 4096 caracteres.
            total = reais(order.get('total') or '0')
            heading = (
                f'👤 **Cliente**\n<@{buyer}>{role_text}\n\n'
                f'💵 **Valor Pago**\n`{total}`\n\n'
                '🛍️ **Produtos Adquiridos**\n'
            )
            max_products = max(0, 4096 - len(heading) - 3)
            if len(products) > max_products:
                products = products[:max_products - 3] + '...'
            embed = discord.Embed(
                title='🛒 Novo Pedido Entregue',
                description=heading + products,
                color=0xD6B37A,
            )
            if user is not None:
                embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text='Agradecemos pela sua preferência!')

            files = [await attachment.to_file() for attachment in proofs] if proofs else []
            await channel.send(
                embed=embed, files=files,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (httpx.HTTPError, discord.HTTPException, ValueError, TypeError):
            LOG.exception('Falha ao publicar entrega')

    async def schedule_close(self, channel, seconds, status):
        deadline = int(time.time()) + seconds
        topic = re.sub(r';close_at:\d+;close_status:(rejected|delivered)$', '', channel.topic or '')
        await channel.edit(topic=f'{topic};close_at:{deadline};close_status:{status}', reason='Agendar fechamento automático')
        asyncio.create_task(self.shop.close_channel_at(channel, deadline, status))
