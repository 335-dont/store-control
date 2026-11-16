"""Painel independente de tickets de suporte — sem interferir em carrinhos/pedidos."""
import asyncio
import logging
import re
import discord
import httpx
from discord import app_commands

LOG = logging.getLogger(__name__)
PANEL_ID = 'eleve:help:choose:v1'
CLOSE_ID = 'eleve:help:close:v1'
TOPIC_PREFIX = 'eleve-support:owner:'
DEFAULT_OPTIONS = [
    {'id': 'general', 'label': 'Suporte geral', 'description': 'Converse com a nossa equipe', 'emoji': '🎫'},
    {'id': 'questions', 'label': 'Dúvidas', 'description': 'Tire suas dúvidas', 'emoji': '❓'},
    {'id': 'other', 'label': 'Outros assuntos', 'description': 'Fale com a staff', 'emoji': '💬'},
]

def safe_options(template):
    values = template.get('options') if isinstance(template, dict) else None
    if not isinstance(values, list):
        return DEFAULT_OPTIONS
    results = []
    for index, item in enumerate(values[:25]):
        if not isinstance(item, dict):
            continue
        label = str(item.get('label') or '').strip()[:100]
        if not label:
            continue
        option_id = str(item.get('id') or f'option-{index}')[:100]
        desc = str(item.get('description') or '').strip()[:100]
        emoji = str((template.get('emojis') or {}).get(f'ticket_option_{index+1}') or item.get('emoji') or '').strip()
        results.append({'id': option_id, 'label': label, 'description': desc, 'emoji': emoji})
    return results

def parse_emoji(emoji):
    if not emoji:
        return None
    # PartialEmoji covers Unicode and application emojis, no Nitro needed.
    try:
        return discord.PartialEmoji.from_str(emoji)
    except (TypeError, ValueError):
        return None

def formatted(text, mapping, template=None):
    result = str(text or '')
    for key, value in mapping.items():
        result = result.replace('{' + key + '}', str(value))
    fallbacks = {'ticket_panel_title': '🎫', 'ticket_open_title': '🎫'}
    for key, fallback in fallbacks.items():
        result = result.replace('{emoji_' + key + '}', str((template or {}).get('emojis', {}).get(key) or fallback))
    for key, value in (template or {}).get('emojis', {}).items():
        result = result.replace('{emoji_' + key + '}', str(value))
    return result

def make_embed(template, title, description, variables=None):
    variables = variables or {}
    template = template if isinstance(template, dict) else {}
    color = 0xC3A06B
    try:
        color = int(str(template.get('color') or '#C3A06B').lstrip('#'), 16)
    except (ValueError, TypeError):
        pass
    embed = discord.Embed(
        title=formatted(template.get('title') or title, variables, template)[:256],
        description=formatted(template.get('description') or description, variables, template)[:4096],
        color=color,
    )
    if template.get('footer'):
        embed.set_footer(text=formatted(template['footer'], variables, template)[:2048])
    for kind in ('image', 'thumbnail'):
        value = str(template.get(kind) or '')
        if value.startswith('https://'):
            getattr(embed, 'set_' + kind)(url=value)
    return embed

def staff_roles(guild, pix):
    roles = []
    role_id = str((pix or {}).get('delivery_role_id') or '')
    if role_id.isdecimal():
        role = guild.get_role(int(role_id))
        if role and role != guild.default_role:
            roles.append(role)
    # Besides the configured staff role, members with administration privileges can access tickets.
    for role in guild.roles:
        if role != guild.default_role and (role.permissions.administrator or role.permissions.manage_guild):
            if role not in roles:
                roles.append(role)
    return roles

