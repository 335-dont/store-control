# Etapa 4.1 — Leitura de estoque no Discord

## O que faz
- `GET /api/bot/guilds/{guild_id}/stock` devolve somente produtos ativos e disponíveis daquele servidor, com catálogo, preço e quantidade.
- Autenticação exclusiva por `X-Bot-Key` (`BOT_INTERNAL_KEY`); não usa cookies de usuário.
- `/estoque` consulta a API com o ID do servidor onde o comando foi executado. Resposta privada (ephemeral), somente leitura.
- Sem compras, reservas, descontos de estoque ou tickets nesta etapa.

## Instalação
1. No serviço **web** da Railway, adicione `BOT_INTERNAL_KEY` com segredo aleatório forte, distinto de `SESSION_SECRET` e `DISCORD_BOT_TOKEN`.
2. Crie **outro serviço** na Railway, conectado ao mesmo repositório, com Dockerfile Path `Dockerfile.bot` (root directory `/`).
3. No serviço do bot, configure `DISCORD_BOT_TOKEN` (token do bot Discord), `STORE_API_URL=https://store-control-production.up.railway.app` e `BOT_INTERNAL_KEY` com **o mesmo valor** do serviço web. Não compartilhe segredos em prints ou no chat.
4. No Discord Developer Portal, habilite os escopos `bot` e `applications.commands` na instalação do bot. A instalação no servidor precisa estar concluída.
5. Faça deploy dos dois serviços e teste `/estoque` no servidor com produtos e em outro servidor vazio.

## Segurança e limites
- Não exponha `BOT_INTERNAL_KEY` no frontend. Não coloque segredos no Git.
- A chave permite consultar o estoque de qualquer servidor: restrinja-a aos serviços backend/bot, faça rotação em caso de vazamento.
- O comando lista apenas os primeiros produtos que couberem numa mensagem; a API devolve a lista completa.
- Uma leitura com status 200 não garante que o bot esteja no servidor; o próprio Discord limita execução do comando aos servidores onde está instalado.
- O endpoint retorna estoque disponível, não é uma API de checkout. Reservas e baixa transacional virão em etapa separada.
