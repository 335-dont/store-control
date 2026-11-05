# Store Control — Etapa 2: seleção de servidores

## O que esta etapa entrega
- `/auth/guilds` lista apenas servidores em que a conta possui `MANAGE_GUILD`, `ADMINISTRATOR` ou é proprietária.
- OAuth2 `identify guilds` com access/refresh token criptografados no PostgreSQL (tabela `discord_credentials`).
- Seleção validada no servidor via `/auth/guilds/{id}/select`, armazenada em cookie assinado HttpOnly.
- Avatar do servidor e link de convite do bot; o status de instalação só é mostrado se `DISCORD_BOT_TOKEN` estiver configurado e a API confirmar.
- Menu de servidores dentro do perfil existente.

## Variáveis
Mantém `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`, `SESSION_SECRET`, `DATABASE_URL`. Opcional: `DISCORD_BOT_TOKEN` para verificar instalações (não expor no frontend nem GitHub).

## Atenção
Esta etapa **não** ativa catálogo por servidor nem escrita no PostgreSQL pelo frontend. A API `/api/*` permanece bloqueada em produção; os módulos do painel ainda usam localStorage. O botão de convite usa permissões `0` como padrão mínimo e deverá ser ajustado para o bot quando ele estiver implementado.

**Após o deploy, faça logout e login novamente** para gerar as credenciais OAuth criptografadas. Não altere `SESSION_SECRET` se quiser manter sessões existentes.

Verifique que `DATABASE_URL` aponta para o PostgreSQL e que o usuário do banco tem permissão de criar a tabela `discord_credentials`.
