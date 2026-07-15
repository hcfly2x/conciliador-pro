# Roadmap de Finalizacao - Conciliador Pro

Revisao consolidada em 15/07/2026 a partir do codigo atual, do
`PROJECT_CONTEXT.md` e dos roadmaps anteriores.

Este e o checklist operacional vigente para finalizar o aplicativo. Documentos
anteriores continuam como historico, mas nao devem prevalecer sobre este arquivo,
o `PROJECT_CONTEXT.md` ou o codigo atual.

Regra de publicacao: commit e push exigem autorizacao explicita do proprietario.

## Diagnostico executivo

O fluxo principal existe e o produto ja e utilizavel: autenticacao, importacao com
preview, deduplicacao, classificacao, bloqueio, base historica, sugestoes, parcelas,
cofre, relatorios e deploy web estao implementados. O trabalho restante nao pede
reescrita; pede corrigir quatro fluxos criticos, fechar a regressao dos parsers,
consolidar regras e validar producao.

### Achados bloqueadores

1. A importacao ainda classifica automaticamente um lancamento quando encontra
   data, valor, descricao e tipo iguais em outro lancamento classificado. Isso
   viola a regra que proibe autoclassificacao e ainda ignora a conta nessa busca.
2. Na tabela, selecionar categoria salva e bloqueia imediatamente o lancamento.
   Isso impede o preenchimento normal de subcategoria e observacao antes do
   bloqueio.
3. A exclusao de documentos tem comportamentos diferentes: apagar um documento
   persistido no banco preserva os lancamentos; apagar um arquivo local remove
   arquivo, importacao e lancamentos na mesma operacao.
4. Os relatorios usam universos diferentes. Resumo geral e evolucao mensal filtram
   `locked=0`, enquanto resumo mensal e categoria incluem classificados e pendentes.

### Achados de alta prioridade

1. Categoria e subcategoria recebidas pela API nao sao validadas quanto a
   existencia, compatibilidade entre si ou tipo receita/despesa.
2. O motor de sugestoes consulta apenas `classification_history`; lancamentos
   classificados diretamente nao sao consultados como segunda fonte, apesar da
   regra consolidada.
3. O endpoint de confirmar/rejeitar vinculo historico nao esta liberado para o
   perfil colaborador, embora a documentacao de perfis atribua essa operacao ao
   trabalho cotidiano.
4. A API ainda aceita `import_db_duplicates`, capaz de forcar a reinsercao de um
   lancamento detectado no banco.
5. Next.js 15.5.15 possui alertas de seguranca conhecidos; `npm audit` recomenda
   atualizacao compativel para 15.5.20.
6. Login nao possui limitacao de tentativas, atraso progressivo ou bloqueio
   temporario.

### Divida tecnica relevante

1. `backend/app.py` concentra aproximadamente 5.000 linhas e mistura API, schema,
   importacao, classificacao, documentos e relatorios.
2. Alteracoes de schema rodam na inicializacao sem ferramenta formal de migrations.
3. Valores monetarios usam `REAL`/double precision; deve-se avaliar `NUMERIC` no
   PostgreSQL antes de ampliar o uso financeiro.
4. As tabelas nao declaram chaves estrangeiras, deixando integridade referencial
   dependente do codigo.
5. Documentos sao armazenados em Base64 dentro do PostgreSQL, aumentando tamanho e
   memoria de leitura. O destino definitivo ainda precisa de decisao.
6. Roadmaps e documentos de arquitetura contem decisoes antigas sobre vinculo,
   armazenamento, banco e contagem de testes.

## Checklist ordenado de implementacao

### Etapa 0 - Congelar regras e proteger dados

- [x] Confirmar o universo oficial dos tres relatorios.
- [x] Confirmar a UX de excluir somente o documento ou documento mais lancamentos.
- [x] Confirmar a remocao definitiva de `import_db_duplicates`.
- [x] Confirmar se colaboradores podem revisar candidatos de vinculo historico.
- [ ] Fazer backup verificavel do PostgreSQL de producao antes de migrations.
- [ ] Registrar commit e schema atualmente publicados em Vercel, Render e Supabase.

