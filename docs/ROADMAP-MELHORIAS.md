# Roadmap de Melhorias

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

- [ ] Permitir selecionar o arquivo antes de escolher uma conta.
- [ ] Detectar banco, conta/cartao e tipo do documento pelo conteudo e nome.
- [ ] Exibir confianca e evidencias usadas na deteccao.
- [ ] Permitir correcao manual antes da pre-visualizacao final.
- [ ] Detectar competencia de extratos pelo periodo declarado e pelas datas.
- [ ] Detectar competencia de cartoes pela data valida mais recente da fatura.
- [ ] Alertar divergencias entre nome, conteudo, conta e competencia.
- [ ] Exibir todos os lancamentos antes de salvar.
- [ ] Exibir entradas, saidas, totais, duplicados e linhas descartadas.
- [ ] Bloquear confirmacao quando houver erro critico de leitura.

### Criterios de aceite

- Nenhuma transacao e salva durante a etapa de deteccao ou pre-visualizacao.
- O usuario sempre pode corrigir conta e competencia antes de confirmar.
- Totais e quantidade da pre-visualizacao correspondem ao documento original.

## Fase 3 - Testes do motor de importacao

- [ ] Criar amostras anonimizadas ou autorizadas de Extrato Santander.
- [ ] Criar amostras anonimizadas ou autorizadas de Extrato XP.
- [ ] Criar amostras anonimizadas ou autorizadas de Extrato Nubank.
- [ ] Criar amostras anonimizadas ou autorizadas de Cartao Santander.
- [ ] Criar amostras anonimizadas ou autorizadas de Cartao XP.
- [ ] Criar amostras anonimizadas ou autorizadas de Cartao Nubank.
- [ ] Testar quantidade, valores, sinais, datas, duplicados e competencia.
- [ ] Criar testes de regressao para cada erro corrigido.

## Fase 4 - Sugestoes de categoria e subcategoria

- [ ] Separar score de similaridade de probabilidade calibrada.
- [ ] Melhorar a normalizacao de estabelecimentos e descricoes.
- [ ] Correlacionar descricao, conta, valor e data.
- [ ] Calcular categoria antes da subcategoria.
- [ ] Condicionar subcategorias a categoria sugerida.
- [ ] Considerar frequencia sem favorecer categorias genericas em excesso.
- [ ] Exibir as tres melhores sugestoes com justificativa curta.
- [ ] Criar avaliacao retrospectiva usando a base historica.
- [ ] Medir acerto Top 1, Top 3 e por faixa de confianca.
- [ ] Definir limites seguros para aplicacao automatica.

## Fase 5 - Qualidade, seguranca e publicacao

- [ ] Testar as travas de lancamentos classificados.
- [ ] Revisar permissoes de administrador e colaborador.
- [ ] Revisar auditoria de alteracoes e desbloqueios.
- [ ] Executar build e testes completos.
- [ ] Revisar o diff antes de cada commit.
- [ ] Solicitar autorizacao explicita antes de commit e push.
- [ ] Validar a versao publicada na Vercel e no Render.
