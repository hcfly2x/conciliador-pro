# Banco de dados - estado vigente

Atualizado em 22/07/2026. O DDL executavel em `core/application.py` e as
migrations em `backend/migrations` prevalecem sobre este resumo.

## Bancos suportados

- PostgreSQL hospedado quando `DATABASE_URL` esta definida.
- SQLite em `backend/data/conciliador_pro.db` para desenvolvimento/testes.
- SQL direto; nao existe ORM.

## Grupos de tabelas

| Dominio | Tabelas principais |
|---|---|
| Cadastros | `accounts`, `categories`, `subcategories`, `ledgers` |
| Financeiro | `transactions`, `installment_plans`, `transaction_reconciliations` |
| Importacao | `import_previews`, `imported_files`, `import_jobs` |
| Historico | `classification_history`, `seed_import_jobs` |
| Sugestoes | `transaction_suggestions`, `transaction_suggestion_state`, `suggestion_jobs`, `recalculation_jobs` |
| Cofre | `stored_documents`, `account_file_coverage` |
| Seguranca | `users`, `sessions`, `audit_log` |
| Operacao | `schema_migrations`, `maintenance_log` |

## Integridade implementada no codigo

- Lote inteiro bloqueado quando qualquer ocorrencia ja existe no banco.
- Repeticoes internas recebem chaves distintas e sao preservadas.
- Categoria deve existir e corresponder ao tipo receita/despesa.
- Subcategoria deve existir.
- Lancamento protegido exige desbloqueio auditado.
- Uma transacao nao pode participar de duas conciliacoes ativas.
- Uma base historica nova so substitui a anterior depois de produzir registros.

As relacoes ainda nao usam foreign keys extensivamente. Adiciona-las exige
auditoria previa de orfaos e plano explicito de `ON DELETE`.

## Dinheiro

O schema legado usa `REAL`/double precision. Valores exibidos e comparacoes
financeiras sao arredondados conforme as regras atuais, mas a migracao para
`NUMERIC` continua pendente. Antes dela, criar testes de arredondamento, auditar
valores existentes e planejar conversao reversivel.

## Migrations

`schema_migrations` registra:

- versao inteira;
- nome imutavel;
- checksum;
- data UTC de aplicacao.

O runner recusa migration desconhecida ou alterada depois de aplicada. A versao
1 marca o schema legado como baseline; a versao 2 adiciona indices das filas por
`(status, created_at)`. Novas mudancas devem receber uma nova versao e teste de
idempotencia.

## Backup

Enquanto a homologacao permite reset, backup persistente nao bloqueia releases.
Quando os dados passarem a ser preservados entre versoes, cada release deve
registrar commit + versao do schema e exigir backup restauravel antes da
migration.
