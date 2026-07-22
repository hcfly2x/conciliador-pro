# Decisao sobre o code review de performance - 22/07/2026

Este documento registra o que foi acatado, condicionado ou recusado do review
independente `CODE-REVIEW-PERFORMANCE-2026-07-22.md`. O codigo atual foi usado
como fonte principal da verdade.

## Regra de decisao

**Principio de Pareto: buscar 80% do resultado com 20% do esforco.**

Entram primeiro mudancas que removem trabalho claramente redundante, melhoram
a experiencia percebida e nao alteram regras financeiras. Otimizacoes com novo
schema, cache distribuido, backfill ou maior complexidade operacional dependem
de evidencia de que atacam um gargalo relevante.

## Diagnostico aceito

- O lote de vinculos carrega toda a `classification_history` em cada chamada.
- O frontend envia selecoes em blocos de 10; portanto a carga completa se
  repete uma vez por bloco.
- Existe uma consulta redundante por lancamento dentro do lote, embora as
  colunas necessarias ja tenham sido lidas.
- O fallback `find_identity_match` percorre historico linearmente e repete
  parses e comparacoes dentro do loop.
- `DataLoader` recarrega cinco conjuntos de dados em todo `bumpRefresh`.
- Jobs inline podem competir com a navegacao, especialmente durante importacao,
  sugestoes e recalculo.
- Busca com `%texto%`, subconsulta correlacionada e contagens com joins podem
  degradar, mas ainda precisam aparecer nas medicoes antes de receber trabalho.

## Acatar agora: alto impacto e baixo esforco

1. **Medir uma linha de base pequena e util.** Registrar duracao do lote para
   10, 50 e 200 itens e as cardinalidades de transacoes/historico. Consultar
   `pg_stat_statements` e usar `EXPLAIN (ANALYZE, BUFFERS)` nas consultas que
   aparecerem como mais caras.
2. **Remover o N+1 do lote.** Usar `row[9]` e `row[11]`, ja retornados pela
   consulta inicial, em vez de consultar novamente cada `tx_id`.
3. **Reduzir trabalho no fallback sem mudar candidatos.** Analisar a data do
   lancamento uma vez. Calcular primeiro as compatibilidades numericas e so
   executar comparacao textual quando a regra comum ou parcelada ainda puder
   ser satisfeita.
4. **Separar refresh global de refresh operacional.** Classificar, vincular ou
   conciliar deve atualizar o contador e o estado afetado sem recarregar contas,
   categorias, subcategorias e meses.
5. **Preservar atualizacoes locais ja existentes.** Confirmacao individual,
   rejeicao e classificacao individual ja atualizam linhas localmente. O lote
   ainda pode recarregar a pagina quando necessario, principalmente se
   `affected_ids` incluir parcelas fora da pagina.

## Acatar depois da medicao

1. **Pre-filtrar candidatos no SQL.** E a direcao preferida para escala porque
   reduz leitura, transferencia e memoria sem introduzir estado compartilhado.
   O filtro deve ser um superconjunto das regras comum e parcelada para nunca
   eliminar candidato valido.
2. **Indice `classification_history(type, date, amount)`.** Criar apenas se o
   plano da consulta pre-filtrada comprovar utilidade.
3. **Indice parcial de vinculos confirmados.** Avaliar
   `(history_match_id, date DESC) WHERE history_match_confirmed=1` com EXPLAIN.
4. **Contagens do historico sem joins desnecessarios.** Aplicar se `/history`
   aparecer entre as consultas relevantes; sem busca textual, os joins de nomes
   podem ser omitidos das contagens.
5. **Background Worker no Render.** Acatado como isolamento operacional, mas
   depende de aprovacao do custo e de cutover atomico. Seu impacto sera maior
   durante jobs; nao deve ser tratado como explicacao unica para lentidao
   permanente de navegacao.

## Nao acatar como proposto

1. **Nao usar `COUNT(*) + MAX(ctid/rowid)` como versao de cache.** `COUNT(*)`
   ainda pode varrer a tabela, `ctid` nao representa versao de negocio e uma
   substituicao com a mesma quantidade pode escapar da invalidacao.
2. **Nao adotar cache de processo como primeira solucao.** Em Gunicorn, cada
   processo teria aquecimento e memoria proprios. Se o pre-filtro SQL nao for
   suficiente, um cache so sera aceito com uma versao monotona explicita da base
   historica, invalidacao testada e comportamento multiprocesso definido.
3. **Nao criar agora bucket adicional de valores em memoria.** Pode se tornar
   redundante depois do pre-filtro SQL; medir primeiro.
4. **Nao adicionar agora `pg_trgm`/GIN.** So entra se pesquisa textual estiver
   no topo das consultas lentas.
5. **Nao materializar agora `seed_sheet`.** O filtro nao pertence ao caminho
   principal e exigiria migration, backfill e verificacao por um ganho ainda
   nao demonstrado.
6. **Nao introduzir SWR/React Query.** Eventos e o store atual podem resolver a
   repeticao com menor superficie de regressao.
7. **Nao reimplementar atualizacao local indiscriminadamente.** Parte relevante
   ja existe. Ajustes restantes devem ser pontuais e preservar o fallback de
   recarga para parcelas ou linhas fora da pagina.

## Correcao de seguranca no fallback

Nao e seguro simplesmente descartar uma linha quando `amount_normal` for falso:
ela ainda pode ser candidata pela regra de total parcelado. A ordem correta e:

1. calcular valor comum e valor total parcelado;
2. se nenhum dos dois puder corresponder, pular a linha;
3. somente entao calcular similaridade textual e datas aplicaveis;
4. preservar exatamente tolerancias, limiares e revisao de ambiguidades.

## Prioridade resultante

1. Medicao curta e quick wins sem mudanca de resultado.
2. Reducao das recargas globais do frontend.
3. Pre-filtro SQL e indices somente com evidencia.
4. Worker separado mediante aprovacao operacional.
5. Otimizacoes opcionais apenas se continuarem visiveis nas metricas.

A separacao estrutural dos 13 handlers restantes continua desejavel, mas perde
prioridade temporariamente para a lentidao percebida pelo usuario.

## Implementado localmente nesta rodada

- N+1 do lote removido e protegido por teste de regressao.
- Parse de data e rejeicao numerica antecipada aplicados ao fallback, mantendo
  a alternativa de total parcelado.
- Refresh operacional separado dos gatilhos de cadastros e meses.
- Validacao: 95 testes Python, TypeScript, build Next.js e 8 jornadas
  Playwright aprovados.
