# Contextos Importantes do Projeto

## Objetivo funcional
Conciliador financeiro pessoal/empresa com foco em:
- importar extratos e faturas
- manter base local própria de lançamentos
- classificar por categoria/subcategoria/observação
- detectar inconsistências de duplicidade
- oferecer auto-classificação por histórico

## Decisões de produto já consolidadas
1. Fonte de verdade dos lançamentos:
- somente documentos financeiros importados (extrato/fatura)
- `importar base` serve apenas para histórico de classificação

2. Seleção de conta/cartão:
- obrigatória na importação
- sem detecção automática por nome/conteúdo

3. Duplicidade:
- duplicado interno do arquivo: permitido (pode ser legítimo)
- duplicado com banco existente: não inserir novamente

4. Cartão de crédito:
- quase tudo despesa
- entradas são exceções (estorno/reembolso/cashback)

5. Probabilidades na classificação:
- categoria, subcategoria e match perfeito são métricas separadas
- cálculo usa sempre: data + descrição aproximada + valor + conta

## Comportamentos específicos importantes
- Extrato Santander PDF pode ter seção final de comprovantes repetidos; parser trata espelhamento.
- Comprovante/fatura Santander PDF sem detalhe suficiente deve ser recusado para evitar lixo de dados.
- CSV de cartão (quando existe) é preferível por granularidade e consistência.

## Estado atual esperado no app
- edição inline em lançamentos pendentes
- salvar automático ao classificar/editar
- botão auto classificar aparece por limiar de probabilidade
- filtros e ordenação na tabela

## Riscos conhecidos
- PDFs com layout muito diferente podem exigir ajuste de parser por banco/período.
- ambientes Python no Windows podem apontar para interpreters diferentes.

## Estratégia recomendada para evolução
1. consolidar parsers por banco/formato com testes de regressão
2. criar suíte de validação por arquivo (contagem esperada, pares espelhados, duplicidade)
3. adicionar logging estruturado de importação (debug/auditoria)
4. evoluir relatório de qualidade da importação por documento

## Pastas-chave
- backend: `backend/app.py`, `backend/data/`
- frontend: `frontend/components`, `frontend/lib`
- documentação: `docs/`

## Convenção prática de uso
1. importar documento escolhendo conta/cartão corretamente
2. revisar contagens de parsed/inserted/duplicates
3. classificar pendentes
4. usar base histórica para acelerar classificação futura
