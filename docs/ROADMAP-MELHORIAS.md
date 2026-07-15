# Roadmap de Melhorias

> Documento historico. O checklist consolidado vigente esta em
> `docs/ROADMAP-FINALIZACAO.md`.

Este documento e o checklist oficial das proximas entregas do Conciliador Pro.

Regra de publicacao: nenhuma alteracao deve receber commit ou push sem autorizacao
explicita do proprietario do repositorio `hcfly2x/conciliador-pro`.

## Fase 0 - Fundacao tecnica

- [x] Tornar o proxy local da API configuravel.
- [x] Adicionar `.env.example` para o frontend.
- [x] Proteger dependencias, builds, bancos e segredos locais com `.gitignore`.
- [x] Substituir o README generico do Next.js.
- [x] Validar sintaxe do backend e build de producao do frontend.

## Fase 1 - Performance e Cofre de Arquivos

- [x] Consultar a cobertura de apenas um ano por requisicao.
- [x] Eliminar consultas repetidas por conta e mes.
- [x] Exibir sempre os 12 meses de 2023, 2024, 2025 e 2026.
- [x] Abrir 2026 por padrao.
- [x] Diferenciar `importado`, `faltando`, `dispensado` e `futuro`.
- [x] Calcular os totais apenas para o ano selecionado.
- [x] Proteger a interface contra celulas ausentes.
- [x] Manter a listagem detalhada sob demanda ao selecionar uma celula.

### Criterios de aceite

- A pagina abre sem executar uma consulta ao banco para cada celula.
- A troca de ano carrega somente os 12 meses selecionados.
- Mes futuro sem arquivo nao aumenta o contador de faltantes.
- Uma conta sem dados continua aparecendo com todas as celulas do ano.

Validacao local em 2026-07-14:

- API `/api/v1/coverage?year=2026`: status 200, 12 meses e 6 contas.
- Todas as contas retornaram exatamente 12 celulas.
- Sintaxe do backend validada.
- Build de producao do frontend concluida com sucesso.

## Fase 2 - Deteccao e pre-validacao de importacoes

- [x] Permitir selecionar o arquivo antes de escolher uma conta.
- [x] Detectar banco, conta/cartao e tipo do documento pelo conteudo e nome.
- [x] Exibir confianca e evidencias usadas na deteccao.
- [x] Permitir correcao manual antes da pre-visualizacao final.
- [x] Detectar competencia de extratos pelo periodo declarado e pelas datas.
- [x] Detectar competencia de cartoes pela data valida mais recente da fatura.
- [x] Alertar divergencias entre nome, conteudo, conta e competencia.
- [x] Exibir todos os lancamentos antes de salvar.
- [x] Exibir entradas, saidas, totais, duplicados e linhas descartadas.
- [x] Bloquear confirmacao quando houver erro critico de leitura.

### Criterios de aceite

- Nenhuma transacao e salva durante a etapa de deteccao ou pre-visualizacao.
- O usuario sempre pode corrigir conta e competencia antes de confirmar.
- Totais e quantidade da pre-visualizacao correspondem ao documento original.

Validacao local em 2026-07-15:

- Deteccao automatica correta nos 6 arquivos reais de janeiro/2026.
- Cartoes Nubank, Santander e XP identificados sem selecao manual.
- Extratos Nubank, Santander e XP identificados sem selecao manual.
- Endpoint de preview sem `account_id`: status 200 e conta XP detectada.
- Competencia de cartao calculada pelo ultimo lancamento valido.
- 7 testes automatizados de deteccao, competencia, parcelas e sinais aprovados.
- Build de producao do frontend concluida com sucesso.
- Alerta de baixa contagem adicionado para extratos com menos de 15 lancamentos.

## Fase 3 - Testes do motor de importacao

