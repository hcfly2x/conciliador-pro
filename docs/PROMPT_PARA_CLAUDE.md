Você é um arquiteto/engenheiro sênior fazendo code review e revisão de produto deste projeto local.

Projeto:
- Pasta: C:\Users\hcfly\Downloads\conciliador-pro
- Stack: Backend Flask + SQLite, Frontend Next.js
- Objetivo: conciliador financeiro com importação de extratos/faturas, classificação por categoria/subcategoria, e sugestões por probabilidade.

Sua missão:
1. Fazer uma leitura completa da arquitetura (backend + frontend + docs).
2. Validar se as regras de negócio críticas estão corretas:
   - conta/cartão obrigatório na importação
   - duplicidade interna vs duplicidade com banco
   - cartão: despesa por padrão, receita em estorno/reembolso/cashback
   - probabilidades separadas: categoria, subcategoria, match perfeito
3. Encontrar bugs, regressões e riscos de dados.
4. Propor melhorias de UX, confiabilidade e manutenção.
5. Entregar plano de ação priorizado (P0/P1/P2), com justificativa técnica.

Arquivos de contexto para ler primeiro:
- C:\Users\hcfly\Downloads\conciliador-pro\docs\DATABASE_E_FLUXO.md
- C:\Users\hcfly\Downloads\conciliador-pro\docs\CONTEXTO_IMPORTANTE_PROJETO.md

Formato da resposta que eu quero:
- Seção 1: Diagnóstico executivo (curto)
- Seção 2: Achados críticos (com arquivo e impacto)
- Seção 3: Achados médios/baixos
- Seção 4: Melhorias recomendadas
- Seção 5: Checklist de testes manuais e automatizados
- Seção 6: Patch plan sugerido (ordem de implementação)

Importante:
- Seja objetivo e específico.
- Sempre referencie arquivo/trecho quando apontar problema.
- Se houver hipóteses, marque explicitamente como hipótese.
