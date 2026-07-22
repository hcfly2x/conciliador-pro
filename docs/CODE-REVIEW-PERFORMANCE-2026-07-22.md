# Code review de performance e escalabilidade — 22/07/2026

Revisor: análise independente sobre o pacote local (pós `c853b14`).
Escopo conforme `LEIA-ME-CODE-REVIEW-2026-07-22.md`: gargalos que crescem com o
volume, consultas PostgreSQL, custo do vínculo histórico, repetição de
requisições no frontend, web/worker separados, sequência incremental segura e
riscos de regressão financeira.

Convenções: **H** = tamanho da `classification_history`; **T** = tamanho de
`transactions`; **N** = itens selecionados num lote.

---

## 0. O que está bom (e não deve ser mexido)

- Escape de `%`/`_` com `ESCAPE '\'` aplicado nas buscas.
- Índices de fila de jobs via migration versionada (v2) com checksum.
- Worker separado com `pg_try_advisory_lock`, recuperação de jobs
  interrompidos e homologação no CI com restart do web — arquitetura correta.
- Job de sugestões carrega evidências **uma vez** (`load_suggestion_evidence`)
  e usa fingerprint para pular lançamentos já calculados — padrão certo.
- Lote de vínculos com `operation_id`, `duration_ms` e logs estruturados —
  a instrumentação necessária para a Fase 1 de medição já existe no endpoint.
- Chunking sequencial no frontend com progresso real e parada em timeout.

---

## 1. Gargalo dominante: o lote de vínculos recarrega a base histórica inteira **por bloco**

A hipótese nº 1 da `ANALISE-PERFORMANCE` está confirmada — e é pior do que o
documento descreve, porque dois comportamentos corretos isoladamente se
multiplicam:

1. **Backend** (`prepare_history_links_batch`): a cada chamada, executa
   `SELECT ... FROM classification_history` **sem WHERE**, materializa todas as
   linhas em Python e constrói três índices em memória (`history_index`,
   `installment_amount_index`, `history_cache`).
2. **Frontend** (`historyLinkBatch.ts`): divide a seleção em blocos de
   `CHUNK_SIZE = 10` e chama o endpoint uma vez por bloco.

Resultado: uma seleção de 500 lançamentos gera **50 cargas completas e 150
construções de índice** da base histórica na mesma operação. O custo real é
O(H × N/10), não O(H + N). Com H = 50 mil registros, são 2,5 milhões de linhas
materializadas para vincular 500 itens. É exatamente o perfil de lentidão "que
cresce com o volume" relatado.

Correções, em ordem de segurança:

- **1a. Cache por processo com invalidação por versão (ganho ~50x no lote,
  risco baixo).** Manter os três índices em um cache de módulo, chaveado por um
  "carimbo de versão" da base histórica — por exemplo
  `SELECT COUNT(1), MAX(rowid/ctid ou updated_at) FROM classification_history`
  (uma consulta barata por bloco). Se o carimbo confere, reutiliza; se mudou
  (importação/substituição/exclusão de base), recarrega. Importante: a
  invalidação por carimbo é obrigatória — ver riscos na seção 7.
- **1b. Alternativa sem cache: pré-filtrar candidatos no SQL.** A regra estrita
  compara `(type, date, amount_cents)`; o bloco tem no máximo 10 lançamentos.
  Uma única consulta
  `WHERE type IN (...) AND date IN (datas do bloco) AND ABS(amount) BETWEEN min-1 AND max+1`
  reduz o universo de H para dezenas de linhas. Atenção ao índice: o existente
  `idx_hist_type_account_date_amount` tem `account_id` antes de `date` e **não
  serve** para consultas sem filtro de conta — seria necessário
  `classification_history(type, date, amount)`, validado com
  `EXPLAIN (ANALYZE, BUFFERS)`.
- Recomendação: fazer **1a primeiro** (não muda nenhuma consulta de decisão,
  só evita recarga) e deixar 1b para a fase de redução de universo, junto com o
  caso parcelado.

## 2. Consulta redundante por item dentro do loop do lote

Confirmando a segunda parte da hipótese nº 1: para cada `tx_id`, o loop executa

```sql
SELECT history_match_confirmed, locked FROM transactions WHERE id=?
```

sendo que a consulta inicial do bloco **já retornou essas duas colunas**
(`row[9]` e `row[11]`), na mesma transação e conexão — não há escrita
concorrente possível entre as duas leituras que justifique a releitura. São até
500 consultas eliminadas por operação trocando `current_state` por
`(row[9], row[11])`. Correção de uma linha, zero risco.

## 3. Fallback `find_identity_match`: O(H) por lançamento, com trabalho repetido por linha

Quando a regra estrita não encontra candidato, o fallback percorre a lista
completa do `history_cache` do tipo. Três custos evitáveis dentro do loop
por linha do histórico:

