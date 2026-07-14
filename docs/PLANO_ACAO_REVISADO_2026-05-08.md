# Plano De Acao Revisado - 2026-05-08

Este documento revisa o pacote `plano-de-acao_1.zip` contra o estado atual do projeto.

## Leitura Executiva

O plano externo e bom como direcao, mas parte do diagnostico esta defasado. O projeto atual ja tem recursos que o plano marcava como ausentes:

- Tela `/arquivos`.
- Tela `/base-historica`.
- Tabela `account_file_coverage`.
- Endpoints `/api/v1/coverage`.
- Endpoint `/api/v1/system/reset`.
- `competence_month` no commit e no upload direto.
- Relatorios filtrando `duplicate` e `ignored`.
- `bulk_classify` retornando `cursor.rowcount`.
- Classificacao manual alimentando `classification_history`.

## O Que Foi Mantido Como Prioridade

### Prioridade 1 - Seguranca De Importacao

Objetivo: garantir que o usuario veja quando alguma linha candidata a lancamento nao foi parseada.

Tarefas:

- Expor `rejected_lines` no backend em preview e commit.
- Mostrar `rejected_lines` nas telas de importacao e cofre.
- Evoluir os parsers para preencher `rejected_lines` tambem quando uma linha tabular tiver data, valor e descricao, mas nao virar lancamento.
- Destacar falha de `balance_check` no preview.

### Prioridade 2 - Varredura De Pasta Confiavel

Objetivo: usar a varredura para saber o que existe em cada arquivo antes da carga inicial.

Tarefas:

- Corrigir contagem de duplicados no banco por arquivo escaneado.
- Garantir que parcelas diferentes nao sejam marcadas como duplicadas.
- Exibir duplicados internos, duplicados contra banco, novos e matches historicos por arquivo.

### Prioridade 3 - Encoding E Acabamento

Objetivo: remover textos quebrados e deixar a UI apresentavel.

Tarefas:

- Revisar arquivos do frontend fora de `node_modules`.
- Substituir comentarios com encoding quebrado por ASCII simples ou UTF-8 correto.
- Revisar labels visiveis nas telas principais.

### Prioridade 4 - Identity Match

Objetivo: criar vinculo 1:1 entre lancamento real e linha da base historica quando houver correspondencia forte.

Tarefas:

- Adicionar colunas de rastreabilidade.
- Implementar `find_identity_match`.
- Integrar ao recalculate.
- Exibir acao de vincular ao historico na tabela principal.

### Prioridade 5 - Motor De Probabilidades

Objetivo: melhorar a precisao das sugestoes depois que importacao e seguranca estiverem estaveis.

Tarefas:

- Melhorar similaridade de descricao.
- Ajustar peso de conta, valor e recorrencia.
- Garantir que `suggest_for_desc` use a `classification_history`.

## O Que Nao Sera Feito Agora

- Reescrever o sistema.
- Trocar SQLite por banco externo.
- Remover parsers legados em lote sem uma suite de regressao.
- Criar tabela relacional de tags antes de o CSV em `flags` virar gargalo real.
- Automatizar classificacao sem revisao humana.

## Primeira Acao Iniciada

Iniciar pela Prioridade 1: expor e mostrar `rejected_lines` no fluxo de pre-validacao.
