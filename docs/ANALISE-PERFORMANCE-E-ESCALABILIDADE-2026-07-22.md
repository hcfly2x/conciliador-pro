# Analise de performance e escalabilidade - 22/07/2026

## Objetivo

Registrar a hipotese tecnica atual para a lentidao percebida depois do aumento
do volume de dados e orientar um code review independente. Este documento e um
brainstorm tecnico: nenhuma otimizacao de banco foi aplicada nesta rodada.

O PostgreSQL continua adequado ao porte e ao dominio do produto. A prioridade
nao deve ser trocar de banco ou apagar dados, mas medir e corrigir a forma como
o sistema consulta, cruza e recalcula os registros.

## Hipoteses principais

### 1. Vinculos percorrem a base historica inteira

O endpoint de vinculo em lote consulta toda a tabela `classification_history`
e constroi indices Python em memoria a cada requisicao. Isso faz o custo de
cada lote crescer junto com toda a base historica, mesmo quando apenas poucos
lancamentos foram selecionados.

O fluxo tambem consulta novamente o estado de cada lancamento dentro do loop,
apesar de parte desse estado ja estar presente na consulta inicial. Esse padrao
adiciona uma consulta por item selecionado.

Direcao recomendada:

- selecionar no PostgreSQL apenas candidatos com tipo, data e valor
  compativeis;
- manter campos normalizados e chaves de busca previamente calculadas;
- calcular similaridade textual em Python somente sobre a lista reduzida;
- remover consultas por item que possam ser resolvidas pela leitura em lote;
- medir separadamente a regra comum e a excecao de valor total parcelado.

### 2. Pesquisa textual e consultas correlacionadas

A consulta do historico usa pesquisa por trechos com `%texto%` e uma subconsulta
correlacionada para localizar o lancamento vinculado mais recente. Sem indices
compativeis, ambas tendem a degradar conforme as tabelas crescem.

Direcao recomendada:

- avaliar `pg_trgm` com indice GIN para descricao normalizada;
- indexar os campos usados para vinculo confirmado e ordenacao por data;
- comparar `JOIN LATERAL`, consulta agregada ou tabela auxiliar com a subconsulta
  atual usando `EXPLAIN (ANALYZE, BUFFERS)`;
- manter paginacao no banco, sem carregar todos os registros na aplicacao.

### 3. Contagens e filtros da tela de pendentes

Totais de pendentes, classificados, vinculados e conciliados usam filtros e
subconsultas que podem exigir varreduras frequentes. Os indices devem refletir
as combinacoes realmente usadas pelas telas, e nao apenas colunas isoladas.

Indices candidatos a validacao, nunca a criacao sem medicao:

- `transactions(status, locked)`;
- `transactions(history_match_id, history_match_confirmed)`;
- `transactions(installment_plan_id)`;
- `transactions(account_id, date)`;
- `classification_history(type, date, amount)`;
- indices parciais para estados pendentes ou vinculos confirmados.

A ordem e a seletividade precisam ser confirmadas com planos reais. Indices em
excesso tambem aumentam custo de importacao e atualizacao.

### 4. Requisicoes repetidas no frontend

Durante os testes E2E aparecem leituras repetidas de contas, categorias,
subcategorias, razoes, meses e totais. Parte desses dados muda pouco e pode ser
reutilizada entre telas. Recarregar a pagina ou a tabela inteira depois de cada
alteracao tambem amplifica o custo do backend.

Direcao recomendada:

- identificar requisicoes simultaneas ou duplicadas no navegador;
- aplicar cache e deduplicacao aos cadastros quase estaticos;
- invalidar apenas os totais e registros realmente afetados;
- atualizar localmente o lancamento salvo quando a resposta da API ja contem o
  estado final;
- avaliar um endpoint agregado para o bootstrap da tela somente se a medicao
  mostrar ganho claro.

### 5. Jobs pesados competem com o processo web

A producao atual usa `WORKER_MODE=inline` no unico web service. Importacao,
sugestoes e recalculos podem competir por CPU, memoria e conexoes enquanto o
usuario navega.

