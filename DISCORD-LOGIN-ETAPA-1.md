# Etapa 1 — login Discord no cabeçalho

Esta entrega implementa OAuth2 Discord com troca de token no servidor, sessão assinada HttpOnly e avatar animado (GIF quando o hash começa com `a_`). O menu fica no avatar do canto superior direito.

## Configuração no Railway

No Discord Developer Portal, abra sua aplicação > OAuth2 e registre a URL de redirecionamento HTTPS exatamente como `https://SEU-DOMINIO.up.railway.app/auth/callback` (troque pelo domínio real do serviço).

No serviço web Railway, configure estas variáveis de ambiente **sem colocar valores no repositório ou no frontend**:

- `DISCORD_CLIENT_ID`: ID da aplicação Discord
- `DISCORD_CLIENT_SECRET`: segredo OAuth2 da aplicação
- `DISCORD_REDIRECT_URI`: URL HTTPS cadastrada no Discord, terminando em `/auth/callback`
- `SESSION_SECRET`: sequência aleatória com pelo menos 32 caracteres, exclusiva do ambiente

Faça novo deploy após adicionar as variáveis. O usuário entra clicando no círculo do cabeçalho > Entrar com Discord. A rota `/auth/me` retorna apenas dados públicos do perfil autenticado. O token de acesso do Discord não é persistido no navegador.

## Escopo e segurança

**Ainda não é um painel multi-servidor pronto para produção.** Esta etapa só autentica a identidade Discord e exibe o perfil. O OAuth2 solicita `identify guilds`, mas ainda não armazena os tokens nem valida permissões dos servidores. Não é seguro assumir que qualquer usuário autenticado pode ler ou alterar dados da loja.

Por isso, a API de catálogo existente permanece **indisponível em produção** até a implementação de `guild_id`, validação de permissões e autorização por servidor. O frontend de produtos ainda usa localStorage nesta etapa. A próxima entrega precisa migrar os modelos e endpoints com escopo por servidor e depois conectar os componentes ao backend. Não faça cadastro real antes dessa etapa.

Nenhum banco ou serviço Railway foi modificado por este ZIP. Não publicar senhas, tokens, `DATABASE_URL` ou `.env`.
