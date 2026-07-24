# Registro de releases

O registro nao substitui o historico do Git. Ele associa a revisao publicada ao
schema e ao modo operacional que preservam os dados de producao.

| Data | Commit | Schema | Backend | Executor de jobs | Evidencia |
|---|---|---:|---|---|---|
| 24/07/2026 | `86150c5` | 3 (health confirmado) | Render/PostgreSQL | `inline` no web | Classificação em lote passa a confirmar se itens já classificados devem ser incluídos; inclusão exige admin e é auditada. Health respondeu commit `86150c5fc422`. |
| 23/07/2026 | `a71e446` | 3 (health confirmado) | Render/PostgreSQL | `inline` no web | Candidatos de conciliação completos e paginados; health respondeu `a71e4462c778`. |
| 23/07/2026 | `fabafb6` | 2 (confirmado pelo health) | Render/PostgreSQL | `inline` no web | CI completo verde; exportacao XLSX em streaming e compatibilidade do cursor PostgreSQL; download de auditoria confirmado em producao pelo proprietario |
| 22/07/2026 | `e73adfd` | 2 (runner; confirmacao publica pendente) | Render/PostgreSQL | `inline` no web | CI verde, health 200, 40 requests concorrentes, importacao e vinculo em lote confirmados pelo proprietario |
| 22/07/2026 | `d4699b2` | 2 (confirmado pelo health) | Render/PostgreSQL | `inline` no web | CI completo verde, Vercel 200, health 200 e processamento de vinculos em blocos de 10 |
| 22/07/2026 | `c853b14` | 2 (confirmado pelo health) | Render/PostgreSQL | `inline` no web | CI completo verde; vinculo em lote com limiar de 75%, progresso visual e persistencia homologados pelo proprietario |

Antes da proxima migration, registrar aqui a evidencia de backup verificavel e
da restauracao homologada. O Supabase Free atual nao fornece essa garantia.

## Backups de producao

- 22/07/2026, antes da release seguinte a `e73adfd`: backup local
  `production-postgresql-20260722-125039.zip`, gerado em transacao PostgreSQL
  `REPEATABLE READ` somente leitura; 24 tabelas e 17.004 registros validados.
- SHA-256: `2a949a761a848996e80dbcbe45f4ffc1b7d86144f759dbcd20f9a934e45a5101`.
- O ZIP e seu arquivo `.sha256` ficam somente em `backend/data/backups/`, fora
  do Git. A restauracao em banco descartavel permanece pendente.