- [x] Validar amostras autorizadas de Extrato Santander.
- [x] Validar amostras autorizadas de Extrato XP.
- [x] Validar amostras autorizadas de Extrato Nubank.
- [x] Validar amostras autorizadas de Cartao Santander.
- [x] Validar amostras autorizadas de Cartao XP.
- [x] Validar amostras autorizadas de Cartao Nubank.
- [ ] Testar quantidade, valores, sinais, datas, duplicados e competencia.
- [x] Criar testes de regressao para deteccao de conta e competencia.

Validacao local em 2026-07-15:

- 26 documentos reais de 2026 auditados sem gravar transacoes.
- Todas as 6 familias tiveram conta e tipo detectados corretamente.
- CSV XP de janeiro: 95 linhas no arquivo e 95 lancamentos no parser.
- CSV Nubank de janeiro: 105 linhas no arquivo e 105 lancamentos no parser.
- Regra incorreta que descartava parcelas 2+ removida.
- Cada parcela agora preserva o valor exibido na fatura.
- Extrato Nubank de janeiro com 2 itens conferido visualmente e confirmado correto.
- Extrato XP de fevereiro contem somente o cabecalho e e bloqueado como arquivo vazio.
- Ferramenta `backend/audit_import_samples.py` criada para repetir a auditoria.

## Fase 3.1 - Parcelamentos de cartao

- [x] Preservar cada parcela como lancamento real no mes e no valor do documento.
- [x] Criar plano persistente para vincular parcelas da mesma compra.
- [x] Evitar agrupamento automatico quando houver ambiguidade.
- [x] Classificar categoria e subcategoria uma unica vez por plano.
- [x] Aplicar a classificacao aos membros ainda desbloqueados do plano.
- [x] Herdar a classificacao quando uma parcela futura for importada.
- [x] Manter observacoes individuais por lancamento.
- [x] Exibir numero da parcela e quantidade de membros vinculados na tabela.
- [x] Criar testes de regressao para agrupamento e separacao de compras semelhantes.

### Regra adotada

O total da compra nao substitui as parcelas. Cada linha continua conciliando exatamente
com a fatura original. O vinculo automatico exige mesma conta, descricao normalizada,
quantidade total de parcelas, valor da parcela e coerencia entre datas e numero da
parcela. Quando mais de um plano for compativel, um novo plano e criado para evitar
misturar compras distintas.

Validacao local em 2026-07-15:

- 12 testes automatizados aprovados.
- Classificacao integrada pela API propagou categoria e subcategoria para 2 parcelas.
- Observacao permaneceu somente no lancamento editado.
- Importacao real do cartao XP preservou 95 lancamentos e criou 25 planos.
- Importacoes reais de janeiro e fevereiro vincularam 17 planos entre meses.
- Build de producao do frontend concluida com sucesso.

## Fase 4 - Sugestoes de categoria e subcategoria

- [ ] Separar score de similaridade de probabilidade calibrada.
- [ ] Melhorar a normalizacao de estabelecimentos e descricoes.
- [x] Correlacionar descricao, conta, valor e data.
- [x] Calcular categoria antes da subcategoria.
- [x] Condicionar subcategorias a categoria sugerida.
- [x] Considerar frequencia sem favorecer categorias genericas em excesso.
- [x] Exibir as tres melhores sugestoes com justificativa curta.
- [ ] Criar avaliacao retrospectiva usando a base historica.
- [ ] Medir acerto Top 1, Top 3 e por faixa de confianca.
- [x] Manter aplicacao automatica desativada por regra de produto.

## Fase 5 - Qualidade, seguranca e publicacao

- [ ] Testar as travas de lancamentos classificados.
- [ ] Revisar permissoes de administrador e colaborador.
- [ ] Revisar auditoria de alteracoes e desbloqueios.
- [x] Executar build e testes completos.
- [ ] Revisar o diff antes de cada commit.
- [ ] Solicitar autorizacao explicita antes de commit e push.
- [ ] Validar a versao publicada na Vercel e no Render.
