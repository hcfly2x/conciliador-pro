# Snapshot de producao - 15/07/2026

Registro anterior a publicacao do hardening prioritario. Nenhuma credencial nem
dado financeiro foi adicionado ao repositorio.

## Aplicacao publicada

- Vercel, ambiente `Production`: commit
  `07274b792c948e48730f79ef70ba11795f22b894`.
- Render, servico `conciliador-pro`: commit
  `07274b792c948e48730f79ef70ba11795f22b894`.
- O endpoint de saude do Render informou PostgreSQL conectado e o mesmo prefixo
  de commit (`07274b792c94`).
- O preflight CORS de producao aceitou exclusivamente a origem
  `https://conciliador-pro-snowy.vercel.app`.

## Banco e backup

- Banco: Supabase PostgreSQL 17.6.
- Schema `public`: 18 tabelas, exportadas junto com 4.050 registros.
- Data UTC do snapshot: `2026-07-15T18:21:48+00:00`.
- O backup foi extraido em diretorio temporario e todos os hashes do manifesto
  foram recalculados com sucesso.
- SHA-256 de `schema.sql`:
  `0e4be55f374c2af6764e26832ca9e93f058bd72921ac9577490b346008a3a69f`.
- SHA-256 do manifesto:
  `152aed04a46a66ff4d180818b2e182fce74fb34cb21d4d49a4ab446049f48939`.
- SHA-256 do ZIP local:
  `4e811ef452ee600c5410a7c5c821d182e50b88da9056d1ccecd0b76d981a6d08`.

O artefato com dados permanece somente em
`backend/data/uploads/backups/conciliador-prod-20260715-152148.zip`, caminho
ignorado pelo Git. A URL temporaria do banco foi removida depois da exportacao.

O plano Free do Supabase nao disponibiliza backups agendados no painel; este
snapshot logico e a salvaguarda anterior a qualquer migration.
