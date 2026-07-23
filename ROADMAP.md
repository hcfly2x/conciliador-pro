# Roadmap — Conciliador Pro

Atualizado em 23/07/2026. Este plano consolida o roadmap revisado com o
`PROJECT_CONTEXT.md` e o código da `main`. Aplicamos Pareto: primeiro a
integridade financeira e a capacidade de operar/restaurar; depois evidência de
desempenho; só então refatorações grandes ou novos módulos.

## Concluído recentemente

- Exportação de auditoria em Excel homologada em produção.
- Classificação em lote, deduplicação de sobreposição de faturas e importação
  XP 06/2026 corrigidas e validadas pelo usuário.
- Candidatos de conciliação passaram a ser completos e paginados, sem o corte
  anterior que escondia pares válidos.
- Base financeira revisada pelo usuário, incluindo XP 06/2026 e Santander
  10/2025.

## P0 — Confiabilidade operacional (maior retorno imediato)

1. **Runbook de produção e jobs — em implementação.** Manter o deploy real
   documentado: Supabase + Render web em `WORKER_MODE=inline` + Vercel; incluir
   health check, diagnóstico de jobs, rollback e validação pós-release.
2. **Backups e restauração comprovada.** Definir backup diário do PostgreSQL e
   executar uma restauração em banco descartável antes da próxima migration ou
   mudança estrutural. Registrar data, checksum e resultado.
3. **Segurança de acesso.** O proprietário deve rotacionar credenciais de banco
   e administrativas quando houver suspeita de exposição, garantir GitHub
   privado e manter segredos somente nos provedores. Esta tarefa requer acesso
   externo e não é feita pelo código.
4. **Homologação hospedada controlada.** Validar admin e colaborador, auditoria,
   logs e Sentry com dados de teste. Após cada importação relevante, usar a
   auditoria Excel como prova de quantidades, totais, origem no cofre e
   conciliações.

## P1 — Medir antes de otimizar

1. Ativar/confirmar Sentry e coletar, por período limitado, tempos p95 das
   consultas de lançamentos, vínculos, sugestões e relatórios, sem enviar
   conteúdo financeiro.
2. Medir volume e plano das consultas lentas na base atual.
3. Apenas com gargalo comprovado, propor índices ou filtros SQL acompanhados de
   migration, teste e medição antes/depois.
4. Migração de região do banco fica **adiada**: é operação de alto risco e não
   deve preceder dados de latência/indisponibilidade que a justifiquem.

## P2 — Reduzir risco de manutenção

1. Migrar em etapas pequenas os 13 handlers de importação e transações ainda em
   `backend/core/application.py` para blueprints, sem alterar contrato ou dados.
2. Definir contratos de resposta das rotas críticas e testes de compatibilidade.
3. Dividir os componentes frontend acima de 400 linhas, preservando cobertura
   E2E: `arquivos/page.tsx`, `ImportPage.tsx` e `useTransactionTable.tsx`.
4. Consolidar a documentação operacional nos documentos vivos: contexto,
   arquitetura, deploy/runbook e changelog de decisão. Arquivos históricos
   permanecem identificados como históricos, sem apagamento sem revisão.

## P3 — Evolução de produto após P0/P1

1. Validar fluxo de colaboração (admin e colaborador) e decidir se uma tela de
   usuários/auditoria é necessária além da API atual.
2. Auditar categorias/subcategorias com acentos e duplicidades antes de qualquer
   migration de normalização; não corrigir nomes por suposição.
3. Avaliar filtros por tipo e seleção de subcategoria em massa com dados de uso;
   classificação em lote já existe e deve ser preservada.
4. Evoluir relatórios mensais por categoria/subcategoria somente se o relatório
   atual não responder à necessidade operacional.
5. Avaliar painel operacional do sistema após haver métricas e runbook estáveis.

## Fora da prioridade atual / requer decisão explícita

- Indicador de "worker parado" não é apropriado na produção atual: os jobs
  operam em `inline`; reavaliar apenas ao homologar um worker separado.
- Homologar e custear Background Worker separado no Render.
- `NUMERIC`, foreign keys, object storage ou nova migração de região do banco.
- Exclusão de rotas/UI legadas e ferramentas de auditoria: primeiro mapear uso
  e dependências; não remover como parte de uma refatoração genérica.

## Critério de avanço

Cada item que altera código deve ter teste proporcional, não modificar
lançamentos existentes sem regra aprovada e ser publicado somente após validação
da `main` e do health de produção.
