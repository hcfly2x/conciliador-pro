# Roadmap vigente de finalizacao - Conciliador Pro

Atualizado em 22/07/2026. Este e o checklist operacional vigente. O codigo e a
fonte principal da verdade e `PROJECT_CONTEXT.md` consolida as regras do produto.
Os demais roadmaps sao historicos ou entradas de code review.

Legenda:

- `[x]` concluido e validado localmente.
- `[~]` implementado parcialmente ou aguardando validacao externa.
- `[ ]` pendente.
- `[>]` condicionado ou deliberadamente adiado.

Nenhum commit ou push pode ser feito sem autorizacao explicita do proprietario.

## Marco atual

- `origin/main`, Vercel e Render: commit `d4699b2`.
- Producao usa PostgreSQL e `WORKER_MODE=inline` no unico web service do Render.
- Validacao: 94 testes Python locais na rodada atual, PostgreSQL descartavel no CI,
  TypeScript, build e 8 jornadas Playwright aprovados.
- O proprietario confirmou em producao importacao de extrato e vinculo em lote.
- O health publicado confirma PostgreSQL, schema 2 e executor inline.

## 1. Produto e integridade financeira

- [x] Preservar os lancamentos dos documentos como fonte de verdade.
- [x] Bloquear o lote quando houver duplicado ja persistido no banco.
- [x] Preservar repeticoes internas legitimas do documento.
- [x] Impedir autoclassificacao e exigir acao humana.
- [x] Salvar categoria, subcategoria e observacao como uma operacao explicita.
- [x] Validar categoria, tipo e subcategoria no backend.
- [x] Preservar todas as parcelas e seus valores originais.
- [x] Separar exclusao de documento e exclusao de lancamentos.
- [x] Excluir pares conciliados de todos os relatorios e permitir desfazer.
- [ ] Configurar por tipo de documento quando divergencia de saldo ou linhas
  rejeitadas devem bloquear a importacao.

## 2. Importacao e regressao dos parsers

- [x] Cobrir os seis formatos oficiais com fixtures anonimizadas.
- [x] Validar quantidade, datas, valores, sinais, competencia e conta detectada.
- [x] Usar pagamento/vencimento da fatura para competencia de cartao.
- [x] Cobrir documentos vazios, corrompidos, protegidos e layout inesperado.
- [x] Cobrir CSV/XLSX com variacoes de encoding e formato monetario.
- [x] Cobrir arquivo repetido, duplicado no banco e repeticao interna.
- [x] Limitar tamanho e extensao antes da leitura completa.
- [~] Executar regressao dos seis formatos oficiais: fixtures anonimizadas
  aprovadas; originais privados ainda precisam de conferencia em staging.
- [x] Registrar totais esperados e observados em
  `docs/REGRESSAO-FINANCEIRA-2026-07-22.md`.

## 3. Vinculos historicos e sugestoes

- [x] Exibir comparacao lado a lado e justificativas de data, valor e descricao.
- [x] Persistir confirmacao, rejeicao, desvinculo e auditoria.
- [x] Preservar a conta do documento ao confirmar o vinculo.
- [x] Confirmar lotes sem recarregar a pagina a cada item, exigindo descricao
  com similaridade minima de 75%, mesma data e valor exato.
- [x] Abrir candidatos recusados/ambiguos em revisao manual.
- [x] Tratar total parcelado com tolerancia de R$ 1 e similaridade minima de 50%.
- [x] Processar selecoes grandes em blocos sequenciais de 10, com progresso real
  e totais acumulados; uma selecao de 50 resulta em cinco blocos.
- [x] Usar historico e transacoes classificadas como evidencias de sugestao.
- [x] Persistir Top 3, justificativas e estado do job.
- [x] Avaliacao retrospectiva leave-one-out disponivel.
- [~] Normalizacao de estabelecimento e metadados em modo sombra; falta medir e
  aprovar ativacao no ranking.
- [ ] Medir falsos positivos do vinculo com amostra real.
- [ ] Separar similaridade, confianca e probabilidade calibrada.
- [x] Cobrir confirmar/rejeitar/desvincular/recalcular em Playwright.

## 4. Seguranca e confiabilidade

- [x] Proxy confiavel para rate limit e teste contra `X-Forwarded-For` forjado.
- [x] RBAC declarativo, escrita negada por padrao e matriz admin/colaborador.
- [x] Escape literal de `%` e `_` em buscas `LIKE`.
- [x] CSP e cabecalhos de seguranca no frontend.
- [x] Rate limit e bloqueio temporario do login.
- [x] Cache LRU, renovacao controlada e limpeza de sessoes expiradas.
- [x] Visibilidade e limite do fallback de conexoes do pool.
- [x] Auditoria dos `except Exception` silenciosos.
- [x] Dependencias sem vulnerabilidades conhecidas no audit local.
- [ ] Testar expiracao, logout, desativacao e troca de perfil com mais de um worker.
- [>] Remover predicado de token legado depois de 30 dias de convivencia.

