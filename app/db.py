import sqlite3
from pathlib import Path

from app.core.config import settings


def get_connection() -> sqlite3.Connection:
    database_path = settings.database_file_path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    settings.storage_dir_path.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).with_name("schema.sql")
    with get_connection() as connection:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        _ensure_media_job_columns(connection)


def _ensure_media_job_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(media_jobs)").fetchall()
    }
    if "result_md5" not in columns:
        connection.execute("ALTER TABLE media_jobs ADD COLUMN result_md5 TEXT")
