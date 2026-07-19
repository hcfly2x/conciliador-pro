# Inventario privado de amostras para homologacao

Levantamento realizado em 15/07/2026 sobre arquivos fornecidos localmente pelo
proprietario. Os documentos contem dados financeiros reais e **nao devem ser
copiados para o repositorio**. Este documento registra apenas contagens, formatos
e resultados agregados, sem valores, nomes ou identificadores financeiros.

## Cobertura recebida

| Tipo oficial | Formato | Arquivos | Periodo observado |
|---|---:|---:|---|
| Extrato Santander | PDF | 36 | 03/2023 a 02/2026 |
| Cartao Santander | PDF | 29 | 01/2024 a 05/2026 |
| Extrato Nubank | PDF | 27 | 01/2024 a 04/2026 |
| Cartao Nubank | CSV | 29 | 01/2024 a 05/2026 |
| Extrato XP | CSV | 8 | 09/2025 a 04/2026 |
| Cartao XP | CSV | 10 | 09/2025 a 06/2026 |

Total auditado pelo `backend/audit_import_samples.py`: **139 documentos**.
Um PDF adicional sem nomenclatura bancaria padrao foi mantido fora da matriz.

## Resultado agregado da auditoria atual

| Tipo | OK | Com avisos | Erros |
|---|---:|---:|---:|
| Cartao Nubank | 29 | 0 | 0 |
| Cartao Santander | 29 | 0 | 0 |
| Cartao XP | 7 | 3 | 0 |
| Extrato Nubank | 0 | 27 | 0 |
| Extrato Santander | 0 | 36 | 0 |
| Extrato XP | 0 | 8 | 0 |

Os avisos dos extratos incluem quantidade baixa, movimentacoes internas e os
dois documentos validos sem movimentacao. Eles nao representam necessariamente
erro; devem ser transformados em expectativas por fixture para evitar um limite
generico de 15 movimentos.

### Casos confirmados sem movimentacao

1. `Extrato - 02-26 - XP.csv`: contem apenas o cabecalho e nenhuma linha. O
   proprietario confirmou que nao houve movimentacao no periodo.
2. `Extrato - 01-24 - Nubank.pdf`: possui texto extraivel e o proprietario
   confirmou que nao houve movimentacao no periodo.

Ambos sao reconhecidos como extratos vazios validos somente quando o documento
fornece evidencia forte. A XP exige o CSV apenas com o cabecalho oficial; o
Nubank exige a declaracao explicita de nenhuma movimentacao no PDF. Os originais
permanecem fora dos testes e do Git.

### Caso adicional

Faturas Santander em PDF identificadas como comprovante foram processadas nas
   amostras recentes; o suporte deve ser afirmado por fixture antes de remover
   qualquer protecao especifica desse formato.

## Base historica

Arquivo analisado localmente: `base_historica.xlsx`.

| Aba observada | Linhas nao vazias |
|---|---:|
| ENTRADAS | 145 |
| SAIDAS (titulo com caracteres corrompidos) | 2.785 |
| HELCIO-SMARTEK (titulo com caracteres corrompidos) | 70 |

Total aproximado: **3.000 linhas nao vazias**, incluindo cabecalhos.

O arquivo apresenta caracteres de substituicao em acentos de nomes de abas e
cabecalhos, por exemplo em `SAIDAS`, `DESCRICAO` e `OBSERVACAO`. O importador nao
depende mais da grafia corrompida: a normalizacao aceita a forma correta e as
variantes degradadas observadas na amostra.

## Protocolo para criar fixtures

Concluido em 19/07/2026: as fixtures anonimizadas dos seis tipos oficiais ficam
em `backend/tests/fixtures/imports` e a matriz executavel em
`backend/tests/test_import_regression.py`. Nenhum dado financeiro privado foi
copiado para o repositorio.

- Selecionar ao menos um representante de cada um dos seis tipos oficiais.
- Anonimizar nomes, documentos, contas, referencias e valores identificaveis.
- Preservar estrutura, separador, encoding, ordem de colunas e padroes de data.
- Registrar resultado esperado: quantidade, datas, sinais, competencia, conta,
  parcelas, duplicados e linhas rejeitadas.
- Incluir separadamente os dois casos de borda identificados acima.
- Nunca adicionar os documentos financeiros originais ao Git.

## Proxima ordem de trabalho

1. Criar uma fixture PDF anonimizada do extrato vazio Nubank; o comportamento
   equivalente do CSV XP ja possui teste sintetico.
2. Criar uma fixture anonimizada de cada tipo oficial.
3. Executar a matriz completa e substituir avisos genericos por expectativas por
   banco e tipo de documento.
