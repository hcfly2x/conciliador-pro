# Avaliacoes posteriores a estabilizacao

Atualizado em 22/07/2026. Este documento define criterios de decisao; os itens
abaixo nao estao autorizados para implementacao antes do fechamento da
homologacao PostgreSQL, da regressao financeira e do primeiro backup restaurado.

## Valores monetarios em `NUMERIC`

Decisao recomendada: migrar `REAL`/`DOUBLE PRECISION` para `NUMERIC(18, 2)` se
a auditoria encontrar qualquer divergencia de arredondamento ou antes de usar os
dados para fechamento contabil. A migracao precisa:

1. comparar soma, minimo, maximo e quantidade por conta e competencia;
2. bloquear valores com mais de duas casas que nao possuam regra documentada;
3. executar em staging sobre copia do banco e gerar relatorio antes/depois;
4. ter rollback testado e nunca converter silenciosamente na aplicacao.

## Foreign keys

Decisao recomendada: adicionar em ondas, depois de consultar orfaos existentes.
Comecar por tabelas de job e auditoria, avancar para categorias/subcategorias e
deixar transacoes/documentos por ultimo. Cada migration deve declarar a politica
de exclusao (`RESTRICT`, `SET NULL` ou `CASCADE`); nao usar `CASCADE` como padrao.

## Armazenamento dos documentos

Manter o armazenamento atual enquanto o total persistido estiver abaixo de
aproximadamente 200 MB e backup/restore continuar dentro da janela operacional.
Ao atingir o limite, comparar Supabase Storage com `bytea`, preservando hash,
tipo, tamanho, autorizacao e exclusao atomica. A contabilidade nao pode depender
da disponibilidade do arquivo para manter os lancamentos ja importados.

## Calibracao estatistica

O score atual deve continuar sendo apresentado como similaridade/confianca, nao
como probabilidade. Calibrar somente com uma amostra rotulada de confirmacoes e
rejeicoes reais, separada por tipo de documento. Criterios minimos:

- medir precisao e recall dos vinculos automaticos e dos enviados a revisao;
- preservar um conjunto de teste fora da calibracao;
- publicar limiar, tamanho da amostra e matriz de confusao;
- nunca relaxar as regras deterministicas de data e valor do lote sem aprovacao.

## Pluggy / Open Finance

Nao iniciar integracao antes de confirmar uso real de conta PJ, cobertura dos
bancos necessarios, custo e politica de retencao. Fazer primeiro um spike sem
persistencia financeira, avaliando consentimento, renovacao, webhooks, idempotencia
e como os dados seriam reconciliados com os arquivos, que permanecem a fonte de
verdade contabil ate uma decisao explicita em contrario.
