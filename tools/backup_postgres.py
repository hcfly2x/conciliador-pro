from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import psycopg
from psycopg import sql


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_row_count(path: Path) -> int:
    field_limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(field_limit)
            break
        except OverflowError:
            field_limit //= 10
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.reader(handle)
        next(rows, None)
        return sum(1 for _ in rows)


def build_schema(conn, tables: list[str]) -> tuple[str, list[str], list[str]]:
    statements = ["BEGIN;", "CREATE SCHEMA IF NOT EXISTS public;"]
    deferred_constraints: list[str] = []
    indexes: list[str] = []

    with conn.cursor() as cur:
        for table in tables:
            cur.execute(
                """
                SELECT a.attname,
                       pg_catalog.format_type(a.atttypid, a.atttypmod),
                       a.attnotnull,
                       pg_get_expr(ad.adbin, ad.adrelid)
                FROM pg_attribute a
                JOIN pg_class c ON c.oid=a.attrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                LEFT JOIN pg_attrdef ad ON ad.adrelid=a.attrelid AND ad.adnum=a.attnum
                WHERE n.nspname='public' AND c.relname=%s
                  AND a.attnum>0 AND NOT a.attisdropped
                ORDER BY a.attnum
                """,
                (table,),
            )
            columns = []
            for name, data_type, not_null, default in cur.fetchall():
                definition = f"  {quote_identifier(name)} {data_type}"
                if default is not None:
                    definition += f" DEFAULT {default}"
                if not_null:
                    definition += " NOT NULL"
                columns.append(definition)

            cur.execute(
                """
                SELECT conname, contype, pg_get_constraintdef(oid, true)
                FROM pg_constraint
                WHERE conrelid=%s::regclass
                ORDER BY conname
                """,
                (f"public.{quote_identifier(table)}",),
            )
            for constraint_name, constraint_type, definition in cur.fetchall():
                constraint_sql = (
                    f"ALTER TABLE public.{quote_identifier(table)} ADD CONSTRAINT "
                    f"{quote_identifier(constraint_name)} {definition};"
                )
                if constraint_type == "f":
                    deferred_constraints.append(constraint_sql)
                else:
                    columns.append(f"  CONSTRAINT {quote_identifier(constraint_name)} {definition}")

            statements.append(
                f"CREATE TABLE public.{quote_identifier(table)} (\n" + ",\n".join(columns) + "\n);"
            )

            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes i
                WHERE i.schemaname='public' AND i.tablename=%s
                  AND NOT EXISTS (
                    SELECT 1 FROM pg_constraint c
                    WHERE c.conname=i.indexname AND c.conrelid=%s::regclass
                  )
                ORDER BY indexname
                """,
                (table, f"public.{quote_identifier(table)}"),
            )
            indexes.extend(f"{definition};" for _, definition in cur.fetchall())

    statements.append("COMMIT;")
    return "\n\n".join(statements) + "\n", deferred_constraints, indexes


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera backup logico verificavel do PostgreSQL de producao.")
    parser.add_argument("--database-url-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    database_url = args.database_url_file.read_text(encoding="utf-8").strip()
    if not database_url.startswith(("postgres://", "postgresql://")):
        raise SystemExit("Arquivo nao contem uma URL PostgreSQL valida")

    output_dir = args.output_dir.resolve()
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=False)

    manifest: dict[str, object] = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "format": "conciliador-logical-backup-v1",
        "schema": "public",
        "tables": [],
    }

    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version(), current_database()")
            server_version, database_name = cur.fetchone()
            manifest["server_version"] = server_version
            manifest["database_name"] = database_name
            cur.execute(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relkind='r'
                ORDER BY c.relname
                """
            )
            tables = [row[0] for row in cur.fetchall()]

        schema_text, foreign_keys, indexes = build_schema(conn, tables)
        (output_dir / "schema.sql").write_text(schema_text, encoding="utf-8", newline="\n")

        restore_lines = ["\\set ON_ERROR_STOP on", "\\i schema.sql", "BEGIN;"]
        for table in tables:
            csv_path = data_dir / f"{table}.csv"
            copy_query = sql.SQL("COPY {}.{} TO STDOUT WITH (FORMAT CSV, HEADER TRUE)").format(
                sql.Identifier("public"), sql.Identifier(table)
            )
            with conn.cursor() as cur, csv_path.open("wb") as handle:
                with cur.copy(copy_query) as copy:
                    for block in copy:
                        handle.write(bytes(block))

            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.{}").format(sql.Identifier("public"), sql.Identifier(table)))
                expected_rows = int(cur.fetchone()[0])
            actual_rows = csv_row_count(csv_path)
            if actual_rows != expected_rows:
                raise RuntimeError(f"Contagem divergente em {table}: banco={expected_rows}, backup={actual_rows}")

            relative_csv = f"data/{table}.csv"
            restore_lines.append(
                f"\\copy public.{quote_identifier(table)} FROM '{relative_csv}' WITH (FORMAT CSV, HEADER TRUE);"
            )
            manifest["tables"].append({
                "name": table,
                "rows": actual_rows,
                "file": relative_csv,
                "bytes": csv_path.stat().st_size,
                "sha256": file_sha256(csv_path),
            })

        restore_lines.extend(["COMMIT;", *foreign_keys, *indexes])
        (output_dir / "restore.sql").write_text("\n".join(restore_lines) + "\n", encoding="utf-8", newline="\n")
        conn.rollback()

    for filename in ("schema.sql", "restore.sql"):
        path = output_dir / filename
        manifest[f"{filename}_sha256"] = file_sha256(path)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    print(json.dumps({
        "output_dir": str(output_dir),
        "tables": len(manifest["tables"]),
        "rows": sum(int(item["rows"]) for item in manifest["tables"]),
        "manifest_sha256": file_sha256(manifest_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
