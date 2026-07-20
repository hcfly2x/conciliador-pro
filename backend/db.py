"""Camada de banco de dados dual: Postgres hosted (producao) ou SQLite (dev local).

Uso:
    from db import db_connect, IS_POSTGRES

    with db_connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()

- Se a variavel de ambiente DATABASE_URL estiver definida (postgres://...),
  usa Postgres via psycopg3.
- Caso contrario, usa o SQLite local em backend/data/conciliador_pro.db.

O wrapper Postgres imita a API do sqlite3 usada pelo app:
- placeholders `?` sao convertidos para `%s` (com escape de `%` literais)
- IFNULL(  -> COALESCE(
- PRAGMA table_info(x) -> information_schema (retorna linhas com nome na posicao 1)
- REAL -> DOUBLE PRECISION em DDL (evita perda de centavos no float4)
- linhas retornadas aceitam indice numerico E chave por nome (como sqlite3.Row)
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("CONCILIADOR_DATA_DIR") or BASE / "data").resolve()
# Testes E2E podem isolar completamente o SQLite sem tocar no banco local.
DB_PATH = (DATA / "conciliador_pro.db").resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

if IS_POSTGRES:
    import psycopg  # type: ignore
    from psycopg_pool import ConnectionPool  # type: ignore

    # Neon/Heroku usam postgres:// ; psycopg aceita postgresql://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

    # Pool de conexoes: abrir uma conexao nova a cada requisicao custa ~0,5-1s
    # quando banco e backend estao em regioes diferentes (TLS + auth a cada vez).
    # O pool reutiliza conexoes ja abertas. prepare_threshold=None evita bugs com
    # poolers (Supavisor/pgbouncer). max_idle recicla conexoes ociosas antes que
    # o pooler as derrube.
    _POOL = None
    _POOL_PID = None

    def _get_pool():
        """Cria o pool sob demanda, por processo (seguro com fork do gunicorn)."""
        global _POOL, _POOL_PID
        pid = os.getpid()
        if _POOL is None or _POOL_PID != pid:
            _POOL = ConnectionPool(
                DATABASE_URL,
                min_size=0,
                max_size=int(os.environ.get("DB_POOL_MAX", "10")),
                max_idle=120,
                # check: testa a conexao antes de entregar; descarta conexoes que o
                # pooler do Supabase tenha derrubado (evita 500 apos ociosidade).
                check=ConnectionPool.check_connection,
                kwargs={"prepare_threshold": None},
                open=True,
            )
            _POOL_PID = pid
        return _POOL


def _make_row_class(fields: tuple[str, ...]):
    index_map = {name: i for i, name in enumerate(fields)}

    class _Row(tuple):
        __slots__ = ()
        _fields = fields

        def __getitem__(self, key):
            if isinstance(key, str):
                return tuple.__getitem__(self, index_map[key])
            return tuple.__getitem__(self, key)

        def keys(self):
            return list(fields)

        def get(self, key, default=None):
            try:
                return self[key]
            except (KeyError, IndexError):
                return default

    return _Row


_PRAGMA_TABLE_INFO = re.compile(r"^\s*PRAGMA\s+table_info\(\s*([A-Za-z0-9_]+)\s*\)\s*$", re.IGNORECASE)
_IFNULL = re.compile(r"\bIFNULL\s*\(", re.IGNORECASE)
_COLLATE_NOCASE = re.compile(r"\bCOLLATE\s+NOCASE\b", re.IGNORECASE)
_DDL_START = re.compile(r"^\s*(CREATE|ALTER)\b", re.IGNORECASE)
_REAL = re.compile(r"\bREAL\b", re.IGNORECASE)
# ROUND(x, n) no Postgres exige NUMERIC (nao aceita double precision).
_ROUND = re.compile(r"\bROUND\(\s*([^,()]+?)\s*,", re.IGNORECASE)
_PLACEHOLDER_SENTINEL = "\x00PH\x00"


def _translate_pg(sql: str, has_params: bool) -> str:
    m = _PRAGMA_TABLE_INFO.match(sql)
    if m:
        table = m.group(1).lower()
        # Mesma forma do sqlite: (cid, name, type, notnull, dflt_value, pk)
        return (
            "SELECT ordinal_position - 1, column_name, data_type, "
            "CASE WHEN is_nullable='NO' THEN 1 ELSE 0 END, column_default, 0 "
            "FROM information_schema.columns "
            f"WHERE table_name = '{table}' ORDER BY ordinal_position"
        )
    sql = _IFNULL.sub("COALESCE(", sql)
    sql = _COLLATE_NOCASE.sub("", sql)
    sql = _ROUND.sub(r"ROUND(CAST(\1 AS NUMERIC),", sql)
    if _DDL_START.match(sql):
        sql = _REAL.sub("DOUBLE PRECISION", sql)
    if has_params:
        # protege % literais (LIKE '%x%') antes de converter ? -> %s
        sql = sql.replace("?", _PLACEHOLDER_SENTINEL)
        sql = sql.replace("%", "%%")
        sql = sql.replace(_PLACEHOLDER_SENTINEL, "%s")
    return sql


class _PgCursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rowcount = cursor.rowcount

    def _wrap_rows(self, rows):
        if not rows or self._cursor.description is None:
            return rows
        fields = tuple(d.name for d in self._cursor.description)
        row_cls = _make_row_class(fields)
        return [row_cls(r) for r in rows]

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None or self._cursor.description is None:
            return row
        fields = tuple(d.name for d in self._cursor.description)
        return _make_row_class(fields)(row)

    def fetchall(self):
        return self._wrap_rows(self._cursor.fetchall())

    def fetchmany(self, size: int = 100):
        return self._wrap_rows(self._cursor.fetchmany(size))


class _PgConnection:
    """Imita a interface minima de sqlite3.Connection usada pelo app."""

    def __init__(self, conn, pooled: bool = False):
        self._conn = conn
        self._pooled = pooled
        self.row_factory = None  # compat: atribuicoes sao ignoradas (chaves sempre disponiveis)

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> _PgCursor:
        params_t = tuple(params) if params is not None else None
        has_params = bool(params_t)
        translated = _translate_pg(sql, has_params)
        cur = self._conn.cursor()
        if has_params:
            cur.execute(translated, params_t)
        else:
            cur.execute(translated)
        return _PgCursor(cur)

    def executemany(self, sql: str, seq_of_params) -> _PgCursor:
        translated = _translate_pg(sql, True)
        cur = self._conn.cursor()
        cur.executemany(translated, [tuple(p) for p in seq_of_params])
        return _PgCursor(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if self._pooled:
            try:
                self._conn.rollback()
            except Exception:
                pass
            _get_pool().putconn(self._conn)
        else:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            if self._pooled:
                _get_pool().putconn(self._conn)
            else:
                self._conn.close()
        return False


class _SqliteConnection(sqlite3.Connection):
    """Connection SQLite que fecha deterministicamente ao sair do `with`."""

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


def db_connect(direct: bool = False):
    """Obtem uma conexao (do pool no Postgres). Usar como context manager.

    direct=True abre uma conexao dedicada fora do pool (ex.: advisory locks na
    inicializacao, que nao devem voltar para o pool carregando o lock).
    """
    if IS_POSTGRES:
        if direct:
            return _PgConnection(psycopg.connect(DATABASE_URL, prepare_threshold=None), pooled=False)
        try:
            return _PgConnection(_get_pool().getconn(timeout=15), pooled=True)
        except Exception:
            # Resiliencia: se o pool falhar por qualquer motivo, abre conexao direta.
            return _PgConnection(psycopg.connect(DATABASE_URL, prepare_threshold=None), pooled=False)
    DATA.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH, factory=_SqliteConnection)
