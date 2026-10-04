import os
from functools import lru_cache
from typing import Sequence

from pydantic import SecretStr
from langchain_ibm import ChatWatsonx

# Overridable so the evaluation suite can measure a different model without
# editing code. The default is the model the deployment actually runs.
DEFAULT_MODEL_ID = "mistralai/mistral-small-3-1-24b-instruct-2503"
DEFAULT_URL = "https://eu-gb.ml.cloud.ibm.com"

# Output token ceilings per task. Each is sized to the longest reply that task
# should produce, so a long query is never cut short. A ceiling costs nothing
# unless it is used.
_MAX_TOKENS = {
    "planner": 300,
    "sql": 400,
    "chat": 350,
    "summary": 150,
}

# The planner must reply with JSON. The chat API can enforce that, which
# removes a whole class of failure: in testing it made no difference to
# accuracy and none to latency, so there is no reason not to.
_RESPONSE_FORMAT = {
    "planner": {"type": "json_object"},
}

# A message as LangChain accepts it: (role, text), role being "system", "user"
# or "assistant".
Message = tuple[str, str]


def _model_id(task: str) -> str:
    """
    Resolve the model for a task: a per-task override, then the global one,
    then the default. Per-task overrides let the evaluation suite measure a
    larger model on one step without changing the others.
    """
    per_task = os.environ.get(f"WATSONX_MODEL_ID_{task.upper()}", "").strip()
    return per_task or os.environ.get("WATSONX_MODEL_ID", "").strip() or DEFAULT_MODEL_ID


# Cached because building a client per request is pure overhead: the
# credentials and endpoint do not change while the process runs.
@lru_cache(maxsize=None)
def _build(task: str, model_id: str) -> ChatWatsonx:
    return ChatWatsonx(
        model_id=model_id,
        url=SecretStr(os.environ.get("WATSONX_URL", "").strip() or DEFAULT_URL),
        project_id=os.environ.get("PROJECT_ID", "").strip(),
        api_key=SecretStr(os.environ.get("IBM_API_KEY", "").strip()),
        # The chat API has no "greedy" decoding mode; temperature 0 is its
        # equivalent, and the evaluation suite depends on repeatable output.
        temperature=0,
        max_completion_tokens=_MAX_TOKENS[task],
        response_format=_RESPONSE_FORMAT.get(task),
    )


def create_llm(task: str = "sql", model_id: str | None = None) -> ChatWatsonx:
    """
    Return the chat client configured for a task.

    A single entry point rather than one factory per task, because it is the
    seam the tests and the evaluation harness patch. Defaulting to "sql" keeps
    every existing caller working unchanged.
    """
    if task not in _MAX_TOKENS:
        raise ValueError(f"Unknown LLM task {task!r}; expected one of {sorted(_MAX_TOKENS)}")
    return _build(task, model_id or _model_id(task))


def complete(llm, messages: Sequence[Message]) -> str:
    """
    Send messages to a chat model and return its reply as text.

    The only place that knows a chat model answers with a message object
    rather than a string, so every caller deals in plain text.
    """
    return str(llm.invoke(list(messages)).content).strip()
