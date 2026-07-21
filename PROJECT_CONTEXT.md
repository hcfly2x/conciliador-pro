# PROJECT_CONTEXT.md — Conciliador Pro

## Objetivo do produto

Aplicativo web de controle financeiro pessoal que importa extratos e faturas,
organiza lançamentos reais por conta, permite classificação manual e usa uma
base histórica como evidência para acelerar a classificação.

Fluxo principal:

1. Importar a base histórica.
2. Importar extratos e faturas.
3. Revisar vínculos diretos com a base histórica.
4. Calcular sugestões.
5. Classificar manualmente o restante.
6. Conciliar transferências internas quando aplicável.

## Estado atual

O produto possui fluxo funcional de autenticação, importação com preview,
deduplicação, base histórica, vínculos revisáveis, sugestões assíncronas,
classificação, parcelas, conciliação, relatórios, cofre de documentos e reset.

A branch principal é `main`. A preservação da conta do lançamento ao confirmar
um vínculo histórico está implementada e publicada.

## Arquitetura e stack

- Frontend: Next.js 15, React 19, TypeScript, Tailwind CSS, Zustand e Playwright.
- Backend: Flask, Python e Gunicorn.
- Banco: PostgreSQL em ambiente configurado com `DATABASE_URL`; SQLite como
  fallback local e para testes.
- Persistência: SQL direto com adaptador de compatibilidade SQLite/PostgreSQL.
- Arquivos: documentos originais armazenados em Base64 no banco, com fallback
  local.
- CI: GitHub Actions executa testes Python, typecheck/build do frontend e
  testes Playwright.

## Funcionalidades existentes

- Login, sessões, perfis `admin` e `colaborador`, auditoria e rate limit.
- Importação de CSV, XLS/XLSX e PDF com preview, validações, totais, avisos e
  deduplicação.
- Confirmação da importação executada em job assíncrono, com retomada do
  acompanhamento após atualização da página e proteção contra confirmação
  duplicada.
- O job de importação expõe fase, progresso numérico e logs recentes na tela.
- Detecção automática de conta com possibilidade de seleção manual.
- Parsers para Santander, Nubank e XP.
- Cadastro de contas, categorias e subcategorias.
- Importação assíncrona da base histórica com progresso e logs.
- Vínculos históricos revisáveis a partir de score de 96%.
- Sugestões persistidas de categoria e subcategoria, calculadas manualmente em
  job separado.
- Central de classificação, classificação em lote e tratamento de parcelas.
- Conciliação manual e reversível de entrada e saída de mesmo valor.
- Relatórios de resumo, categorias e evolução mensal.
- Cofre de documentos, cobertura de arquivos e reset administrativo.
- Contas correntes (`ledgers`) acessíveis no menu.

## Regras de negócio vigentes

- Extratos e faturas são a fonte de verdade dos lançamentos reais.
- A base histórica não cria lançamentos reais; serve como evidência de
  classificação.
- Não existe autoclassificação: toda classificação exige ação humana.
- Qualquer lançamento do arquivo que já exista no banco bloqueia o lote inteiro,
  pois indica arquivo repetido; não existe importação parcial nesse caso.
- Ocorrências repetidas dentro do mesmo arquivo são lançamentos legítimos e são
  preservadas integralmente com chaves distintas.
- Despesas possuem valor negativo; receitas possuem valor positivo.
- Um vínculo histórico é apresentado para revisão com score mínimo de 96%.
- Em compras parceladas, o valor da parcela e a data reconstruída da primeira
  parcela podem ser comparados ao valor total parcelado e à data da compra na
  base histórica. Essa comparação serve apenas como evidência: os valores e as
  datas dos lançamentos reais continuam exatamente como vieram dos arquivos.
- Confirmar vínculo replica categoria e subcategoria do histórico e bloqueia o
  lançamento.
- Confirmar vínculo nunca substitui a conta do lançamento real; a conta vinda
  do arquivo bancário é a fonte mais confiável.
- Rejeitar vínculo impede que o mesmo candidato reapareça para aquele
  lançamento.
- Lançamentos com vínculo direto pendente não recebem sugestões nem podem ser
  classificados antes da revisão.
- Conciliação exige uma entrada e uma saída com o mesmo valor absoluto e pode
  ser desfeita.
- Lançamentos conciliados não entram nos totais dos relatórios.
- Durante a homologação, o reset completo do sistema é permitido; backup
  persistente não é requisito imediato.

## Decisões confirmadas

- O vínculo histórico é revisável, nunca automático.
- O cálculo de sugestões é separado da importação e iniciado manualmente.
- Categoria e subcategoria do histórico são replicadas somente após confirmação.
- A conta do documento importado prevalece sobre a conta da base histórica.
- Existe uma única base histórica importada ativa. Uma nova importação exige
  confirmação administrativa explícita e só substitui a base anterior depois
  que o novo arquivo produzir registros válidos.
- Lançamentos selecionados podem ter vínculos históricos confirmados em lote;
  essa ação permanece na tabela e aplica categoria e subcategoria em uma única
  operação no servidor, sem navegar para a Central de Classificação.
- A preparação pelo botão `Vincular selecionados` é mais restritiva que os
  demais fluxos: exige similaridade de descrição superior a 95%, diferença de
  data igual a zero e diferença de valor igual a R$ 0,00.

## Tarefas pendentes confirmadas

Nenhuma nova funcionalidade de produto está confirmada para implementação
imediata. As próximas mudanças devem respeitar este contexto e depender de
confirmação explícita quando alterarem escopo ou arquitetura.

## Itens explicitamente abandonados

- Autoclassificação por histórico ou correspondência exata.
- Vínculo automático sem confirmação humana.
- Importação direta sem preview e confirmação.
- Importação automática por pasta.
- Reinserção forçada de duplicados já existentes no banco.
- Arquitetura planejada com FastAPI, SQLAlchemy e Alembic.

## Pontos que precisam de confirmação

- `Ledgers`/Contas Correntes permanece no escopo do produto?
- Documentos devem continuar no PostgreSQL em Base64 quando os dados se
  tornarem persistentes?
- O score de confiança deve evoluir para probabilidade estatisticamente
  calibrada?
- Qual é o ambiente e a versão efetivamente em produção?
- Quando backups verificáveis passarão a ser obrigatórios?
