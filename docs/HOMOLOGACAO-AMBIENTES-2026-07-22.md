# Homologacao de ambientes - 22/07/2026

Registro cumulativo de validacao. Os testes automatizados e de infraestrutura
nao alteraram dados financeiros; importacao e vinculo em lote foram executados e
confirmados pelo proprietario no uso normal do produto.

## Ambiente local homologado

- 94 testes Python locais aprovados na rodada atual, incluindo migrations,
  seguranca, tradutor SQL, propriedade do pool e worker em processo separado.
- TypeScript e build Next.js aprovados.
- 6 jornadas Playwright aprovadas contra `next build` + `next start`: CSP,
  autenticacao admin, importacao/classificacao, conciliacao/desfazer, cofre e
  RBAC/auditoria.
- Auditoria de 8 fixtures: zero erros e cinco avisos esperados.
- No SQLite, eventos auxiliares de progresso produzidos durante a transacao
  financeira sao acumulados e persistidos ao fim, evitando falsos avisos de lock.
  PostgreSQL continua publicando esses eventos em tempo real.
- O job `backend-postgres` passou repetidamente: sobe PostgreSQL 16 descartavel,
  reinicia o web durante um job e confirma a conclusao pelo worker.

## Producao observada

- Frontend: `https://conciliador-pro-snowy.vercel.app`
- Backend: `https://conciliador-pro.onrender.com`
- Frontend abriu e redirecionou corretamente para `/login`, sem erros de console.
- CSP presente, incluindo `frame-ancestors 'none'` e `connect-src` restrito ao
  backend Render.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` e
  `Referrer-Policy: no-referrer` presentes.
- Preflight CORS da origem Vercel aprovado.
- `/api/v1/auth/me` sem token respondeu 401, conforme esperado.
- `/api/v1/health` respondeu 200 com banco `postgres`.
- O proprietario confirmou importacao de extrato e vinculo selecionado em lote.
- Uma rajada de 40 requisicoes concorrentes terminou sem HTTP 500 depois do
  hotfix de propriedade do pool PostgreSQL.
- Render possui somente o web service; `WORKER_MODE=inline` foi configurado e
  homologado como mitigacao operacional sem custo.

## Versoes observadas

- Deploy Vercel/GitHub: `e73adfd`.
- Commit informado pelo health do Render: `e73adfd5c874`.
- Migration mais recente no codigo: versao 2; confirmacao pelo health ampliado
  esta preparada na rodada local seguinte.

## Bloqueios externos

- Background Worker separado ainda nao existe no Render; a producao usa inline.
- Sentry, matriz completa de admin/colaborador e auditoria permanecem pendentes.
- O painel confirmou que o Supabase Free nao oferece backups do projeto. Um
  backup local consistente e verificavel foi criado em 22/07/2026; a restauracao
  em banco descartavel ainda precisa ser homologada antes da proxima mudanca de
  schema.
- Regressao dos seis documentos privados originais ainda precisa de conferencia
  dirigida sem reinserir arquivos ja importados.
