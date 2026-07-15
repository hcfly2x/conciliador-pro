# Contexto do Projeto - Conciliador Pro

Este arquivo e a fonte de verdade para novas conversas e trabalhos no projeto. O codigo atual tem prioridade em caso de divergencia tecnica, mas nenhuma regra de negocio deve ser alterada sem confirmar as decisoes registradas aqui.

## Objetivo do produto

O Conciliador Pro e uma aplicacao web de gestao financeira pessoal para o proprietario e colaboradores autorizados. Ele importa extratos bancarios e faturas de cartao, transforma os documentos em lancamentos, evita duplicacoes, permite classificacao financeira e gera relatorios.

A base historica e auxiliar: ela sugere categorias e subcategorias e pode ser vinculada a lancamentos reais, mas nunca cria nem substitui lancamentos reais.

## Estado atual

- Frontend publicado na Vercel.
- Backend publicado no Render.
- Banco de producao informado: Supabase/PostgreSQL.
- Banco local alternativo: SQLite.
- Build do frontend aprovado na auditoria de 15/07/2026.
- Vinte testes automatizados do backend aprovados na revisao de 15/07/2026.
- A validacao completa dos seis tipos de documento ainda nao foi concluida.
- A producao nao foi validada de ponta a ponta com autenticacao durante a auditoria.

## Arquitetura e stack

- Backend: Python, Flask 3 e Gunicorn.
- Frontend: Next.js 15, React 19 e TypeScript.
- Interface: Tailwind CSS 4.
- Estado do frontend: Zustand.
- Banco: PostgreSQL por `DATABASE_URL`, com fallback SQLite.
- Persistencia: SQL direto, sem ORM.
- Schema inicializado e atualizado por `init_db()`; ainda nao existe ferramenta formal de migrations.
- PDFs: pypdf.
- XLSX: openpyxl.
- XLS: xlrd.
- Autenticacao: token Bearer e sessoes persistidas no banco.
- Perfis existentes: administrador e colaborador.
- Deploy: GitHub, Vercel, Render e Supabase.
- Commit e push exigem autorizacao explicita do usuario.

## Funcionalidades existentes

- Login, logout, sessoes e perfis de acesso.
- Auditoria de operacoes relevantes no backend.
- Importacao de CSV, XLS, XLSX e PDF.
- Parsers para Santander, XP e Nubank.
- Deteccao de conta, banco e tipo de documento.
- Correcao manual da conta antes da confirmacao.
- Preview antes da importacao.
- Validacao de receitas, despesas, duplicados e saldo quando suportado pelo documento.
- Preservacao de duplicados legitimos dentro do mesmo arquivo.
- Bloqueio de duplicados ja existentes no banco pelo fluxo normal.
- Armazenamento e download do documento original.
- Cofre e cobertura de arquivos.
- Cadastro de contas, categorias e subcategorias.
- Classificacao por categoria, subcategoria e observacao.
- Bloqueio apos classificacao e desbloqueio administrativo.
- Classificacao em lote.
- Base historica separada dos lancamentos reais.
- Sugestoes de categoria e subcategoria baseadas na base historica e nos lancamentos classificados.
- O upload da base historica responde imediatamente e a importacao e o recalculo de vinculos rodam como jobs persistentes, sem manter a requisicao HTTP bloqueada.
- Vinculo entre registros da base historica e lancamentos reais.
- Agrupamento e propagacao de classificacao entre parcelas reconhecidas.
- Relatorios de resumo, categoria e evolucao mensal.
- Contas correntes internas (`ledgers`) implementadas no codigo, mas ainda nao utilizadas pelo usuario.
- Reset administrativo.

## Regras de negocio vigentes

- Lancamentos reais so podem ser criados a partir de extratos e faturas.
- A base historica serve para sugestoes e vinculos; ela nao cria lancamentos reais.
- A autoclassificacao e proibida. O sistema apenas apresenta sugestoes e o usuario decide se deseja aplica-las.
- As sugestoes devem considerar a base historica e os lancamentos ja classificados.
- Quando um lancamento estiver vinculado a base historica, a coluna de status deve exibir `Vinculado`, e nao `Manual`.
- Um candidato a vinculo historico so deve ser apresentado a partir de 96% de compatibilidade.
- O candidato deve mostrar lado a lado os dados do lancamento real e do registro historico.
- O vinculo so e confirmado depois de acao humana explicita; uma rejeicao deve impedir que o mesmo candidato reapareca para o lancamento.
- Confirmar um vinculo nao aplica categoria ou subcategoria automaticamente.
- Despesas tem valor negativo.
- Receitas tem valor positivo.
- Lancamentos de cartao sao despesas por padrao.
- Estornos, cashback, abatimentos e creditos podem ser receitas.
- Duplicados internos de um arquivo podem ser legitimos e sao preservados.
- Lancamentos ja existentes no banco nao devem ser importados novamente.
- Toda importacao passa por preview e confirmacao.
- A conta detectada pode ser corrigida antes da confirmacao.
- Cada parcela permanece como um lancamento mensal real.
- Parcelas futuras nao sao criadas artificialmente.
- Categoria e subcategoria podem ser propagadas entre parcelas reconhecidas.
- Observacoes sao individuais.
- Categoria e obrigatoria para concluir a classificacao.
- Subcategoria e observacao sao opcionais.
- Depois da classificacao, o lancamento fica bloqueado contra alteracoes acidentais.
- Apenas administradores podem desbloquear um lancamento.
- Relatorios devem considerar somente lancamentos reais.
- Relatorios incluem todos os lancamentos reais, classificados ou pendentes, e excluem apenas duplicados e ignorados.
- Excluir um documento do cofre nao exclui lancamentos sem uma segunda operacao e confirmacao explicitas.
- Duplicados ja existentes no banco nunca podem ser reinseridos, nem por parametro interno da API.
- Documentos originais devem permanecer disponiveis para uma eventual auditoria futura, mesmo que sejam consultados raramente.

