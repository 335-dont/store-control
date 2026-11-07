"""Etapa 4.2: painel público e carrinho privado (prévia, sem cobrança)."""
import asyncio
import logging
import io
import re
import qrcode
from pix_code import pix_code
from decimal import Decimal

import discord
import httpx
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
                                self.client.add_view(CartView(self, cart, await self.fetch(guild.id)), message_id=message.id)
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
                embed=order_embed(order)
                qr_file=None
                if pix.get('key'):
                    code=pix_code(pix['key'],pix['name'],pix['city'],order['total'])
                    qr=qrcode.QRCode(border=2,box_size=8);qr.add_data(code);qr.make(fit=True)
                    image=qr.make_image(fill_color='black',back_color='white')
                    buffer=io.BytesIO();image.save(buffer,format='PNG');buffer.seek(0)
                    qr_file=discord.File(buffer,filename='pix.png')
                    embed.set_image(url='attachment://pix.png')
                    embed.add_field(name='Pix Copia e Cola',value=f'```{code[:900]}```',inline=False)
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
    def __init__(self, view):
        self.ticket_view = view
        super().__init__(placeholder='Ações do Entregador', custom_id='sc43d:staff',
            options=[
                discord.SelectOption(label='Aprovar pagamento', value='approved', emoji='✅'),
                discord.SelectOption(label='Rejeitar pagamento', value='rejected', emoji='❌'),
                discord.SelectOption(label='Marcar entregue', value='delivered', emoji='📦'),
            ], row=1)

    async def callback(self, interaction):
        await self.ticket_view.change(interaction, self.values[0], staff=True)


class OrderTicketView(discord.ui.View):
    def __init__(self, shop):
        super().__init__(timeout=None)
        self.shop = shop
        self.add_item(StaffActionSelect(self))

    async def get_order(self, interaction):
        topic = getattr(interaction.channel, 'topic', '') or ''
        if not topic.startswith('sc-order:') or ';buyer:' not in topic:
            raise ValueError('Este canal não é um ticket de pedido')
        oid, buyer = topic[len('sc-order:'):].split(';buyer:', 1)
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(
                f'{self.shop.api_url}/api/bot/guilds/{interaction.guild_id}/orders/{oid}',
                headers={'X-Bot-Key': self.shop.key})
            r.raise_for_status()
        return r.json(), int(buyer)

    async def change(self, interaction, new_status, staff=False):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            order, buyer = await self.get_order(interaction)
            if staff:
                if not interaction.user.guild_permissions.manage_guild:
                    return await interaction.followup.send('Somente a equipe com Gerenciar Servidor pode realizar esta ação.', ephemeral=True)
            elif interaction.user.id != buyer:
                return await interaction.followup.send('Somente o comprador pode confirmar o pagamento.', ephemeral=True)
            if not staff and order.get('status') == 'payment_review':
                return await interaction.followup.send('A equipe já foi notificada. Envie seu comprovante aqui.', ephemeral=True)
            async with httpx.AsyncClient(timeout=15) as http:
                r = await http.post(
                    f'{self.shop.api_url}/api/bot/guilds/{interaction.guild_id}/orders/{order["id"]}/status',
                    headers={'X-Bot-Key': self.shop.key}, json={'status': new_status})
            if r.status_code == 409:
                return await interaction.followup.send('Esta ação não está disponível para a situação atual do pedido.', ephemeral=True)
            r.raise_for_status()
            updated = r.json()
            if not staff:
                try:
                    await interaction.channel.send(
                        f'<@{buyer}>, após o pagamento, envie o comprovante aqui e aguarde a confirmação de um entregador.\n\n'
                        '🔔 **Entregadores notificados!**',
                        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                except discord.HTTPException:
                    LOG.exception('Notificação não enviada para pedido %s', order['id'])
                return await interaction.followup.send('Pagamento em análise. Envie o comprovante neste canal.', ephemeral=True)
            embed=order_embed(updated)
            if interaction.message.embeds:
                previous=interaction.message.embeds[0]
                if previous.image and previous.image.url:embed.set_image(url=previous.image.url)
                for field in previous.fields:
                    if field.name=='Pix Copia e Cola':embed.add_field(name=field.name,value=field.value,inline=False)
            await interaction.message.edit(embed=embed, view=self)
            try:
                member=interaction.guild.get_member(buyer) or await interaction.guild.fetch_member(buyer)
                await interaction.channel.edit(name=channel_name(new_status,member.name),reason='Status do pedido atualizado')
            except discord.HTTPException:
                LOG.warning('Não foi possível renomear canal %s',interaction.channel_id)
            await interaction.followup.send('Situação do pedido atualizada.', ephemeral=True)
        except (ValueError, httpx.HTTPError, discord.HTTPException):
            LOG.exception('Falha ao atualizar pedido')
            await interaction.followup.send('Não foi possível atualizar o pedido. Tente novamente.', ephemeral=True)

    @discord.ui.button(label='Já paguei — Chamar Entregadores', emoji='💳', style=discord.ButtonStyle.secondary, custom_id='sc43b:paid', row=0)
    async def paid(self, interaction, button):
        await self.change(interaction, 'payment_review')


    @discord.ui.button(label='Copiar e Colar', emoji='🔗', style=discord.ButtonStyle.secondary, custom_id='sc43d:copy', row=0)
    async def copy_pix(self, interaction, button):
        try:
            order, buyer = await self.get_order(interaction)
            if interaction.user.id != buyer:
                return await interaction.response.send_message('Somente o comprador pode consultar o Pix.', ephemeral=True)
            pix = await self.shop.fetch_pix(interaction.guild_id)
            if not pix.get('key'):
                return await interaction.response.send_message('Pix não configurado.', ephemeral=True)
            code = pix_code(pix['key'], pix['name'], pix['city'], order['total'])
            await interaction.response.send_message(code, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except (ValueError, httpx.HTTPError, KeyError):
            LOG.exception('Falha ao consultar Pix')
            await interaction.response.send_message('Não foi possível consultar o Pix.', ephemeral=True)
