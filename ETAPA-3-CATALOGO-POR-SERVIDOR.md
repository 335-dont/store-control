# Etapa 3 — Catálogo e estoque por servidor

- Nova tabela `guild_stores` criada automaticamente pelo `backend/init_db.py`, sem alterar tabelas antigas.
- Login Discord obrigatório; cada GET/PUT exige guild selecionada e permissão atual de administrar o servidor.
- `PUT /api/store/snapshot` exige revisão igual à do banco. Conflitos retornam 409 e **não sobrescrevem** os dados.
- A interface de Produtos e Estoque usa um estado compartilhado que grava no PostgreSQL e lê no carregamento.
- Dados legados em `localStorage` **não são apagados**. Importe-os explicitamente na página Produtos, somente em servidor vazio.
- Pedidos, reservas, logs e relatórios ainda não estão integrados à nova tabela.

## Validação antes de publicar

1. `python3 -m compileall -q backend/app backend/init_db.py`
2. `cd frontend && npm ci && npm run build`
3. Configure `DATABASE_URL` do PostgreSQL e as variáveis Discord existentes no Railway.
4. Após deploy, entre no Discord, selecione um servidor, crie um catálogo e um produto, aguarde o aviso de salvamento desaparecer, e abra o mesmo servidor em outro dispositivo.
5. Teste dois servidores diferentes e uma conta sem permissão.

**Atenção:** a integração foi preparada, mas não houve teste de ponta a ponta com Discord/Railway/PostgreSQL real neste ambiente. Faça backup dos dados locais antes do deploy.
