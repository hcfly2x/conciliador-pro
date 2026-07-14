# Briefing Para Claude - Conciliador Pro Web

## Objetivo Atual
Criar uma versao simples, robusta e web do Conciliador Pro para uso pessoal e por uma funcionaria, sem depender da maquina local do usuario.

## Direcao De Produto
- O app deve ser acessivel via web por mais de uma pessoa.
- Usar banco de dados web/hosted, nao banco local preso a uma maquina.
- Manter o fluxo simples: importar extrato/fatura, revisar lancamentos, salvar, classificar, consultar relatorios.
- Evitar complexidade prematura. Priorizar confiabilidade, clareza e facilidade de operacao.

## Regras De Lancamentos
- Lancamentos reais so devem nascer de documentos importados: extratos bancarios ou faturas de cartao.
- A base historica antiga nao deve criar lancamentos reais.
- A base historica pode continuar existindo apenas como fonte de sugestoes de categoria e subcategoria.
- Cartao de credito deve ser tratado como saida por padrao.
- Em cartao, entrada/receita so deve ocorrer em casos como estorno, reembolso, cashback, credito ou devolucao.
- Extratos de conta podem conter entradas e saidas.

## Travas Apos Salvar
Adicionar protecoes para evitar alteracao acidental de lancamentos ja classificados/salvos:
- Depois que categoria/subcategoria/observacao forem salvas, o registro deve ficar em modo protegido.
- Para alterar depois, exigir uma acao explicita como "editar" ou "desbloquear".
- Alteracoes importantes devem registrar auditoria: usuario, data/hora, campo alterado, valor anterior e novo valor.
- Nunca mudar categoria/subcategoria automaticamente depois que o usuario classificou manualmente, salvo confirmacao explicita.

## Importacao E Deduplicacao
- Antes de salvar uma importacao, mostrar uma tela de validacao visual.
- Mostrar total lido, novos, duplicados internos do arquivo e duplicados ja existentes no banco.
- Duplicados internos dentro do mesmo arquivo podem ser legitimos e nao devem ser bloqueados automaticamente.
- Duplicados contra o banco existente nao devem ser reinseridos por padrao.
- O usuario deve confirmar a importacao final depois de revisar.

## Acesso E Usuarios
- Prever usuarios/autenticacao simples.
- Pelo menos dois perfis: administrador e colaborador.
- Administrador pode importar, classificar, editar/desbloquear e gerenciar categorias.
- Colaborador pode operar classificacoes conforme permissao definida.
- Todas as acoes sensiveis devem ter trilha de auditoria.

## Base Historica
- A base historica ja nao e importante para conciliar com extratos.
- Ela pode ser mantida como banco de conhecimento para sugestoes de categoria/subcategoria.
- Sugestoes nunca devem sobrescrever classificacoes manuais sem confirmacao.

## Arquivos Excluidos Do Zip
Foram excluidos arquivos de runtime, cache, dependencias e dados locais sensiveis/travados:
- node_modules, .next, .venv, .npm-cache, __pycache__
- backend/data e bancos SQLite locais (*.db, *.db-shm, *.db-wal)
- logs, tools, deliverables antigos

## Problemas Do Projeto Local Atual
- Backend Flask local funciona via `backend/.venv`.
- Frontend Next.js local teve problemas no Windows com `spawn EPERM`.
- O objetivo agora nao e insistir no ambiente local antigo, e sim aproveitar regras/codigo/contexto para criar uma versao web simples e confiavel.
