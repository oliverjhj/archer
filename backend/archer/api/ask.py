import asyncio
import os
import sqlite3
import re
import logging
from typing import Union, List
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from pydantic import BaseModel

from ..ai.llm import create_llm
from ..ai.classifier import classify_query
from ..ai.sql_generator import generate_sql
from ..ai.chat import generate_chat_response
from ..auth.jwt import get_current_user
from ..core.limiter import limiter
from ..core.usage import budget, BUDGET_EXHAUSTED_MESSAGE
from ..db.database import database_path, schema_columns
from ..db.query import run_select

router = APIRouter()

class AskRequest(BaseModel):
    question: Union[str, List[str]]

async def answer_question(question: Union[str, List[str]]) -> dict:
    """
    Shared question-answering orchestration.

    Both entry points call this and nothing duplicates it:
      - POST /ask      authenticated by the x-api-key webhook secret
      - POST /api/ask  authenticated by the browser session cookie

    Authentication is deliberately the caller's job. This function assumes the
    caller is already authorised and performs no auth of its own.
    """
    # A list is joined rather than passed through: str() of a list would hand
    # the model "['a', 'b']", brackets and quotes included.
    user_query = " ".join(question) if isinstance(question, list) else question

    # No escaping. Braces used to be doubled here, which made every question
    # containing one fail: the prompt renderer mistook them for unfilled
    # placeholders. Substitution is a single pass that never re-reads what a
    # user typed, and generated SQL is executed only through run_select, so
    # the protection lives where it can be enforced rather than in the text.

    clean_sql = "N/A - General Conversation"

    # Claim budget before calling the model, because asking is what costs. The
    # per-IP rate limiter on the routes stops one visitor hammering the demo;
    # this stops the aggregate, which is the part that reaches a bill.
    if not budget.try_consume():
        logging.warning("Refused a question: daily budget exhausted (%s)", budget.snapshot())
        return {"answer": BUDGET_EXHAUSTED_MESSAGE}

    try:
        logging.info(f"User Query: {user_query}")

        # The watsonx SDK is synchronous. Calling it directly from an async
        # handler blocks the event loop for the whole round trip - seconds,
        # under which nothing else on the process is served. asyncio.to_thread
        # moves it to a worker thread so concurrent requests are unaffected.
        route_decision = await asyncio.to_thread(
            classify_query, create_llm("classifier"), user_query
        )

        # --- ROUTE A: DATA QUERY (SQL Generation) ---
        if route_decision == "1":
            db_path = database_path()
            if not os.path.exists(db_path):
                logging.error("Database file not found at %s - the image was built incorrectly", db_path)
                return {"answer": "Database temporarily unavailable. Please contact support."}

            schema_text = ", ".join(schema_columns())

            clean_sql, generated_response = await asyncio.to_thread(
                generate_sql, create_llm("sql"), user_query, schema_text
            )

            if not clean_sql:
                return {"answer": f"I couldn't generate a valid SQL query. (AI said: {generated_response})"}

            # Defence in depth: run_select refuses anything else too, but
            # this keeps the clearer message for the obvious case.
            if not re.match(r"^\s*(SELECT|WITH)\b", clean_sql, re.IGNORECASE):
                logging.error(f"Non-SELECT query blocked: {clean_sql}")
                return {"answer": "I can only execute SELECT queries for security reasons."}

            # The only execution path for generated SQL: read-only, an
            # authorizer limiting it to reading sales_data, a deadline and
            # a row cap. See archer.db.query.
            result = await asyncio.to_thread(run_select, clean_sql)
            db_result = result.rows
            returned_columns = result.columns

            # --- THE FORMATTING FIXES ---

            # 1. THE TRUNCATION WARNING FIX
            truncated_msg = ""
            if result.truncated:
                truncated_msg = "\n\n*(Note: Displaying the maximum of 100 rows to maintain performance.)*"

            if not db_result or len(db_result) == 0 or db_result is None:
                clean_answer = f"I couldn't find any data matching that request. \n\n*(Query attempted: {clean_sql})*"
                
            # 2. THE SINGLE VALUE DECIMAL FIX
            elif len(db_result) == 1 and len(db_result[0]) == 1:
                final_value = db_result[0][0]
                col_name = returned_columns[0].lower()
                
                if 'revenue' in col_name and isinstance(final_value, (int, float)):
                    final_value = f"£{final_value:,.2f}"
                elif isinstance(final_value, (int, float)):
                    if final_value == int(final_value):
                        final_value = f"{int(final_value):,}"
                    else:
                        final_value = f"{final_value:,.2f}"
                        
                clean_answer = f"Based on the data, the answer is: **{final_value}** \n\n*(SQL used: {clean_sql})*"
                
            # 3. THE TABLE QUANTITY DECIMAL FIX
            else:
                table_md = f"| {' | '.join(returned_columns)} |\n"
                table_md += f"|{'|'.join(['---'] * len(returned_columns))}|\n"
                for row in db_result:
                    formatted_row = []
                    for col_idx, val in enumerate(row):
                        col_name = returned_columns[col_idx].lower()
                        
                        if 'revenue' in col_name and isinstance(val, (int, float)):
                            formatted_row.append(f"£{val:,.2f}")
                        elif 'quantity' in col_name and isinstance(val, (int, float)):
                            formatted_row.append(f"{int(val):,}")
                        elif isinstance(val, (int, float)):
                            if val == int(val):
                                formatted_row.append(f"{int(val):,}")
                            else:
                                formatted_row.append(f"{val:,.2f}")
                        else:
                            clean_text = str(val).replace('\n', ', ').replace('\r', '')
                            formatted_row.append(clean_text)
                            
                    table_md += f"| {' | '.join(formatted_row)} |\n"
                clean_answer = f"Here is the data you requested:\n\n{table_md}{truncated_msg}\n*(SQL used: {clean_sql})*"
                
            return {"answer": clean_answer}

        # --- ROUTE B: GENERAL CHAT (Persona Injected) ---
        else:
            chat_response = await asyncio.to_thread(
                generate_chat_response, create_llm("chat"), user_query
            )
            return {"answer": chat_response}
            
    # Issue #6: Narrow exception handling to catch only operational errors
    except (sqlite3.Error, ValueError, KeyError, AttributeError) as e:
        # Silently record the exact crash in the server logs
        logging.error(f"CRITICAL DB ERROR: {str(e)} | SQL ATTEMPTED: {clean_sql}")
        
        # Maintain the polite user-facing UI response
        clean_answer = f"I understood you need data, but I had trouble running that specific query against the database. Could you try rephrasing your question with slightly different terms?"
        return {"answer": clean_answer}


@router.post("/ask")
@limiter.limit("20/minute")
async def ask_ai(request: Request, payload: AskRequest, x_api_key: str = Header(None)):
    """
    Webhook entry point, authenticated by a shared secret header.

    Behaviour is unchanged from before the /api/ask proxy was added.
    """
    expected_secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not expected_secret or x_api_key != expected_secret:
        raise HTTPException(status_code=401, detail="Unauthorised: Invalid or missing API Key")

    return await answer_question(payload.question)


@router.post("/api/ask")
@limiter.limit("20/minute")
async def ask_ai_authenticated(
    request: Request,
    payload: AskRequest,
    username: str = Depends(get_current_user),
):
    """
    Browser entry point for the React frontend.

    Authenticated by the session cookie rather than the webhook secret, so the
    browser never needs WEBHOOK_SECRET. The secret stays server-side and is
    never sent to, or required by, frontend code.

    get_current_user raises 401 when the cookie is missing, invalid or expired.
    The application converts a 401 on an /api/ path into a JSON response rather
    than the redirect-to-login used for page routes - see archer/app.py.
    """
    return await answer_question(payload.question)

