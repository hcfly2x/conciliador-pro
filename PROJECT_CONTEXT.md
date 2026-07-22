# PROJECT_CONTEXT.md - Conciliador Pro

Atualizado em 22/07/2026. Este arquivo consolida o contexto de produto. O codigo
continua sendo a fonte principal da verdade; `docs/ROADMAP-FINALIZACAO.md` e o
checklist operacional vigente. Roadmaps anteriores sao apenas historicos.

## Objetivo do produto

Aplicativo web de controle financeiro pessoal que importa extratos e faturas,
preserva os lancamentos exatamente como constam nos documentos, permite
classificacao humana e usa uma base historica como evidencia para acelerar o
trabalho.

Fluxo principal:

1. Importar ou substituir, com confirmacao administrativa, a base historica.
2. Importar extratos e faturas com deteccao, preview e confirmacao.
3. Revisar vinculos diretos com a base historica.
4. Calcular sugestoes em job separado.
5. Classificar manualmente o restante.
6. Conciliar transferencias internas quando aplicavel.

## Estado em 22/07/2026

O produto possui fluxo funcional de autenticacao, importacao com preview,
deduplicacao, base historica, vinculos revisaveis, sugestoes assincronas,
classificacao, parcelas, conciliacao, relatorios, cofre e reset administrativo.

A branch oficial e `main`. O commit `e73adfd` esta em `origin/main`, Vercel e
Render. O Render usa PostgreSQL e, por possuir apenas o web service no plano
atual, executa jobs com `WORKER_MODE=inline`. O Background Worker separado
continua sendo a arquitetura alvo, mas nao esta ativo em producao.

Validacao da versao publicada e da rodada local seguinte:

- 94 testes Python aprovados localmente na rodada atual; o release `e73adfd`
  possuia a cobertura anterior e a rodada local
  seguinte adiciona cobertura do contrato operacional do health.
- A integracao PostgreSQL do CI passou com banco descartavel, web e worker em
  processos separados e reinicio do web durante um job.
- 6 jornadas Playwright aprovadas.
- TypeScript e build de producao Next.js aprovados.
- `npm audit --omit=dev` sem vulnerabilidades conhecidas.
- `pip check` sem dependencias quebradas.

## Arquitetura atual

- Frontend: Next.js 15.5.20, React 19, TypeScript, Tailwind CSS, Zustand e
  Playwright.
- Backend: Flask, Python e Gunicorn.
- Banco: PostgreSQL quando `DATABASE_URL` esta configurada; SQLite local/testes.
- Persistencia: SQL direto com adaptador de compatibilidade SQLite/PostgreSQL.
- Jobs: tabelas persistentes. O worker separado possui lease PostgreSQL
  exclusivo e esta homologado no CI; a producao atual usa o fallback inline no
  web service ate a criacao de um Background Worker no Render.
- Arquivos: documentos originais em Base64 no banco, com fallback local.
- Observabilidade: logs estruturados e Sentry opcional por DSN.
- CI: testes Python, typecheck/build e Playwright.

`backend/app.py` e uma fachada pequena. Dos 62 endpoints de blueprint, 34 ja
possuem handlers nos modulos de dominio, incluindo auth/auditoria, sistema,
relatorios, contas/razoes/categorias, cobertura/cofre e conciliacoes. Os 28
endpoints grandes de importacao, transacoes, vinculos e sugestoes ainda dependem
de `backend/core/application.py`. O bootstrap legado continua idempotente para
compatibilidade; novos schemas passam obrigatoriamente por migrations versionadas.

## Funcionalidades existentes

- Login, sessoes, perfis `admin` e `colaborador`, auditoria e rate limit.
- Importacao de CSV, XLS/XLSX e PDF com preview, validacoes, totais, avisos e
  deduplicacao.
- Competencia de cartao baseada na data de pagamento da fatura, com vencimento
  como fallback; datas dos lancamentos nunca definem a competencia do cartao.
- Confirmacao da importacao em job persistente, com progresso, logs, retomada
  apos refresh e protecao contra confirmacao duplicada.
