# Store Control — pacote de preparação Railway

## O que está pronto
- O painel React original foi mantido, compilado e servido pela FastAPI no mesmo serviço.
- PostgreSQL existente na Railway pode ser conectado usando referência privada `${{Postgres.DATABASE_URL}}` (o nome do serviço deve ser conferido na sua Railway).
- A API `/api/*` exige cabeçalho `X-API-Key` em produção. A chave **nunca deve ser colocada no JavaScript público**.
- O site pode ser aberto pelo iPhone em HTTPS após configurar domínio público Railway.

## O que ainda NÃO está pronto
- O painel continua usando `localStorage` e não sincroniza com PostgreSQL.
- O bot Discord ainda não está implementado neste pacote.
- Não existe login de usuário nem autorização granular; os endpoints API ficam bloqueados para o navegador em produção.
- `init_db.py` usa `create_all` para banco novo; é bootstrap inicial, **não é migração de esquema**.
- Não usar dados reais de clientes, estoque ou pagamentos até implementar autenticação e testar backups.

## Publicar quando o código estiver no GitHub
1. Railway > projeto existente > Add Service > GitHub Repository > `store-control`.
2. O Dockerfile e `railway.json` estão na **raiz** do repositório; configure root directory `/`.
3. No serviço novo, em Variables, adicione `DATABASE_URL` como **referência à variável** `DATABASE_URL` do serviço Postgres (normalmente `${{Postgres.DATABASE_URL}}`; confirme o nome exato).
4. Adicione `API_ACCESS_KEY` com valor aleatório forte gerado em gerenciador de senhas (não envie essa chave pelo chat).
5. Adicione `APP_ENV=production`.
6. Deploy. Depois, Settings > Networking > Generate Domain e abra a URL HTTPS no Safari.
7. Acesse `/health` para confirmar a API. `/api/*` retorna 401 sem a chave: **isso é esperado**.
8. Confira custos e créditos; banco + serviço web consomem recursos continuamente. Limite financeiro pode interromper serviços.

## Importante para GitHub no iPhone
GitHub não executa ZIP enviado como arquivo. É preciso extrair o pacote e enviar os arquivos e pastas, preservando a estrutura. A interface móvel do GitHub pode limitar o upload de pastas; se necessário use um computador ou GitHub Codespaces para fazer commit do projeto.

## Segurança
Nunca versionar `.env`, token do Discord, chave Pix privada ou senha do banco. Não habilite acesso público ao PostgreSQL. A chave de API não deve ser compartilhada com o frontend.