- `dt.date.fromisoformat(tx_date)` reanalisa a **mesma** data do lançamento a
  cada linha do histórico (H parses idênticos por lançamento). Içar para fora
  do loop.
- `descriptions_have_common_parts(tx_desc, ...)` roda para linhas que já
  falhariam pelo valor. Testar `amount_normal` (comparação numérica barata)
  **antes** da comparação textual e pular cedo.
- A lista é linear; um índice em memória por faixa de centavos (bucket
  `int(amount)`) reduziria o candidato médio de H para poucas dezenas. Só vale
  se 1a/1b não tornarem isso irrelevante — medir primeiro.

## 4. Consultas do `/api/v1/history`

- **Subconsulta correlacionada do vínculo mais recente**
  (`LEFT JOIN transactions t ON t.id = (SELECT ... ORDER BY date DESC LIMIT 1)`):
  executa por linha, mas só nas ~50 linhas da página — o custo por linha é o
  problema, não a cardinalidade. Hoje o índice `idx_tx_history_match_status`
  cobre `(history_match_id, status)` mas **não** `history_match_confirmed` nem
  a ordenação por data. Índice parcial recomendado (após EXPLAIN):

  ```sql
  CREATE INDEX idx_tx_history_confirmed_date
  ON transactions(history_match_id, date DESC)
  WHERE history_match_confirmed = 1;
  ```

  O mesmo índice serve o filtro `linked=true/false` (EXISTS/NOT EXISTS), o
  `total_linked` e a ordenação `sort_by=linked`.
- **`COUNT` duplo com joins**: `total` e `total_linked` repetem os três LEFT
  JOINs de nomes; os joins só são necessários quando há `search`. Montar o
  FROM condicionalmente (sem busca, contar direto em `classification_history`)
  corta dois joins das contagens mais frequentes.
- **Busca `%texto%`**: LIKE com curinga à esquerda não usa índice btree. A
  direção do documento de análise está certa: `pg_trgm` + GIN em
  `description_norm` (e avaliar em `description`). Migration só-Postgres,
  guardada por `IS_POSTGRES`.
- **`source_file_id LIKE '%:sheet:x'`**: curinga à esquerda = varredura
  completa sempre que o filtro de planilha é usado. Como o valor é derivável,
  materializar uma coluna `seed_sheet` no import da base (backfill via
  migration) e indexar, eliminando também o `CASE WHEN ... LIKE` do SELECT.

## 5. Repetição de requisições no frontend

Confirmada a hipótese nº 4, com um mecanismo específico:

- **`bumpRefresh` recarrega os cinco cadastros.** `DataLoader` depende de
  `refreshKey` e refaz `accounts + categories + subcategories + months +
  pendingCount` em **toda** chamada de `bumpRefresh` — que os componentes
  disparam após mutações que não alteram cadastro nenhum (classificar,
  vincular, conciliar). Além disso, `refreshKey` também está nas dependências
  do `load(1)` do `useTransactionTable`, então um `bumpRefresh` disparado por
  outra tela pode recarregar a tabela inteira em paralelo.
  Correção: separar o que muda de fato — um `refreshPendingBadge()` leve (já
  existe) para o contador, e recarga de cadastros apenas por evento explícito
  (o padrão `window.dispatchEvent(new Event('ledgers:changed'))` já usado para
  razões é o modelo certo; estender para contas/categorias).
- **Recarga total após mutação pontual.** Após classificar/vincular, o fluxo é
  `load(page)` — repaginação completa com agregados de summary. O retorno da
  API já contém o estado final do lançamento e, no lote, `affected_ids`.
  Correção incremental segura: atualizar localmente as linhas retornadas e
  recarregar **apenas** os agregados (uma consulta leve), reservando
  `load(page)` para quando `affected_ids` incluir linhas fora da página (caso
  de irmãos de parcelamento).
- **`ClassificationCenter`** chama `bumpRefresh() + loadSummary() + loadQueue(1)`
  ao concluir job — com a correção do primeiro item, o custo cai sozinho.

Não recomendo adotar biblioteca de cache (SWR/React Query) nesta fase: o
padrão de eventos + store atual resolve com menos risco de regressão nos E2E.

## 6. Web e worker separados

A implementação está pronta e correta: lease por advisory lock em conexão
direta (fora do pool, como deve ser), `recover_interrupted_process_jobs`,
teste de CI com restart do web durante job. Avaliação:

- **Ativar o Background Worker no Render é a medida de maior impacto na
  percepção de lentidão**, porque hoje (`WORKER_MODE=inline`) sugestões e
  recálculos disputam CPU e as ~10 conexões do pool com a navegação do
  usuário. Não é otimização de consulta; é isolamento.
- Checklist de cutover (ver também seção 7): criar o worker no Render com
  `worker.py`; **na mesma janela**, alterar o web para não executar jobs
  (garantir que o modo inline fique desligado quando o worker existir);
  validar pelo health que o executor reportado mudou; manter o inline como
  fallback documentado, nunca simultâneo.