**Saida:** decisoes pendentes fechadas e backup restauravel.

### Etapa 1 - Corrigir bloqueadores de regra e integridade

- [x] Remover a classificacao automatica por correspondencia exata na importacao;
      manter o resultado apenas como sugestao.
- [x] Transformar categoria, subcategoria e observacao em um rascunho unico com
      botao explicito `Salvar e bloquear`.
- [x] Validar no backend que categoria existe e corresponde ao tipo do lancamento.
- [x] Validar que subcategoria existe antes de salvar.
- [ ] Preservar categoria e subcategoria entre parcelas somente pela regra
      confirmada de plano de parcelamento.
- [ ] Separar explicitamente exclusao de arquivo e exclusao de lancamentos, com
      confirmacoes e auditorias distintas.
- [x] Unificar filtros dos relatorios conforme a decisao da Etapa 0.
- [ ] Criar testes de integracao para classificacao, bloqueio, desbloqueio,
      propagacao de parcelas e exclusao de documentos.

**Saida:** nenhuma classificacao sem acao humana e nenhuma exclusao ambigua.

### Etapa 2 - Fechar o motor de importacao

- [ ] Criar fixtures anonimizadas dos seis tipos oficiais: extrato e cartao de
      Santander, XP e Nubank.
- [ ] Para cada fixture, afirmar quantidade, datas, valores, sinais, competencia,
      conta detectada, duplicados internos, duplicados no banco e linhas rejeitadas.
- [ ] Testar PDFs vazios, protegidos, corrompidos e com layout inesperado.
- [ ] Testar CSV/XLS/XLSX com encoding, separador, coluna e formato monetario
      diferentes.
- [ ] Testar reimportacao do mesmo arquivo e arquivos distintos com lancamentos
      coincidentes.
- [x] Remover a opcao de reinserir duplicados do banco, se confirmada na Etapa 0.
- [x] Garantir limite de tamanho e extensao antes de ler arquivos em memoria.
- [ ] Tornar falha de saldo e linhas rejeitadas criterios de bloqueio configurados
      por tipo de documento.

**Saida:** regressao automatizada completa dos seis parsers e deduplicacao.

### Etapa 3 - Finalizar vinculos historicos

- [x] Usar limiar inicial de 96% para apresentar candidato.
- [x] Exibir comparacao lado a lado antes da decisao.
- [x] Exigir confirmacao humana e persistir rejeicao do mesmo candidato.
- [x] Exibir `Vinculado` somente depois da confirmacao.
- [ ] Testar API e interface de confirmar, rejeitar, desvincular e recalcular.
- [x] Definir permissao de colaborador e alinhar guard, frontend e documentacao.
- [ ] Exibir justificativa objetiva: diferenca de data, diferenca de valor e
      similaridade de descricao, sem chamar score tecnico de probabilidade.
- [ ] Medir falsos positivos do limiar de 96% com amostra real antes da producao.

**Saida:** vinculo revisavel, auditavel e sem efeito de autoclassificacao.

### Etapa 4 - Reconstruir o motor de sugestoes

- [ ] Normalizar estabelecimentos removendo ruido bancario, parcelas, IDs e sufixos.
- [x] Usar base historica e lancamentos classificados como fontes de evidencia.
- [ ] Tratar origens historicas desconhecidas sem penalidade de conta.
- [ ] Calcular categoria primeiro e subcategoria condicionada a categoria.
- [ ] Separar similaridade tecnica, confianca e probabilidade calibrada.
- [ ] Exibir Top 3 com justificativas curtas e fontes de evidencia.
- [x] Filtrar categorias da interface pelo tipo receita/despesa.
- [x] Adicionar subcategoria a classificacao em lote.
- [ ] Criar avaliacao retrospectiva com Top 1, Top 3, cobertura e calibracao.
- [ ] Manter toda aplicacao dependente de clique humano.

