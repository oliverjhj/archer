"""
Unit tests for multi-part messages and clarifying questions.

The planner is patched to return a chosen plan; data parts run against the
same mocked SQL path as the other pipeline tests.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from archer.ai.planner import MAX_OPTIONS, Clarification, Plan, PlannedPart, parse_plan
from archer.pipeline import CLIPPED_NOTICE, Part, format_legacy, run_turn


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mixed_plan_is_parsed() -> None:
    plan = parse_plan(
        '{"kind": "mixed", "parts": [{"kind": "data", "question": "Revenue in 2025?"},'
        ' {"kind": "chat", "question": "What is IBM SERV?"}]}'
    )
    assert plan.kind == "mixed"
    assert [p.kind for p in plan.parts] == ["data", "chat"]
    assert plan.requested_parts == 2


@pytest.mark.unit
def test_clarify_plan_is_parsed_and_options_capped() -> None:
    options = ", ".join(f'"Option {i}?"' for i in range(6))
    plan = parse_plan(
        f'{{"kind": "clarify", "parts": [], "clarification": {{"question": "Which one?", "options": [{options}]}}}}'
    )
    assert plan.kind == "clarify"
    assert len(plan.clarification.options) == MAX_OPTIONS


@pytest.mark.unit
def test_clarify_without_a_question_is_rejected() -> None:
    assert parse_plan('{"kind": "clarify", "parts": []}') is None


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def _turn(plan, question="q", data_parts=None, chat_reply="IBM SERV is services."):
    """Run a turn with the planner, the data path and the chat path patched."""
    data = MagicMock(side_effect=data_parts or [])
    chat = MagicMock(return_value=chat_reply)

    async def fake_data(question, trace=None):
        return data(question)

    with (
        patch("archer.pipeline.create_llm", return_value=MagicMock()),
        patch("archer.pipeline.plan_message", return_value=plan),
        patch("archer.pipeline.run_data_part", side_effect=fake_data),
        patch("archer.pipeline.generate_chat_response", chat),
    ):
        turn = asyncio.run(run_turn(question))
    return turn, data, chat


def _data_part(question, value="£1,000.00"):
    return Part(type="data", question=question, text="Based on the data, the answer is:", sql="SELECT 1", value=value, rows=[[value]], columns=["x"])


@pytest.mark.unit
def test_a_mixed_message_answers_each_part_in_order() -> None:
    plan = Plan(
        kind="mixed",
        parts=[PlannedPart(kind="data", question="Revenue in 2025?"), PlannedPart(kind="chat", question="What is IBM SERV?")],
        requested_parts=2,
    )
    turn, data, chat = _turn(plan, "Revenue in 2025, and what is IBM SERV?", [_data_part("Revenue in 2025?")])

    assert turn.kind == "mixed"
    assert [p.type for p in turn.parts] == ["data", "chat"]
    assert turn.interpreted_as is None
    legacy = format_legacy(turn)
    assert legacy.startswith("**1. Revenue in 2025?**")
    assert "**2. What is IBM SERV?**\n\nIBM SERV is services." in legacy


@pytest.mark.unit
def test_two_data_parts_make_a_data_turn() -> None:
    plan = Plan(kind="data", parts=[PlannedPart(kind="data", question="A?"), PlannedPart(kind="data", question="B?")], requested_parts=2)
    turn, data, _ = _turn(plan, "A and B?", [_data_part("A?", "1"), _data_part("B?", "2")])
    assert turn.kind == "data"
    assert data.call_count == 2


@pytest.mark.unit
def test_one_failing_part_does_not_sink_the_others() -> None:
    failed = Part(type="data", question="B?", status="sql_error", text="I understood you need data...")
    plan = Plan(kind="data", parts=[PlannedPart(kind="data", question="A?"), PlannedPart(kind="data", question="B?")], requested_parts=2)
    turn, _, _ = _turn(plan, "A and B?", [_data_part("A?"), failed])
    assert turn.kind == "data"
    assert [p.status for p in turn.parts] == ["ok", "sql_error"]


@pytest.mark.unit
def test_extra_parts_are_noted() -> None:
    plan = Plan(kind="data", parts=[PlannedPart(kind="data", question=f"Q{i}?") for i in range(3)], requested_parts=4)
    turn, _, _ = _turn(plan, "four things", [_data_part(f"Q{i}?") for i in range(3)])
    assert turn.notice == CLIPPED_NOTICE
    assert format_legacy(turn).endswith(f"*(Note: {CLIPPED_NOTICE})*")


@pytest.mark.unit
def test_a_clarifying_question_runs_no_query() -> None:
    plan = Plan(kind="clarify", clarification=Clarification(question="The second what?", options=["Second partner?", "Second product?"]))
    turn, data, chat = _turn(plan, "What about the second one?")

    assert turn.kind == "clarify"
    assert turn.parts[0].type == "clarify"
    assert turn.parts[0].options == ["Second partner?", "Second product?"]
    data.assert_not_called()
    chat.assert_not_called()
    assert format_legacy(turn) == "The second what?\n- Second partner?\n- Second product?"


@pytest.mark.unit
def test_the_clarifying_question_is_remembered_with_its_options() -> None:
    plan = Plan(kind="clarify", clarification=Clarification(question="The second what?", options=["Second partner?"]))
    turn, _, _ = _turn(plan, "What about the second one?")
    assert "The second what?" in turn.memory.answer
    assert "Second partner?" in turn.memory.answer


@pytest.mark.unit
def test_history_keeps_the_last_table_of_a_multi_part_answer() -> None:
    first = Part(type="data", question="A?", text="Here is the data you requested:", sql="SELECT a", columns=["a"], rows=[["1"], ["2"]])
    second = Part(type="data", question="B?", text="Here is the data you requested:", sql="SELECT b", columns=["b"], rows=[["3"], ["4"]])
    plan = Plan(kind="data", parts=[PlannedPart(kind="data", question="A?"), PlannedPart(kind="data", question="B?")], requested_parts=2)
    turn, _, _ = _turn(plan, "A and B?", [first, second])
    assert turn.memory.sql == "SELECT b"
    assert turn.memory.rows == [["3"], ["4"]]


@pytest.mark.unit
def test_a_clarifying_question_for_a_clear_message_is_overruled() -> None:
    plan = Plan(kind="clarify", clarification=Clarification(question="Partners or end users?", options=["Partners?"]))
    turn, data, _ = _turn(plan, "Show me the top 5 customers by revenue", [_data_part("Show me the top 5 customers by revenue")])
    assert turn.kind == "data"
    assert data.call_args.args[0] == "Show me the top 5 customers by revenue"
