import os
import sqlite3
import logging
from functools import lru_cache

# The database lives beside the running application: the repository root when
# run locally, /app inside the container. This matches the path that
# archer.api.ask resolves when it opens a read-only connection.
DB_FILENAME = os.getenv("DB_FILE_NAME", "sales.db").strip() or "sales.db"


def database_path() -> str:
    """Absolute path to the SQLite database."""
    return os.path.abspath(DB_FILENAME)


def verify_database() -> bool:
    """
    Verify the bundled SQLite database is present and usable.

    The dataset is static, synthetic and about 45MB, so it is baked into the
    container image at build time rather than fetched at startup. That removes
    a network call, a set of credentials and an entire class of startup
    failure from the critical path, and it means a cold start is not paying
    for a 45MB download - which matters because the deployment scales to zero.

    This replaces the previous download-from-object-storage step. The contract
    with the application is unchanged: return True when the database is ready,
    False when the application must not start.

    Returns:
        bool: True if the database exists and contains the expected table.
    """
    local_db_path = database_path()

    if not os.path.exists(local_db_path):
        logging.critical(
            "Database not found at %s. It is copied into the image at build "
            "time; a missing file means the image was built incorrectly.",
            local_db_path,
        )
        return False

    file_size = os.path.getsize(local_db_path)
    if file_size == 0:
        logging.critical("Database at %s is empty.", local_db_path)
        return False

    # Validate it is genuinely a SQLite database with the expected schema,
    # rather than trusting the filename. A truncated or wrong file would
    # otherwise fail later, per request, instead of once at startup.
    try:
        conn = sqlite3.connect(f"file:{local_db_path}?mode=ro", uri=True)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sales_data'"
            )
            if cursor.fetchone() is None:
                logging.critical(
                    "Database validation failed: sales_data table not found in %s",
                    local_db_path,
                )
                return False
        finally:
            conn.close()
    except sqlite3.Error as e:
        logging.critical(
            "File at %s is not a valid SQLite database: %s", local_db_path, str(e)
        )
        return False

    logging.info(
        "Database ready: %s (%s bytes)", local_db_path, format(file_size, ",")
    )
    return True


def schema_columns() -> tuple[str, ...]:
    """
    The column names of sales_data, in table order.

    Read on its own connection, because the connection that runs generated SQL
    refuses PRAGMA by design. Not cached: it takes well under a millisecond,
    and an uncached read cannot go stale when tests point the path elsewhere.
    """
    conn = sqlite3.connect(f"file:{database_path()}?mode=ro", uri=True)
    try:
        return tuple(row[1] for row in conn.execute("PRAGMA table_info(sales_data)"))
    finally:
        conn.close()


@lru_cache(maxsize=1)
def dataset_date_range() -> tuple[str, str]:
    """
    The first and last document date in the dataset.

    The conversational prompt tells users what period it can answer for. That
    used to be a hardcoded string, which is the kind of detail that is right
    on the day it is written and quietly wrong forever after. Reading it from
    the data means it cannot drift.

    Cached: the dataset is read-only and baked into the image, so this is
    answered once per process. Falls back to empty strings rather than raising,
    because a conversational reply is not worth failing a request over.
    """
    try:
        conn = sqlite3.connect(f"file:{database_path()}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT MIN(document_date), MAX(document_date) FROM sales_data"
            ).fetchone()
        finally:
            conn.close()
        return (row[0] or "", row[1] or "")
    except sqlite3.Error as exc:
        logging.warning("Could not read dataset date range: %s", exc)
        return ("", "")
