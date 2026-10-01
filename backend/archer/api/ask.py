import logging
import os
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth.jwt import get_current_user
from ..core.limiter import limiter
from ..core.usage import BUDGET_EXHAUSTED_MESSAGE, budget
from ..pipeline import HistoryTurn, budget_turn, format_legacy, run_turn

router = APIRouter()

MAX_QUESTION_LENGTH = 2000


class AskRequest(BaseModel):
    question: Union[str, List[str]]
    # Earlier exchanges, as the server returned them in each turn's "memory"
    # and the browser sends back. Optional, so /ask callers that send only a
    # question are unaffected. These limits reject abuse; the pipeline trims
    # what it actually uses much further.
    history: List[HistoryTurn] = Field(default_factory=list, max_length=6)


async def answer_question(
    question: Union[str, List[str]], history: Optional[List[HistoryTurn]] = None
) -> dict:
    """
    Shared question-answering orchestration.

    Both entry points call this and nothing duplicates it:
      - POST /ask      authenticated by the x-api-key webhook secret
      - POST /api/ask  authenticated by the browser session cookie

    Authentication is deliberately the caller's job. This function assumes the
    caller is already authorised and performs no auth of its own.

    Returns {"answer": <Markdown>, "turn": <structured record>}. The answer
    string is what /ask has always returned; the turn is what the React app
    renders. Both come from the same run, so they cannot disagree.
    """
    # A list is joined rather than passed through: str() of a list would hand
    # the model "['a', 'b']", brackets and quotes included.
    user_query = " ".join(question) if isinstance(question, list) else question

    # Claim budget before calling the model, because asking is what costs. The
    # per-IP rate limiter on the routes stops one visitor hammering the demo;
    # this stops the aggregate, which is the part that reaches a bill.
    if not budget.try_consume():
        logging.warning("Refused a question: daily budget exhausted (%s)", budget.snapshot())
        turn = budget_turn(user_query, BUDGET_EXHAUSTED_MESSAGE)
        return {"answer": BUDGET_EXHAUSTED_MESSAGE, "turn": turn.model_dump()}

    if len(user_query) > MAX_QUESTION_LENGTH:
        raise HTTPException(status_code=422, detail="Question is too long.")

    logging.info("User Query: %s (history: %d items)", user_query, len(history or []))
    turn = await run_turn(user_query, history)
    return {"answer": format_legacy(turn), "turn": turn.model_dump()}


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

    return await answer_question(payload.question, payload.history)


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
    return await answer_question(payload.question, payload.history)

