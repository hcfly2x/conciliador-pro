# Roadmap - Conciliador Pro

Atualizado em 23/07/2026. Este roadmap segue o código atual e o
`PROJECT_CONTEXT.md`; não reativa itens abandonados.

## Concluído recentemente

- Exportação de auditoria em Excel homologada em produção.
- Ajuste de classificação em lote publicado.
- Correção de deduplicação de faturas sobrepostas publicada.
- Base financeira revisada pelo usuário, incluindo XP 06/2026 e Santander
  10/2025.

## Prioridade 1 - Confiabilidade operacional

1. Validar no ambiente hospedado os perfis admin e colaborador, o registro de
   auditoria, logs e Sentry, usando dados de teste controlados.
2. Definir e testar uma rotina de backup e restauração do PostgreSQL antes de
   qualquer próxima migration.
3. Após cada importação relevante, usar a exportação de auditoria como prova de
   quantidade, totais, origem no cofre e conciliações.

## Prioridade 2 - Medir antes de otimizar

1. Medir tempo e volume das consultas de vínculos, sugestões e tabela de
   lançamentos na base atual.
2. Somente se houver gargalo comprovado, prefiltrar candidatos no SQL ou criar
   índices adicionais, acompanhados de migration e teste.

## Prioridade 3 - Reduzir risco de manutenção

1. Migrar, em etapas pequenas, os 13 handlers remanescentes de importação e
   transações de `backend/core/application.py` para blueprints.
2. Dividir os componentes frontend acima de 400 linhas, preservando a cobertura
   E2E atual.
3. Consolidar a documentação operacional a cada release: contexto, arquitetura,
   deploy e changelog de decisão.

## Posterior - Somente mediante decisão explícita

- Homologar e custear um Background Worker separado no Render. Até então,
  `WORKER_MODE=inline` permanece o modo de produção.
- Avaliar `NUMERIC`, foreign keys ou object storage somente após medição e
  auditoria de dados.
