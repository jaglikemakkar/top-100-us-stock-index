# app/db.py
import duckdb
from .config import settings


def get_connection() -> duckdb.DuckDBPyConnection:
    # DuckDB is file-based; for simple assignment a single connection per request is fine
    conn = duckdb.connect(settings.duckdb_path, read_only=False)
    return conn
