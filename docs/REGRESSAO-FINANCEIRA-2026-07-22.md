# Regressao financeira - 22/07/2026

Escopo: fixtures anonimizadas dos seis formatos oficiais. A execucao nao gravou
transacoes no banco principal e nao copiou documentos financeiros privados.

## Resultado dos seis formatos

| Formato | Conta detectada | Itens | Soma assinada | Competencia | Resultado |
|---|---|---:|---:|---|---|
| Extrato Santander PDF | CONTA SANTANDER | 3 | R$ 364,50 | 2026/03 | aprovado |
| Extrato XP CSV | CONTA XP | 3 | R$ 849,00 | 2026/03 | aprovado |
| Extrato Nubank PDF | CONTA NUBANK | 2 | R$ 150,00 | 2026/03 | aprovado |
| Cartao Santander PDF | CARTAO SANTANDER | 12 | -R$ 780,00 | 2026/04 | aprovado |
| Cartao XP CSV | CARTAO XP | 3 | -R$ 180,90 | sem metadado na fixture | aprovado |
| Cartao Nubank CSV | CARTAO NUBANK | 3 | -R$ 135,57 | sem metadado na fixture | aprovado |

As fixtures de cartao XP e Nubank nao possuem data de pagamento/vencimento nem
competencia no nome anonimizado; por isso o detector retorna competencia
desconhecida, sem usar incorretamente as datas dos lancamentos. A fixture
Santander comprova a estrategia `card_payment_date`.

## Verificacoes adicionais

- Sinais de receitas, despesas, estornos e cashback preservados.
- Parcela 2/5 (XP) e parcela 3/10 (Nubank) preservadas com valor do documento.
- Repeticao interna no extrato XP preservada: 3 linhas, 2 assinaturas unicas.
- Uma linha candidata rejeitada no extrato XP permaneceu visivel para revisao.
- Extratos vazios confirmados de XP e Nubank aceitos sem criar lancamentos.
- PDFs corrompido, inesperado e protegido falharam de forma fechada.
- Variacoes CSV Latin-1 e XLSX monetario aprovadas.
- Reimportacao do mesmo arquivo e colisao com banco foram bloqueadas.
- A importacao nao atribui categoria/subcategoria automaticamente.

## Evidencias executadas

- `python -m unittest tests.test_import_regression`: 10 testes aprovados.
- `python audit_import_samples.py tests/fixtures/imports --json`: 8 arquivos
  auditados, zero erros; cinco avisos esperados por baixa quantidade, vazio
  confirmado ou linha rejeitada.

## Limite desta rodada

Os 139 documentos financeiros privados inventariados em 15/07/2026 nao estavam
todos disponiveis na pasta oficial do repositorio durante esta rodada. A matriz
anonimizada e repetivel foi validada; uma conferencia manual dos originais em
staging continua necessaria antes da publicacao final.
