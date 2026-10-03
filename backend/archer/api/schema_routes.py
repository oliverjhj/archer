import sqlite3
import logging

from fastapi import APIRouter, Depends, Request

from ..auth.jwt import get_current_user
from ..core.limiter import limiter
from ..db.database import TABLE_NAME, database_path

router = APIRouter()

# The descriptions live in archer.db.catalogue, shared with the prompts. The
# tests import them from here.
from ..db.catalogue import COLUMN_DESCRIPTIONS, COMMON_COLUMNS, KNOWN_VALUES  # noqa: E402,F401


@router.get("/api/schema")
@limiter.limit("30/minute")
async def get_schema(request: Request, username: str = Depends(get_current_user)):
    """
    Describe the dataset a visitor is querying.

    A demo where the user cannot see the column names is a guessing game, and
    the questions people invent when guessing are the ones that come back
    empty. This is read straight from the database rather than from a hardcoded
    list, so it cannot drift from what is actually there.
    """
    conn = None
    try:
        conn = sqlite3.connect(f"file:{database_path()}?mode=ro", uri=True)
        cursor = conn.cursor()

        columns = [
            {
                "name": row[1],
                "type": row[2] or "TEXT",
                "common": row[1] in COMMON_COLUMNS,
                "description": COLUMN_DESCRIPTIONS.get(row[1], ""),
            }
            for row in cursor.execute(f"PRAGMA table_info({TABLE_NAME})")
        ]
        rows = cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
        date_from, date_to = cursor.execute(
            f"SELECT MIN(document_date), MAX(document_date) FROM {TABLE_NAME}"
        ).fetchone()

        return {
            "table": TABLE_NAME,
            "row_count": rows,
            "date_from": date_from,
            "date_to": date_to,
            "columns": columns,
            "known_values": KNOWN_VALUES,
        }
    except sqlite3.Error as exc:
        logging.error("Could not read schema: %s", exc)
        return {"table": TABLE_NAME, "row_count": 0, "columns": [], "known_values": {}}
    finally:
        if conn:
            conn.close()
