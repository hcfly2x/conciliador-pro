# Homologacao de ambientes - 22/07/2026

Validacao somente leitura, sem deploy e sem alterar dados financeiros.

## Ambiente local homologado

- 91 testes Python locais aprovados e 1 teste PostgreSQL condicional, incluindo
  migrations, seguranca, tradutor SQL e worker em processo separado com reinicio
  do processo web.
- TypeScript e build Next.js aprovados.
- 6 jornadas Playwright aprovadas contra `next build` + `next start`: CSP,
  autenticacao admin, importacao/classificacao, conciliacao/desfazer, cofre e
  RBAC/auditoria.
- Auditoria de 8 fixtures: zero erros e cinco avisos esperados.
- No SQLite, eventos auxiliares de progresso produzidos durante a transacao
  financeira sao acumulados e persistidos ao fim, evitando falsos avisos de lock.
  PostgreSQL continua publicando esses eventos em tempo real.
- O job `backend-postgres` do CI sobe PostgreSQL 16 descartavel, reinicia o web
  durante um job e confirma a conclusao pelo worker. Ele sera efetivamente
  homologado na primeira execucao do CI apos o push.

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

## Versoes observadas

- Deploy Vercel/GitHub mais recente: `5b238c8`.
- Commit informado pelo health do Render: `3f17d8a`.

O commit `5b238c8` altera dependencia do frontend; o Render pode estar usando
filtro por diretorio. Mesmo assim, a matriz de release deve registrar
explicitamente os dois commits quando frontend e backend forem implantados em
revisoes diferentes.

## Bloqueios externos

- A rodada local de Sentry, worker e migrations ainda nao foi publicada; nao e
  possivel valida-la no ambiente atual.
- Nao havia sessao autenticada no navegador nem credenciais de homologacao.
  Admin, colaborador, auditoria e operacoes autenticadas permanecem pendentes.
- Nenhuma `DATABASE_URL` de homologacao esta configurada localmente; o teste
  PostgreSQL da rodada nova permanece pendente.
