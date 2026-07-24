# Homologacao de ambientes - atualizada em 23/07/2026

> Atualização em 24/07/2026: a confirmação mais recente de produção é o health
> do commit `86150c5fc422`, PostgreSQL, schema 3 e `WORKER_MODE=inline`. As
> versões listadas abaixo permanecem como evidência histórica da rodada anterior.

Registro cumulativo de validacao. Os testes automatizados e de infraestrutura
nao alteraram dados financeiros; importacao e vinculo em lote foram executados e
confirmados pelo proprietario no uso normal do produto.

## Ambiente local homologado

- 103 testes Python locais aprovados na rodada atual, incluindo migrations,
  seguranca, tradutor SQL, propriedade do pool e worker em processo separado.
- TypeScript e build Next.js aprovados.
- 9 jornadas Playwright aprovadas contra `next build` + `next start`: CSP,
  autenticacao admin, importacao/classificacao, conciliacao/desfazer, cofre,
  RBAC/auditoria, download real da planilha, vinculo em lote e ciclo completo de
  revisao de vinculos.
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
- O proprietario confirmou o download da planilha administrativa de auditoria
  depois da correcao de streaming e da interface do cursor PostgreSQL.
- Uma rajada de 40 requisicoes concorrentes terminou sem HTTP 500 depois do
  hotfix de propriedade do pool PostgreSQL.
- Render possui somente o web service; `WORKER_MODE=inline` foi configurado e
  homologado como mitigacao operacional sem custo.

## Versoes observadas

- Ultima correcao funcional homologada na Vercel/GitHub: `fabafb6`.
- Commit informado pelo health do Render nessa homologacao: `fabafb6e47cc`.
- Migration informada pelo health publicado: versao 2; executor de jobs:
  `WORKER_MODE=inline` no processo web.

## Bloqueios externos

- Background Worker separado ainda nao existe no Render; a producao usa inline.
- Sentry, matriz completa de admin/colaborador e auditoria permanecem pendentes.
- O painel confirmou que o Supabase Free nao oferece backups do projeto. Um
  backup local consistente e verificavel foi criado em 22/07/2026; a restauracao
  em banco descartavel ainda precisa ser homologada antes da proxima mudanca de
  schema.
- Regressao dos seis documentos privados originais ainda precisa de conferencia
  dirigida sem reinserir arquivos ja importados.
