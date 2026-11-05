# Store Control — Etapa 8: Equipe e Configurações

Painel React + Vite com todas as etapas anteriores e novas páginas de **Equipe** e **Configurações**.

## Executar

```bash
npm install
npm run dev
```

Abra o endereço informado pelo Vite (geralmente http://localhost:5173).

## O que testar

- Equipe: adicionar um membro por ID Discord (17 a 20 dígitos), mudar cargo e remover.
- Cargos e permissões: criar cargo, editar suas permissões e excluir cargos personalizados.
- Configurações: aparência, mensagens com prévia, canais/cargos, pagamentos e comportamento de pedidos.
- Atualize a página: as novas configurações devem permanecer neste navegador.

## Limitações importantes

- Dados salvos no `localStorage` do navegador, sem PostgreSQL, API, OAuth2 ou sincronização com Discord.
- As permissões são **somente uma prévia visual** e não protegem recursos ou ações reais.
- Não utilize chave Pix ou informações sensíveis reais neste protótipo.
- A edição de nome, avatar e status do bot e a publicação de mensagens dependem de integração posterior.