## 5. Arquitetura do backend

- [x] Reforcar testes do tradutor SQL e usar schema real nos workflows.
- [~] `app.py` reduzido e 42 de 62 handlers movidos para blueprints: auth,
  sistema, relatorios, contas/razoes/categorias, cobertura/cofre, conciliacoes e
  sugestoes.
- [ ] Mover os 20 handlers grandes restantes: importacao, transacoes e vinculos
  ainda permanecem em `core/application.py`.
- [x] Criar worker persistente para importacoes, seed, sugestoes e recalculo.
- [x] Proteger deploys sobrepostos com lease PostgreSQL exclusivo; processo web
  nao recupera nem altera jobs em execucao.
- [x] Validar worker e web separados no CI com PostgreSQL 16 descartavel.
- [x] Validar persistencia do job ao reiniciar o processo web em testes
  multiprocesso SQLite e PostgreSQL.
- [ ] Criar e homologar o Background Worker no Render. Producao permanece em
  `WORKER_MODE=inline` ate haver aprovacao do custo/servico separado.
- [x] Introduzir migrations versionadas, checksum e tabela de versao do schema.
- [x] Aplicar migrations pendentes no boot de forma idempotente.

## 6. Frontend

- [x] Extrair controles, grid e modal de historico da tabela de transacoes.
- [x] Reduzir todos os componentes da tabela para menos de 400 linhas;
  `useTransactionTable.tsx` possui 382 linhas.
- [x] Remover configuracao Tailwind duplicada.
- [x] Normalizar BOM/LF e adicionar `.gitattributes`.
- [x] Manter progresso visual de operacoes longas, com barra, contadores e logs
  tecnicos recolhiveis no horario local do navegador.
- [x] Cobrir cofre, vinculos, perfil colaborador e auditoria em E2E: CSP,
  autenticacao admin, importacao/classificacao, conciliacao/desfazer, exclusao
  segura no cofre, RBAC/auditoria, vinculo em lote e ciclo completo de revisao
  de vinculos aprovados.
- [ ] Revisar responsividade e textos visiveis.

## 7. Observabilidade e operacao

- [x] Logging de request com metodo, path, status, duracao e usuario, sem payload.
- [x] Sentry opcional no backend e frontend, desligado sem DSN.
- [ ] Confirmar erro controlado no Sentry de staging.
- [ ] Confirmar formato JSON e correlacao de logs no ambiente hospedado.
- [x] Confirmar commits atuais: Vercel e Render em `d4699b2`.
- [~] Fazer smoke test em Vercel, Render e Supabase: frontend, health PostgreSQL,
  CSP, CORS, 401, importacao real e vinculo em lote aprovados; matriz completa
  de perfis e auditoria ainda aguarda homologacao dirigida.
- [ ] Validar admin, colaborador e auditoria no ambiente hospedado.

## 8. Dados persistentes e schema

- [~] Backup local verificavel criado antes da release de 22/07/2026: exportacao
  consistente e somente leitura das 24 tabelas publicas, com 17.004 registros,
  metadados de schema, checksums internos e SHA-256 externo. O Supabase Free nao
  oferece backup gerenciado; ainda falta automatizar a rotina e testar a
  restauracao em PostgreSQL descartavel.
- [x] Registrar commit e versao do schema em cada release persistente; o health
  de `d4699b2` confirmou publicamente schema 2.
- [ ] Restaurar um backup em ambiente de teste.
- [>] Avaliar `NUMERIC` depois da estabilizacao e testar arredondamentos.
- [>] Adicionar foreign keys somente depois de auditar dados existentes.
- [>] Monitorar `stored_documents`; migrar Base64 ao superar aproximadamente 200 MB.

## 9. Documentacao e limpeza

- [x] Atualizar `PROJECT_CONTEXT.md` e este roadmap para o estado de 22/07/2026.
- [x] Marcar roadmaps antigos como historicos/supersedidos.
- [x] Atualizar contexto, arquitetura, API, banco, deploy e README para a rodada
  atual; revisar novamente ao concluir os dominios grandes.
- [ ] Remover codigo legado somente depois de provar que nao possui consumidor.
- [x] Registrar matriz final de variaveis de ambiente.

## 10. Futuro deliberadamente adiado

- [>] Calibracao estatistica do score.
- [>] Migracao monetaria para `NUMERIC`.
- [>] Foreign keys extensivas.
- [>] Object storage/`bytea` para documentos.
- [>] Pluggy/Open Finance; nao iniciar antes da estabilizacao e da confirmacao do
  uso de conta PJ.
- [x] Registrar criterios de decisao para esses itens em
  `docs/AVALIACOES-POS-ESTABILIZACAO.md`.

## Criterio de encerramento

A versao so pode ser chamada de final quando migrations estiverem versionadas,
worker/PostgreSQL e regressao financeira forem homologados, staging/producao
estiverem validados e o commit/schema implantados estiverem registrados.