## Tratamento das contas da base historica

- `CARTAO SULIVAN` representa uma fatura do cartao Santander.
- `PLANILHA PASSADA`, `PRIMEIRA PLANILHA` e `ANTIGO` nao representam contas financeiras reais.
- Registros historicos com essas tres origens podem pertencer a qualquer conta ou fatura do Nubank, XP ou Santander.
- Essas origens desconhecidas nao devem reduzir a probabilidade de uma sugestao apenas por nao coincidirem com a conta do lancamento real.
- Para registros historicos com uma conta real conhecida, a conta pode ser considerada como evidencia no calculo da sugestao.

## Decisoes confirmadas

- A aplicacao e web e multiusuario.
- PostgreSQL e o banco de producao; SQLite e apenas uma alternativa local.
- A planilha antiga nao e fonte oficial de lancamentos.
- A base historica continua sendo usada para sugestoes e vinculos com lancamentos reais.
- A interface deve distinguir claramente um vinculo historico de uma classificacao manual.
- Vinculos historicos usam limiar inicial de 96% e exigem confirmacao humana depois da comparacao visual dos dois registros.
- Administradores e colaboradores podem confirmar ou rejeitar candidatos de vinculo historico.
- Autoclassificacao nao deve existir, independentemente da probabilidade calculada.
- Compras parceladas nao sao consolidadas em um unico lancamento.
- Cada parcela e registrada no mes em que aparece na fatura.
- A interface administrativa completa de usuarios e auditoria nao e necessaria por enquanto.
- Contas correntes internas ficam estacionadas. Antes de evolui-las, deve-se avaliar se os relatorios atendem a necessidade.
- Os documentos originais sao mantidos para auditoria eventual.
- Alteracoes Git so sao publicadas com autorizacao explicita.

## Tarefas pendentes confirmadas

- Validar integralmente os parsers de extrato e cartao de Santander, XP e Nubank.
- Conferir quantidade, data, valor, sinal, competencia e duplicidade.
- Melhorar a normalizacao de descricoes e estabelecimentos.
- Separar similaridade tecnica de probabilidade apresentada ao usuario.
- Considerar descricao, conta quando conhecida, valor e data nas sugestoes.
- Tratar origens historicas desconhecidas sem penalizar a sugestao por conta.
- Calcular categoria antes da subcategoria.
- Condicionar as sugestoes de subcategoria a categoria.
- Exibir as tres melhores sugestoes e suas justificativas.
- Criar metricas Top 1, Top 3 e calibracao.
- Manter toda aplicacao de sugestao dependente de acao humana.
- Ampliar testes de integracao.
- Revisar seguranca, banco e deploy de producao.
- Avaliar se a aba de relatorios elimina a necessidade de evoluir contas correntes internas.
- Limpar codigo e documentacao legados depois de verificar o impacto.

## Itens explicitamente abandonados

- Aplicativo desktop ou Tkinter como arquitetura principal.
- Executavel local como produto final.
- SQLite local como banco de producao.
- Importacao automatica de uma pasta fixa do Desktop.
- Planilha antiga como fonte de lancamentos reais.
- Criacao de lancamentos reais pela base historica.
- Autoclassificacao por probabilidade ou match historico.
- Consolidacao do valor total de compras parceladas.
- Descarte das parcelas futuras.
- Estrutura baseada nas abas `SAIDAS`, `ENTRADAS` e `HELCIO`.
- Relatorio exclusivo da Smartek.
- Organizacao de arquivos em pastas como banco principal.
- Interface administrativa completa de usuarios e auditoria no escopo atual.
- Evolucao imediata das contas correntes internas.

## Pontos que ainda precisam de confirmacao

- Remocao segura dos tratamentos legados da Smartek no importador historico, depois de verificar se existem dados atuais dependentes deles.
- Local definitivo dos documentos originais. Eles devem permanecer acessiveis para auditoria, mas e necessario avaliar se Base64 no PostgreSQL e a melhor opcao ou se deve ser usado armazenamento de objetos.
- Confirmacao de que a producao utiliza o mesmo schema e commit do repositorio auditado.