- Deteccao automatica de conta com correcao manual.
- Parsers Santander, Nubank e XP para conta e cartao.
- Contas, categorias, subcategorias e contas correntes (`ledgers`).
- Base historica unica e substituicao administrativa segura.
- Vinculos historicos individuais e em lote, com fila de revisao manual.
- Sugestoes persistidas de categoria/subcategoria, calculadas manualmente.
- Central de classificacao, classificacao em lote e planos de parcelas.
- Conciliacao manual e reversivel de entrada e saida do mesmo valor.
- Relatorios de resumo, categorias e evolucao mensal.
- Cofre de documentos, cobertura de arquivos e exclusao auditada.
- Release `e73adfd` homologado em producao; o proprietario confirmou importacao
  de extrato e vinculo em lote funcionando com dados reais.

## Regras de negocio vigentes

- Extratos e faturas sao a fonte de verdade dos lancamentos reais.
- A base historica nunca cria nem altera data, valor, descricao ou conta de um
  lancamento real; ela fornece evidencia de categoria e subcategoria.
- Nao existe autoclassificacao. Toda classificacao depende de acao humana.
- Qualquer duplicado ja existente no banco bloqueia o lote inteiro. Repeticoes
  internas do mesmo arquivo sao preservadas como lancamentos legitimos.
- Despesas sao negativas; receitas sao positivas.
- Confirmar vinculo replica categoria/subcategoria, protege o lancamento e nunca
  substitui a conta vinda do documento.
- Rejeitar vinculo impede o mesmo candidato de reaparecer para o lancamento.
- Lancamentos com vinculo pendente nao recebem sugestao/classificacao antes da
  revisao.
- O botao `Vincular selecionados` exige descricao acima de 95%, mesma data e
  valor exato.
- Para parcelas, o total estimado (`parcela x quantidade`) pode diferir ate R$ 1
  do historico, com descricao a partir de 50%. Ambiguidade abre revisao manual.
- Todas as parcelas do documento sao preservadas; plano de parcelas serve apenas
  para relacionamento e propagacao confirmada de classificacao.
- Conciliacao exige entrada e saida com mesmo valor absoluto, e pode ser desfeita.
- Pares conciliados nao entram nos totais dos relatorios.

## Normalizacoes historicas confirmadas

- `Antigo`, `Planilha Passada` e `Primeira Planilha` significam origem sem conta;
  seus registros permanecem com `account_id` nulo.
- `Cartao Sulivan` e alias historico de `CARTAO SANTANDER` apenas na base
  historica.
- Formatos `Parcela 1 de 3`, `1/3` e `01/03` sao equivalentes apenas para
  comparacao. O texto original e preservado.

## Itens abandonados

- Aplicacao desktop Tkinter/PyInstaller como arquitetura principal.
- Importacao automatica por pasta ou importacao direta sem preview.
- Descartar parcelas 2+ ou substituir parcelas pelo total da compra.
- Autoclassificacao por historico/correspondencia exata.
- Vinculo automatico sem acao humana.
- Reinsercao forcada de duplicados existentes no banco.
- Arquitetura FastAPI, SQLAlchemy e Alembic planejada anteriormente.

## Pendencias confirmadas

- Concluir a separacao real dos handlers/regras por dominio.
- Manter migrations versionadas obrigatorias para qualquer novo schema.
- Criar e homologar o Background Worker no Render; web e worker separados ja
  estao cobertos no CI com PostgreSQL e reinicio do web.
- Validar Sentry, Vercel, Render e Supabase em staging/producao.
- Executar regressao manual dos seis formatos oficiais.
- Cobrir por E2E vinculos, cofre, colaborador e auditoria.
- Medir falsos positivos de vinculo e calibracao das sugestoes.
- Definir o caso de uso futuro de `ledgers`.
- Backup local consistente do PostgreSQL de producao criado e validado em
  22/07/2026: 24 tabelas, 17.004 registros, manifesto e SHA-256. O projeto
  Supabase esta no plano Free e nao inclui backups gerenciados; ainda falta
  homologar a restauracao desse pacote em um banco descartavel antes da proxima
  mudanca de schema.

## Avaliacoes depois da estabilizacao

- Migrar valores monetarios para `NUMERIC` e adicionar testes de arredondamento.
- Adicionar chaves estrangeiras depois de auditar dados existentes.
- Migrar documentos para `bytea` ou object storage quando a tabela ultrapassar
  aproximadamente 200 MB.
- Remover suporte a token legado em texto puro depois da janela de 30 dias.
- Avaliar probabilidade estatisticamente calibrada.
- Avaliar Pluggy/Open Finance somente em uma fase futura confirmada.