**Saida:** sugestoes mensuraveis, explicaveis e coerentes com as regras do produto.

### Etapa 5 - Consolidar cofre, relatorios e escopo

- [ ] Implementar a UX de exclusao decidida na Etapa 0.
- [ ] Escolher Base64 no PostgreSQL ou armazenamento de objetos para os originais.
- [ ] Testar upload, download, exclusao, cobertura e auditoria no destino escolhido.
- [ ] Exibir claramente pendentes/sem categoria nos relatorios, se incluidos.
- [ ] Testar totais e percentuais contra consultas de referencia.
- [ ] Avaliar com o usuario se os relatorios eliminam a necessidade de `ledgers`.
- [ ] Se eliminarem, ocultar e depois remover `ledgers`; se nao, definir seu caso de
      uso antes de evoluir a funcionalidade.

**Saida:** documentos auditaveis e relatorios com significado financeiro definido.

### Etapa 6 - Seguranca, schema e manutencao

- [x] Atualizar Next.js para uma versao 15.5.x sem os alertas do `npm audit` e
      repetir build/testes.
- [ ] Restringir `CORS_ORIGINS` em producao e falhar de forma segura se estiver `*`.
- [x] Adicionar rate limit e bloqueio temporario ao login.
- [ ] Revisar token no `localStorage` e CSP.
- [x] Adicionar cabecalhos basicos contra MIME sniffing, framing e vazamento de referrer.
- [ ] Testar expiracao, logout, desativacao e troca de perfil em mais de um worker.
- [x] Impedir desativar ou rebaixar o ultimo administrador ativo.
- [ ] Introduzir migrations versionadas antes de novas alteracoes de schema.
- [ ] Adicionar chaves estrangeiras/indices apos auditoria dos dados existentes.
- [ ] Avaliar migracao de dinheiro para `NUMERIC`, com testes de arredondamento.
- [ ] Dividir `app.py` gradualmente por dominios, sem reescrever os parsers.
- [ ] Adicionar CI para testes Python, typecheck, build e auditoria de dependencias.

**Saida:** deploy repetivel, schema versionado e riscos de seguranca reduzidos.

### Etapa 7 - Limpeza e documentacao

- [ ] Remover tratamentos Smartek somente depois de verificar dados dependentes.
- [ ] Remover endpoints e clientes desativados de autoclassificacao e bulk-vincular.
- [ ] Remover mocks e telas locais legadas se nao tiverem uso confirmado.
- [ ] Corrigir textos/encoding visiveis e revisar responsividade.
- [ ] Atualizar `PROJECT_CONTEXT.md`, arquitetura, API, deploy e README.
- [ ] Marcar roadmaps antigos explicitamente como historicos.

**Saida:** uma unica documentacao coerente com o produto publicado.

### Etapa 8 - Homologacao e encerramento

- [ ] Executar suite completa em SQLite e PostgreSQL limpo.
- [ ] Restaurar backup em ambiente de teste e validar migrations.
- [ ] Importar os seis documentos oficiais em homologacao e conferir manualmente.
- [ ] Validar login de admin e colaborador, permissoes e auditoria.
- [ ] Validar classificacao, parcelas, sugestoes, vinculos, cofre e relatorios.
- [ ] Fazer teste de fumaca na Vercel, Render e Supabase com autenticacao real.
- [ ] Revisar diff, dependencias e variaveis de ambiente.
- [ ] Obter autorizacao explicita para commit e push.
- [ ] Publicar, validar novamente e registrar commit/schema da versao final.

**Saida:** versao final homologada, publicada e rastreavel.

## Verificacoes realizadas nesta revisao

- 20 testes Python aprovados.
- Compilacao Python aprovada.
- TypeScript sem erros.
- Build de producao Next.js aprovado.
- `pip check` sem dependencias quebradas.
- `npm audit --omit=dev`: nenhuma vulnerabilidade conhecida depois da atualizacao
  do Next.js e do override seguro de PostCSS.