class SupportTicketPanelView(discord.ui.View):
    def __init__(self, shop, template=None):
        super().__init__(timeout=None)
        self.shop = shop
        opts = safe_options(template)
        self.select.options = [discord.SelectOption(
            label=o['label'], value=o['id'], description=o['description'] or None,
            emoji=parse_emoji(o['emoji'])
        ) for o in (opts or [DEFAULT_OPTIONS[0]])]
        self.select.placeholder = str((template or {}).get('placeholder') or 'Selecione o assunto do ticket')[:150]

    @discord.ui.select(custom_id=PANEL_ID, placeholder='Selecione o assunto do ticket',
                       options=[discord.SelectOption(label='Suporte geral', value='general')])
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message('Use este painel dentro do servidor.', ephemeral=True)
        selected = select.values[0]
        await interaction.response.defer(ephemeral=True, thinking=True)
        lock = self.shop.creation_locks.setdefault(('eleve-help', interaction.guild.id, interaction.user.id), asyncio.Lock())
        async with lock:
            existing = next((c for c in interaction.guild.text_channels
                             if (c.topic or '').startswith(f'{TOPIC_PREFIX}{interaction.user.id};')), None)
            if existing:
                return await interaction.followup.send(f'Você já tem um ticket aberto: {existing.mention}', ephemeral=True)
            templates = await self.shop.fetch_message_templates(interaction.guild.id)
            panel_tpl = templates.get('ticket_panel') or {}
            options = safe_options(panel_tpl)
            option = next((o for o in options if o['id'] == selected), None)
            if not option:
                return await interaction.followup.send('Esta opção foi alterada. Peça à equipe para republicar o painel.', ephemeral=True)
            bot = interaction.guild.me
            if bot is None:
                return await interaction.followup.send('Não foi possível verificar o bot neste servidor.', ephemeral=True)
            try:
                pix = await self.shop.fetch_pix(interaction.guild.id)
            except (httpx.HTTPError, ValueError):
                pix = {}
            perms = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                bot: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True,
                                                 read_message_history=True, embed_links=True),
            }
            for role in staff_roles(interaction.guild, pix):
                perms[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            name = re.sub(r'[^a-z0-9-]', '-', interaction.user.name.lower()).strip('-')[:45] or str(interaction.user.id)
            try:
                channel = await interaction.guild.create_text_channel(
                    name=f'ticket-{name}'[:95],
                    topic=f'{TOPIC_PREFIX}{interaction.user.id};option:{selected}'[:1024],
                    overwrites=perms,
                    reason=f'Ticket de suporte criado por {interaction.user.id}',
                )
                vars_ = {'cliente': interaction.user.mention, 'assunto': option['label'], 'servidor': interaction.guild.name}
                embed = make_embed(templates.get('ticket_open'), '🎫 Atendimento aberto',
                                   'Olá {cliente}!\n**Assunto:** {assunto}\nDescreva como podemos ajudar.', vars_)
                await channel.send(content=interaction.user.mention, embed=embed,
                                   view=SupportTicketCloseView(self.shop, templates.get('ticket_open')),
                                   allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                await interaction.followup.send(f'Ticket criado: {channel.mention}', ephemeral=True)
            except discord.HTTPException:
                LOG.exception('Falha ao criar ticket de suporte')
                await interaction.followup.send('Não consegui criar o ticket. Verifique as permissões Gerenciar Canais, Ver Canal e Enviar Mensagens.', ephemeral=True)

class ConfirmClose(discord.ui.View):
    def __init__(self, channel_id, requester_id):
        super().__init__(timeout=60)
        self.channel_id = channel_id
        self.requester_id = requester_id

    @discord.ui.button(label='Confirmar fechamento', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.requester_id or interaction.channel_id != self.channel_id:
            return await interaction.response.send_message('Confirmação inválida.', ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel) or not (interaction.channel.topic or '').startswith(TOPIC_PREFIX):
            return await interaction.response.send_message('Este canal não é um ticket de suporte.', ephemeral=True)
        await interaction.response.send_message('Fechando ticket...', ephemeral=True)
        try:
            await interaction.channel.delete(reason=f'Ticket de suporte fechado por {interaction.user.id}')
        except discord.HTTPException:
            LOG.exception('Não consegui fechar ticket')

class SupportTicketCloseView(discord.ui.View):
    def __init__(self, shop, template=None):
        super().__init__(timeout=None)
        self.shop = shop
        self.close.emoji = parse_emoji((template or {}).get('emojis', {}).get('ticket_close') or '🔒')

    @discord.ui.button(label='Fechar ticket', emoji='🔒', style=discord.ButtonStyle.secondary, custom_id=CLOSE_ID)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.channel, discord.TextChannel) or not (interaction.channel.topic or '').startswith(TOPIC_PREFIX):
            return await interaction.response.send_message('Este botão pertence a um ticket de suporte.', ephemeral=True)
        owner_match = re.match(r'^eleve-support:owner:(\d+);', interaction.channel.topic or '')
        is_owner = bool(owner_match and int(owner_match.group(1)) == interaction.user.id)
        perms = getattr(interaction.user, 'guild_permissions', None)
        permitted = bool(perms and (perms.manage_guild or perms.administrator))
        if not permitted and isinstance(interaction.user, discord.Member):
            try:
                pix = await self.shop.fetch_pix(interaction.guild_id)
            except (httpx.HTTPError, ValueError):
                pix = {}
            permitted = any(role in interaction.user.roles for role in staff_roles(interaction.guild, pix))
        if not (is_owner or permitted):
            return await interaction.response.send_message('Somente o cliente ou a staff pode fechar este ticket.', ephemeral=True)
        await interaction.response.send_message('Tem certeza que deseja fechar e excluir este ticket?',
                                                view=ConfirmClose(interaction.channel_id, interaction.user.id), ephemeral=True)

def install_support_tickets(shop, tree, client):
    client.add_view(SupportTicketPanelView(shop))
    client.add_view(SupportTicketCloseView(shop))

    @tree.command(name='painel-ticket', description='Publicar ou atualizar o painel de tickets de suporte')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def painel_ticket(interaction: discord.Interaction):
        perms = getattr(interaction.user, 'guild_permissions', None)
        if not perms or not (perms.manage_guild or perms.administrator):
            return await interaction.response.send_message('Apenas administradores podem publicar o painel.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        templates = await shop.fetch_message_templates(interaction.guild_id)
        tpl = templates.get('ticket_panel') or {}
        options = safe_options(tpl)
        if not options:
            return await interaction.followup.send('Adicione ao menos uma opção no editor do site antes de publicar.', ephemeral=True)
        embed = make_embed(tpl, '🎫 Central de Atendimento', 'Selecione uma opção abaixo para falar com nossa equipe.')
        view = SupportTicketPanelView(shop, tpl)
        try:
            existing = None
            async for msg in interaction.channel.history(limit=100):
                if msg.author.id == client.user.id and any(
                    getattr(component, 'custom_id', None) == PANEL_ID
                    for row in msg.components for component in getattr(row, 'children', [])
                ):
                    existing = msg
                    break
            if existing:
                await existing.edit(embed=embed, view=view)
                text = 'Painel de tickets atualizado neste canal.'
            else:
                await interaction.channel.send(embed=embed, view=view)
                text = 'Painel de tickets publicado neste canal.'
            await interaction.followup.send(text, ephemeral=True)
        except discord.HTTPException:
            LOG.exception('Falha ao publicar painel-ticket')
            await interaction.followup.send('Não consegui publicar o painel. Verifique minhas permissões neste canal.', ephemeral=True)
