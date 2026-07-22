# Code Review - Conciliador Pro (2026-07-14) - HISTORICO

> Registro historico do estado observado em 14/07/2026. Nao e uma especificacao
> vigente. Vinculos historicos e a operacao em lote foram posteriormente
> reintroduzidos por decisao confirmada, com revisao humana e regras estritas.
> Consulte `PROJECT_CONTEXT.md` e `docs/ROADMAP-FINALIZACAO.md`.

Objetivo declarado do dono do sistema: **classificar todas as entradas e saidas da conta com categoria e subcategoria (quando houver)**, com a base historica servindo apenas como fonte de sugestoes.

## 1. O fluxo principal esta solido

O caminho importar -> pendentes -> classificar -> protegido funciona de ponta a ponta (testado contra Postgres real):

- Lancamentos reais nascem apenas de extratos/faturas importados, com preview de validacao (total lido, duplicados internos permitidos, duplicados no banco bloqueados) antes do commit.
- Na tabela, cada linha pendente tem dropdown de categoria e subcategoria com sugestoes no topo (com % de confianca), chips de sugestao rapida e campo de observacao com salvamento automatico.
- Cada classificacao manual alimenta a `classification_history`, entao o sistema aprende: quanto mais voce classifica, melhores as sugestoes seguintes.
- Ao salvar, o lancamento trava (`locked`), com autor e data/hora; alterar exige desbloqueio de admin com auditoria.
- O contador de pendentes na barra lateral e a pagina /pendentes dao o caminho claro para "zerar" a classificacao.

## 2. Auto-criacao de categorias e subcategorias (confirmado no codigo)

- Ao importar a base historica (menu Importar historico), `find_or_create_category` e `find_or_create_subcategory` criam automaticamente tudo que aparecer nas planilhas, sem duplicar (comparacao sem diferenciar maiusculas).
- Criacao manual continua disponivel na tela Categorias (categorias com nome/tipo/cor; subcategorias por nome).
- Delecao e protegida: categoria ou subcategoria usada em lancamentos nao pode ser removida (o sistema avisa quantos lancamentos usam).

Observacao operacional importante: **no banco hosted novo, a base historica ainda nao foi importada** - por isso a lista de subcategorias aparece vazia. Ela sera populada automaticamente na primeira importacao da base historica (ou manualmente).

## 3. Problemas encontrados e corrigidos nesta revisao

1. **Lista de subcategorias invisivel quando vazia.** A tela renderizava os chips, mas sem nenhum item e sem mensagem parecia que so existia o campo de adicionar. Corrigido: contador no titulo ("Subcategorias (N)"), lista em ordem alfabetica, estado vazio explicando de onde elas vem, Enter para adicionar.
2. **Sem como remover subcategoria.** Nao havia endpoint nem botao. Adicionado `DELETE /api/v1/subcategories/<id>` (bloqueado se em uso, com auditoria) e o X em cada chip na tela.
3. **Criacao de subcategoria incompativel com Postgres em duplicidade.** `find_or_create_subcategory` tratava apenas o erro do SQLite (`sqlite3.IntegrityError`); no Postgres, uma colisao abortaria a transacao da importacao da base historica. Corrigido com `INSERT ... ON CONFLICT(name) DO NOTHING`, que funciona igual nos dois bancos (testado em concorrencia).
4. **Residuos do antigo vinculo com a base historica.** Removidos da UI: barra "Match com base historica" com slider de probabilidade, coluna "Historico" da tabela (barras de %, botao Vincular, badge vinculado, menu Desvincular) e o botao "Limpar sugestoes" do topo. No backend, o endpoint `bulk-vincular` foi desativado (retorna 409 por regra de produto), fechando o caminho tambem via API. As sugestoes de categoria/subcategoria continuam intactas - esse e o unico papel da base historica agora.

## 4. Pontos de atencao (nao alterados - decisao do dono)

1. **Lote aplica so categoria.** A classificacao em lote da tela nao permite escolher subcategoria (a API ate aceita). Facil de adicionar um segundo seletor se desejar.
2. **Sem validacao de tipo na classificacao.** Nada impede classificar uma despesa com categoria de receita: o dropdown mostra todas as categorias. Recomendado filtrar o dropdown pelo tipo do lancamento - mudanca pequena, evita erro de digitacao/clique.
3. **Cor das categorias auto-criadas.** Categorias criadas pela base historica nascem cinza (#334155). Cosmetico; editavel na tela de Categorias.
4. **Botao "Limpar classificacoes" sempre visivel no topo (admin).** Ele volta para pendente tudo que nao esta travado. Como toda classificacao agora trava, o risco pratico e baixo, mas o botao poderia migrar para uma area de administracao para reduzir chance de clique acidental.
5. **"Recalcular sugestoes" mantido.** E ele que calcula as sugestoes exibidas nos chips a partir da base historica - coerente com o novo papel dela.

## 5. Saude geral do codigo

- Backend monolitico (`app.py`, ~4200 linhas) porem organizado por blocos; a camada `db.py` isola o dialeto de banco; `auth.py` isola autenticacao/auditoria. Adequado para o porte (2 usuarios).
- Regras sensiveis (papeis, travas, deduplicacao, desativacao do vinculo) estao no backend, nao apenas na tela - nao ha como contornar pela API.
- Cobertura de testes automatizados: inexistente (heranca do projeto). Mitigado por testes manuais scriptados a cada mudanca. Se o sistema crescer, o primeiro investimento deve ser testes dos parsers de extrato/fatura, que sao o maior risco de erro silencioso.
- Arquivos originais de extrato nao persistem entre deploys no plano gratuito (dados persistem no Postgres). Ja documentado em ARQUITETURA-WEB.md.

## 6. Arquivos alterados nesta rodada

| Arquivo | Pasta | Mudanca |
|---|---|---|
| `app.py` | `backend` | bulk-vincular desativado; DELETE subcategoria; ON CONFLICT na criacao |
| `db.py` | `backend` | (ja em producao) traducao ROUND para Postgres |
| `TransactionTable.tsx` | `frontend/components/transactions` | remocao completa da UI de vinculo |
| `Topbar.tsx` | `frontend/components/layout` | remocao do botao Limpar sugestoes |
| `CategoriesPage.tsx` | `frontend/components/categories` | lista de subcategorias com contador, ordenacao, estado vazio e exclusao |
| `api.ts` | `frontend/lib` | funcao deleteSubcategory |
