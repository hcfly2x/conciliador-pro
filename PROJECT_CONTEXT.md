# PROJECT_CONTEXT.md — Conciliador Pro

Atualizado em 23/07/2026, após revisão de código e validação operacional.

O código atual é a fonte principal da verdade. Documentos marcados como
históricos não definem requisitos. Ideias antigas só voltam ao projeto mediante
confirmação explícita.

## Objetivo do produto

Aplicação web de controle financeiro para o proprietário e um colaborador.
Importa extratos e faturas, preserva os lançamentos conforme os documentos,
permite classificação humana, vínculos com uma base histórica, organização de
parcelas, conciliação de transferências internas, auditoria e relatórios.

A base histórica acelera a classificação, mas não substitui nem cria
lançamentos financeiros reais.

## Estado atual

- Branch oficial: `main`.
- A `main`, a Vercel e o Render acompanham o mesmo fluxo de release. O health
  do backend é a fonte operacional para confirmar o commit ativo.
- Última confirmação de health: commit `a71e446`, PostgreSQL, schema 3 e
  `WORKER_MODE=inline`.
- Banco de produção: PostgreSQL/Supabase, schema 3.
- Backend: Render com `WORKER_MODE=inline`.
- Frontend: Vercel.
- CI atual aprovada: testes Python, PostgreSQL 16, TypeScript, build e 9 E2E.
- O código contém 111 métodos de teste Python.
- Existem 64 rotas: 51 implementadas nos blueprints e 13 ainda no núcleo.
- O repositório está em uso com dados reais; mudanças devem preservar
  classificações, vínculos, conciliações, auditoria e documentos.

## Arquitetura e stack

- Frontend: Next.js 15.5.21, React 19, TypeScript, Tailwind CSS 4 e Zustand.
- Backend: Flask, Python e Gunicorn.
- Persistência: SQL direto, sem ORM.
- Banco: PostgreSQL em produção; SQLite em desenvolvimento/testes.
- Compatibilidade de banco: adaptador próprio em `backend/db.py`.
- Migrations: runner versionado com nome/checksum; schema atual na versão 3.
- Jobs persistidos: importação, base histórica, sugestões e recálculo.
- Worker separado está implementado/testado, mas não implantado no Render.
- Documentos: Base64 em `stored_documents`, com cópia local secundária.
- Autenticação: Bearer token, digest no banco, token em `sessionStorage`,
  PBKDF2-SHA256 e perfis `admin`/`colaborador`.
- Observabilidade: logs de requests e jobs; Sentry opcional.
- Infraestrutura: Vercel + Render + Supabase.
- Lema: aplicar Pareto — buscar 80% do resultado com 20% do esforço, priorizando
  integridade financeira, impacto percebido e soluções simples/reversíveis.

## Funcionalidades existentes

- Login, logout, usuários via API, RBAC, auditoria e rate limit.
- Importação de CSV, XLS, XLSX e PDF com detecção, preview e confirmação.
- Importação sequencial de múltiplos arquivos selecionados, reutilizando a
  mesma prévia, qualidade, deduplicação e confirmação do fluxo individual.
- Parsers Santander, Nubank e XP para conta e cartão.
- Detecção/correção de conta e competência.
- Jobs com progresso, logs e retomada visual após refresh.
- Deduplicação contra o banco e preservação de repetições internas.
- Cofre de documentos, download, cobertura mensal e exclusão auditada.
- Contas, categorias, subcategorias e `ledgers`.
- Base histórica substituível mediante confirmação.
- Sugestões Top 3 e avaliação leave-one-out.
- Vínculos históricos individuais e em lote com revisão manual.
- Classificação individual/em lote e proteção pós-classificação.
- A classificação em lote conserva visíveis os itens protegidos ou aguardando
  revisão de vínculo e informa separadamente o que não foi aplicado.
- Planos de parcelas e propagação confirmada de categoria/subcategoria.
- Conciliação reversível de entradas e saídas.
- Lista completa e paginada de candidatos à conciliação, ordenada por
  proximidade de data.
- Relatórios por competência e categoria.
- Exportação administrativa de auditoria financeira em Excel.
- Exportação de auditoria homologada em produção com geração XLSX em
  streaming, sanitização de valores e compatibilidade do cursor PostgreSQL.
- Snapshot técnico de auditoria e reset administrativo protegido.
- Importação por pasta e importação direta permanecem desativadas com HTTP 410.
- A revisão de sobreposição de fatura XP 06/2026 preserva as ocorrências
  existentes e permite inserir somente linhas novas após preview confirmado.

## Regras de negócio vigentes