- Custo: um serviço a mais no plano do Render. Se o custo travar a decisão, o
  meio-termo é reduzir a pressão do inline (batch menor de sugestões e pausa
  entre lotes), mas isso é paliativo — o alvo continua sendo o worker.

## 7. Riscos de regressão financeira e operacional (por correção proposta)

| Correção | Risco | Salvaguarda obrigatória |
|---|---|---|
| 1a. Cache da base histórica | Vincular contra histórico **desatualizado** após substituição/edição da base — regressão financeira direta | Invalidação por carimbo de versão consultado a cada bloco; teste automatizado: importar base → vincular → substituir base → vincular de novo e provar que o segundo lote usa a base nova |
| 1b/3. Pré-filtro SQL de candidatos | Filtro mais estreito que a regra Python exclui candidato válido (falso negativo silencioso) | O filtro SQL deve ser **superconjunto** da regra: data exata para a regra comum, `BETWEEN` com folga ≥ R$ 1,00 para o total parcelado; rodar a avaliação leave-one-out existente antes/depois e comparar |
| 2. Remover consulta por item | Nenhum (mesma transação, mesmos dados) | Testes de workflow existentes |
| 4. Índices novos | Nenhum em resultado; risco operacional de lock na criação em tabela grande | Em Postgres, `CREATE INDEX CONCURRENTLY` — atenção: **não roda dentro de transação**, e o runner de migrations comita no fechamento da conexão; índices CONCURRENTLY precisam de caminho próprio (autocommit) ou janela controlada |
| 4. Coluna `seed_sheet` materializada | Backfill divergente do `CASE` atual | Migration com verificação: contagem por sheet antes/depois idêntica |
| 5. Atualização local no frontend | Tela divergente do banco quando o lote afeta linhas fora da página (irmãos de parcela) | Usar `affected_ids` da resposta como gatilho: se houver id fora da página atual, cair para `load(page)`; jornadas Playwright de vínculo em lote já cobrem o fluxo |
| 6. Cutover do worker | Processamento duplo (inline + worker) desperdiça e pode duplicar efeitos de jobs não idempotentes | Config atômica na mesma janela; o lease protege worker↔worker, **não** web-inline↔worker — a exclusão é por configuração; validar no health |

Risco transversal: nenhuma das correções altera dados existentes. As únicas
escritas novas são índices e a coluna derivada `seed_sheet` — ambas aditivas e
reversíveis.

## 8. Sequência incremental recomendada

Compatível com o plano de fases da `ANALISE-PERFORMANCE`, com as entregas
concretas deste review encaixadas:

**Etapa 0 — Medição (sem mudança de dados)**
1. `pg_stat_statements` no Postgres hospedado; capturar top consultas por
   tempo total.
2. `EXPLAIN (ANALYZE, BUFFERS)` de: consulta do `/history` com busca; contagens
   do `/transactions`; carga completa da `classification_history`.
3. Linha de base: `duration_ms` do lote (já retornado) com seleções de 10, 50 e
   200 em staging.

**Etapa 1 — Ganhos sem mudança de comportamento (1 dia)**
4. Remover a consulta por item do loop do lote (seção 2).
5. Içar o parse de data e reordenar o teste de valor no fallback (seção 3).
6. Recarga condicional dos joins nas contagens do `/history` (seção 4).

**Etapa 2 — Cache da base histórica com invalidação por versão (1–2 dias)**
7. Implementar 1a com carimbo de versão + teste de invalidação obrigatório.
8. Repetir a medição da Etapa 0.3 — expectativa: custo do lote passa a ~O(H)
   uma única vez por operação, em vez de por bloco.

**Etapa 3 — Índices via EXPLAIN (1 dia + janela)**
9. Índice parcial `history_match_confirmed=1` (seção 4).
10. Validar/It criar `classification_history(type, date, amount)` se a Etapa 4
    for adiante.
11. Caminho de execução para `CONCURRENTLY` fora do runner transacional.

**Etapa 4 — Redução do universo de candidatos (2–3 dias)**
12. Pré-filtro SQL superconjunto (1b) para regra comum e parcelada; leave-one-out
    antes/depois como critério de aceite.

**Etapa 5 — Frontend (1–2 dias)**
13. Separar `bumpRefresh` de recarga de cadastros; eventos explícitos por
    domínio (seção 5).
14. Atualização local guiada por `affected_ids` com fallback para `load(page)`.

**Etapa 6 — Worker em produção (meia diária + validação)**
15. Background Worker no Render com cutover atômico e verificação via health.

**Etapa 7 — Busca (opcional, guiada por medição)**
16. `pg_trgm` + GIN se a busca aparecer no topo do `pg_stat_statements`.
17. Coluna `seed_sheet` materializada se o filtro de planilha for de uso
    frequente.

Cada etapa é independente, publicável isoladamente e reversível; nenhuma exige
migração de dados de produção além de índices e da coluna derivada opcional.