Separar o worker passa a ser uma medida de desempenho e isolamento, alem de uma
protecao contra timeout. O fallback inline deve permanecer ate o Background
Worker ser criado e homologado no ambiente hospedado.

## Plano pratico recomendado

### Fase 1 - medir sem mudar dados

1. Habilitar ou consultar `pg_stat_statements` no PostgreSQL hospedado.
2. Registrar latencia por endpoint e quantidade de registros examinados.
3. Capturar planos com `EXPLAIN (ANALYZE, BUFFERS)` das consultas mais lentas em
   uma copia segura ou janela controlada.
4. Separar tempo de banco, processamento Python e rede/frontend.
5. Definir uma linha de base com volume de transacoes e historico.

### Fase 2 - ganhos de baixo risco

1. Remover a consulta por lancamento do lote de vinculos.
2. Adicionar somente indices justificados pelos planos medidos, via migrations
   versionadas e compativeis com PostgreSQL.
3. Reduzir requisicoes duplicadas e recargas completas do frontend.
4. Adicionar testes de desempenho com dados sinteticos, sem copiar os dados de
   producao para o repositorio.

### Fase 3 - reduzir o universo de candidatos

1. Consultar candidatos de vinculo por tipo, data e valor antes da similaridade.
2. Criar estrategia equivalente para o total estimado de parcelamentos com
   tolerancia de ate R$ 1,00.
3. Avaliar colunas normalizadas ou tabela auxiliar de busca somente depois de
   validar a consulta mais simples.
4. Recalcular apenas lancamentos alterados, evitando recalculo global por
   padrao.

### Fase 4 - isolamento operacional

1. Criar e homologar o Background Worker no Render.
2. Medir concorrencia e uso do pool com web e worker separados.
3. Validar reinicio do web durante jobs, lease, idempotencia e observabilidade.

### Fase 5 - decisoes de longo prazo

Arquivamento e particionamento so devem ser considerados se os planos e volumes
reais demonstrarem necessidade. Migracao para NoSQL, sharding ou divisao em
varios bancos nao se justificam no estado atual.

A futura migracao monetaria de `FLOAT` para `NUMERIC` deve ser tratada como
correcao de precisao e integridade financeira, nao como solucao de performance.

## Requisitos de seguranca para qualquer otimizacao

- preservar classificacoes, vinculos, conciliacoes, auditoria e documentos;
- nao alterar schema diretamente em producao;
- usar migrations versionadas, com estrategia de rollback e verificacao;
- testar com PostgreSQL descartavel antes do deploy;
- comparar contagens e somas financeiras antes e depois;
- evitar locks longos durante criacao de indices em tabelas em uso;
- nao remover o fallback inline antes da homologacao do worker separado.

## Perguntas para o code review

1. Quais consultas atuais possuem complexidade linear ou quadratica com o
   crescimento de `transactions` e `classification_history`?
2. Quais indices sao sustentados pelos filtros e ordenacoes reais do codigo?
3. Ha consultas N+1 alem da identificada no vinculo em lote?
4. A consulta de historico pode evitar a subconsulta correlacionada sem mudar o
   resultado funcional?
5. Como reduzir candidatos preservando exatamente as regras de data, valor,
   descricao e parcelamento?
6. Quais endpoints repetidos pelo frontend podem ser cacheados com invalidacao
   segura?
7. O pool e o modo inline podem explicar picos de latencia durante jobs?
8. Qual sequencia de migrations minimiza lock e risco sobre os dados em uso?

## Estado do codigo entregue para revisao

- Producao permanece no commit `c853b14`.
- O ZIP inclui alteracoes locais ainda sem commit e sem deploy.
- A separacao local do backend chegou a 49 de 62 handlers em blueprints.
- Os 95 testes Python passaram, com 1 integracao PostgreSQL local opcional
  ignorada.
- As 8 jornadas Playwright passaram.
- Nenhuma mudanca de schema ou de dados foi feita nesta rodada.

O revisor deve usar `PROJECT_CONTEXT.md` como contexto consolidado e o codigo
atual como fonte principal da verdade. Documentos explicitamente historicos nao
devem substituir as decisoes vigentes.