- Lançamentos reais só vêm de extratos e faturas importados.
- Extratos/faturas são a fonte de verdade para data, valor, descrição e conta.
- A base histórica só fornece evidência de categoria/subcategoria.
- Não existe autoclassificação sem ação humana.
- Despesas são negativas e receitas são positivas.
- Em cartão, compras são despesas; créditos, estornos, cashback, reembolsos e
  devoluções podem ser receitas.
- Competência de cartão usa data de pagamento; vencimento é fallback; depois,
  nome do arquivo. Datas dos lançamentos nunca definem competência de cartão.
- Preview é obrigatório.
- Repetições internas do arquivo são preservadas.
- Em faturas de cartão, a deduplicação é limitada à competência da própria
  fatura; ocorrências iguais em competências diferentes podem ser eventos reais.
- Na sobreposição da mesma fatura, a parcela registrada no texto é comparada
  pelos campos estruturados de parcela, evitando reinserção quando o parser
  normaliza a descrição.
- Arquivo integralmente já importado continua bloqueado pelo hash.
- Sobreposição parcial exige confirmação explícita; duplicados existentes são
  preservados e somente as ocorrências novas são inseridas.
- Classificação exige categoria compatível com receita/despesa.
- Lançamento classificado fica protegido até desbloqueio administrativo. Na
  classificação em lote, quando houver selecionados já classificados, a tela
  pergunta se o administrador quer manter esses itens ou reclassificá-los; a
  segunda opção fica registrada na auditoria.
- Confirmar vínculo replica categoria/subcategoria sem alterar os dados reais.
- Rejeitar vínculo impede a repetição do mesmo candidato.
- Lote padrão exige mesma data, mesmo valor em centavos e descrição >= 75%.
- Parcelamento compara parcela × total com o histórico, tolerância de R$ 1 e
  descrição >= 50%; múltiplos candidatos exigem revisão.
- Parcelas do documento nunca são substituídas pelo total da compra.
- Conciliação exige uma entrada e uma saída de mesmo valor em centavos.
- Pares conciliados não entram nos totais dos relatórios.
- `Antigo`, `Planilha Passada` e `Primeira Planilha` significam histórico sem
  conta.
- `Cartao Sulivan` é alias de `CARTAO SANTANDER` somente na base histórica.

## Decisões confirmadas

- Usar o código como fonte principal da verdade.
- Preservar dados financeiros existentes durante qualquer evolução.
- Manter PostgreSQL; não trocar banco sem evidência.
- Novos schemas devem usar migrations versionadas.
- Manter fallback inline até existir worker separado homologado.
- Medir performance antes de criar índices, cache ou novas estruturas.
- Usar ação humana para classificações e vínculos.
- Manter Sentry opcional e logs sem payload financeiro.
- NUMERIC, foreign keys, object storage, calibração estatística e Pluggy não
  estão autorizados para implementação imediata.

## Tarefas pendentes confirmadas

Consulte `ROADMAP.md`. As prioridades atuais são:

1. Validar administração, colaborador, auditoria, logs e Sentry no ambiente
   hospedado.
2. Medir performance de vínculos e consultas antes de criar otimizações SQL.
3. Concluir a separação dos 13 handlers ainda mantidos no núcleo do backend.
4. Reduzir os componentes frontend acima de 400 linhas: `arquivos/page.tsx`,
   `ImportPage.tsx` e `useTransactionTable.tsx`.
5. Manter contexto, arquitetura, API, releases e roadmap sincronizados a cada
   marco homologado.
6. Usar migration versionada para qualquer nova mudança de schema.

## Itens explicitamente abandonados

- Aplicação desktop Tkinter/PyInstaller.
- FastAPI, SQLAlchemy, Alembic e Docker Compose como arquitetura vigente.
- SQLite como banco de produção.
- Importação automática por pasta.
- Importação direta sem preview.
- Competência de cartão pelas datas dos lançamentos.
- Descartar parcelas posteriores ou substituí-las pelo total.
- Autoclassificação sem ação humana.
- Vinculação global automática sem seleção/revisão.
- Reinserção forçada de duplicados existentes.
- Base histórica obrigatoriamente importada uma única vez.
- Contas históricas antigas como contas válidas para documentos atuais.

## Pontos que precisam de confirmação

- Regra de data do vínculo parcelado em lote: o código estrito atual não exige
  proximidade de data, enquanto o vínculo individual exige até 7 dias.
- Se `ledgers/Contas Correntes` é funcionalidade permanente.
- Aprovação de custo para Background Worker separado no Render.
- Necessidade de telas próprias para usuários e auditoria.
- Destino do endpoint `/system/audit-snapshot` e do script de auditoria local.
- Se a restauração do backup volta a ser bloqueio antes da próxima migration.
- Quando divergência de saldo ou linhas rejeitadas deve bloquear uma importação.
