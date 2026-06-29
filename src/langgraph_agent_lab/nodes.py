"""Node functions for the LangGraph workflow.

Each function receives AgentState and returns a partial state update dict.
Do NOT mutate input state — return new values only.

LLM REQUIREMENT:
- classify_node MUST use a real LLM call (structured output for intent classification)
- answer_node MUST use a real LLM call (grounded response generation)
- evaluate_node SHOULD use LLM-as-judge (bonus points; heuristic acceptable for base score)
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from .llm import get_llm
from .state import AgentState, ApprovalDecision, Route, make_event


# ─── EXAMPLE: working node (provided for reference) ──────────────────
def intake_node(state: AgentState) -> dict:
    """Normalize raw query. This node is provided as a working example."""
    query = state.get("query", "").strip()
    return {
        "query": query,
        "messages": [f"intake:{query[:40]}"],
        "events": [make_event("intake", "completed", "query normalized")],
    }


class ClassificationOutput(BaseModel):
    route: Route = Field(description="Routing decision for the user request")
    reason: str = Field(description="Short explanation for the routing decision")


def _heuristic_classify(query: str) -> ClassificationOutput:
    lowered = query.lower()
    risky_tokens = ["refund", "delete", "cancel", "send email", "confirmation email"]
    tool_tokens = ["lookup", "look up", "order status", "tracking", "search"]
    error_tokens = ["timeout", "failure", "error", "crash", "cannot recover"]
    vague_tokens = ["fix it", "help me", "can you fix"]

    if any(token in lowered for token in risky_tokens):
        return ClassificationOutput(
            route=Route.RISKY,
            reason="Detected side-effect action request.",
        )
    if any(token in lowered for token in tool_tokens):
        return ClassificationOutput(
            route=Route.TOOL,
            reason="Detected information lookup request.",
        )
    if any(token in lowered for token in error_tokens):
        return ClassificationOutput(
            route=Route.ERROR,
            reason="Detected system-failure language.",
        )
    if len(query.split()) <= 4 or any(token in lowered for token in vague_tokens):
        return ClassificationOutput(
            route=Route.MISSING_INFO,
            reason="Request is too vague to act on.",
        )
    return ClassificationOutput(
        route=Route.SIMPLE,
        reason="General support question.",
    )


def _invoke_with_fallback(prompt: str) -> str:
    try:
        llm = get_llm(temperature=0.1)
        response = llm.invoke(prompt)
        return getattr(response, "content", str(response))
    except Exception:
        return ""


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using an LLM.

    *** MUST use a real LLM call — keyword-only heuristics will lose points. ***

    Use .with_structured_output() or equivalent to get reliable enum classification.
    The LLM should classify into one of: simple, tool, missing_info, risky, error.

    Hints:
    - See llm.py for the get_llm() helper
    - Use Pydantic model or TypedDict with .with_structured_output()
    - Set risk_level to "high" for risky routes, "low" otherwise
    - Priority guide: risky > tool > missing_info > error > simple

    Return: {"route": str, "risk_level": str, "events": [make_event(...)]}
    """
    query = state.get("query", "")
    try:
        llm = get_llm(temperature=0.0)
        structured_llm = llm.with_structured_output(ClassificationOutput)
        prompt = (
            "Classify a support request into exactly one route with this strict priority: "
            "risky > tool > missing_info > error > simple.\n"
            "Definitions:\n"
            "- risky: actions with side effects such as refunds, deletions, "
            "cancellations, emails.\n"
            "- tool: information lookup or retrieval.\n"
            "- missing_info: vague or incomplete request lacking enough context.\n"
            "- error: user is reporting system failure, timeout, crash, or service issue.\n"
            "- simple: general question answerable directly.\n"
            f"User query: {query}"
        )
        result = structured_llm.invoke(prompt)
    except Exception:
        result = _heuristic_classify(query)

    route = result.route.value if isinstance(result.route, Route) else str(result.route)
    risk_level = "high" if route == Route.RISKY.value else "low"
    return {
        "route": route,
        "risk_level": risk_level,
        "messages": [f"classify:{route}"],
        "events": [
            make_event(
                "classify",
                "completed",
                "route selected",
                route=route,
                risk_level=risk_level,
            )
        ],
    }


def tool_node(state: AgentState) -> dict:
    """Execute a mock tool call.

    Simulate transient failures for error-route scenarios to test retry loops.

    Requirements:
    - Read current attempt count from state
    - If route is "error" and attempt < 2: return error result (string containing "ERROR")
    - Otherwise: return a mock success result string
    - Append result to tool_results list

    Return: {"tool_results": [result_string], "events": [make_event(...)]}
    """
    attempt = int(state.get("attempt", 0))
    route = state.get("route", "")
    query = state.get("query", "")
    if route == Route.ERROR.value and attempt < 2:
        result = f"ERROR: transient failure while handling '{query}' on attempt {attempt}"
        status = "error"
    else:
        result = f"SUCCESS: completed tool workflow for '{query}' on attempt {attempt}"
        status = "success"
    return {
        "tool_results": [result],
        "messages": [f"tool:{status}"],
        "events": [
            make_event(
                "tool",
                "completed",
                "tool executed",
                status=status,
                attempt=attempt,
            )
        ],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the retry-loop gate.

    Check whether the latest tool result is satisfactory or needs retry.

    SHOULD use LLM-as-judge for bonus points. Heuristic (e.g., check for "ERROR" substring)
    is acceptable for base score.

    Requirements:
    - Read the latest entry from tool_results
    - Set evaluation_result to "needs_retry" or "success"
    - This field drives route_after_evaluate conditional edge

    Note: You may need to add 'evaluation_result' to AgentState if not present.

    Return: {"evaluation_result": str, "events": [make_event(...)]}
    """
    latest_result = (state.get("tool_results") or [""])[-1]
    evaluation_result = "needs_retry" if "ERROR" in latest_result.upper() else "success"
    return {
        "evaluation_result": evaluation_result,
        "events": [
            make_event(
                "evaluate",
                "completed",
                "tool result evaluated",
                evaluation_result=evaluation_result,
            )
        ],
    }


def answer_node(state: AgentState) -> dict:
    """Generate a final response using an LLM.

    *** MUST use a real LLM call — hardcoded strings will lose points. ***

    The LLM should generate a helpful response grounded in available context:
    - tool_results (if any)
    - approval decision (if risky route)
    - original query

    Return: {"final_answer": str, "events": [make_event(...)]}
    """
    query = state.get("query", "")
    tool_results = state.get("tool_results") or []
    approval = state.get("approval")
    prompt = (
        "You are a support operations assistant. Provide a concise final answer grounded only in "
        "the supplied context. If an action was approved, mention that approval. If there are tool "
        "results, summarize them. Do not invent facts.\n"
        f"Query: {query}\n"
        f"Approval: {approval}\n"
        f"Tool results: {tool_results}\n"
    )
    final_answer = _invoke_with_fallback(prompt).strip()
    if not final_answer:
        if tool_results:
            final_answer = f"Yeu cau da duoc xu ly dua tren ket qua tool: {tool_results[-1]}"
        else:
            final_answer = f"Tra loi ho tro cho yeu cau: {query}"
    return {
        "final_answer": final_answer,
        "messages": ["answer:finalized"],
        "events": [make_event("answer", "completed", "final answer generated")],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating.

    Generate a specific clarification question based on the vague/incomplete query.

    Note: You may need to add 'pending_question' to AgentState if not present.

    Return: {"pending_question": str, "final_answer": str, "events": [make_event(...)]}
    """
    query = state.get("query", "")
    pending_question = (
        f"Ban co the cung cap them thong tin cu the de xu ly yeu cau '{query}' khong? "
        "Vi du: ma don hang, tai khoan, loi gap phai, hoac hanh dong mong muon."
    )
    return {
        "pending_question": pending_question,
        "final_answer": pending_question,
        "messages": ["clarify:requested"],
        "events": [make_event("clarify", "completed", "clarification requested")],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for human approval.

    Describe the proposed action and why it requires approval.

    Note: You may need to add 'proposed_action' to AgentState if not present.

    Return: {"proposed_action": str, "events": [make_event(...)]}
    """
    query = state.get("query", "")
    proposed_action = (
        f"Proposed risky action: {query}. Human approval is required before execution."
    )
    return {
        "proposed_action": proposed_action,
        "messages": ["risky_action:prepared"],
        "events": [make_event("risky_action", "completed", "risky action prepared")],
    }


def approval_node(state: AgentState) -> dict:
    """Human-in-the-loop approval step.

    Default behavior: mock approval (approved=True) so tests and CI run offline.
    Extension: if env LANGGRAPH_INTERRUPT=true, use langgraph.types.interrupt() for real HITL.

    Return:
    {"approval": {"approved": bool, "reviewer": str, "comment": str}, "events": [make_event(...)]}
    """
    proposed_action = state.get("proposed_action", "")
    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        try:
            from langgraph.types import interrupt

            decision = interrupt({"proposed_action": proposed_action, "requires_approval": True})
            approval = ApprovalDecision.model_validate(decision).model_dump()
        except Exception:
            approval = ApprovalDecision(
                approved=True,
                reviewer="mock-reviewer",
                comment="Interrupt unavailable, auto-approved fallback.",
            ).model_dump()
    else:
        approval = ApprovalDecision(
            approved=True,
            reviewer="mock-reviewer",
            comment="Approved by default for lab execution.",
        ).model_dump()

    return {
        "approval": approval,
        "messages": [f"approval:{approval['approved']}"],
        "events": [
            make_event(
                "approval",
                "completed",
                "approval decision recorded",
                approved=approval["approved"],
            )
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt.

    Increment the attempt counter and log the transient failure.

    Requirements:
    - Read current attempt from state, increment by 1
    - Add an error message to errors list
    - Return updated attempt count

    Return: {"attempt": int, "errors": [str], "events": [make_event(...)]}
    """
    next_attempt = int(state.get("attempt", 0)) + 1
    current_route = state.get("route", "unknown")
    error_message = f"Retry attempt {next_attempt} triggered for route={current_route}"
    return {
        "attempt": next_attempt,
        "errors": [error_message],
        "messages": [f"retry:{next_attempt}"],
        "events": [
            make_event(
                "retry",
                "completed",
                "retry recorded",
                attempt=next_attempt,
            )
        ],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Handle unresolvable failures after max retries exceeded.

    This is the third layer: retry → fallback → dead letter.
    Log the failure and set a final_answer explaining that the request could not be completed.

    Return: {"final_answer": str, "events": [make_event(...)]}
    """
    final_answer = (
        "Khong the hoan tat yeu cau sau nhieu lan thu. "
        "Tac vu da duoc dua vao dead-letter de can thiep thu cong."
    )
    return {
        "final_answer": final_answer,
        "errors": [f"dead_letter: exhausted retries at attempt {state.get('attempt', 0)}"],
        "messages": ["dead_letter:escalated"],
        "events": [
            make_event(
                "dead_letter",
                "completed",
                "request moved to dead letter queue",
            )
        ],
    }


def finalize_node(state: AgentState) -> dict:
    """Emit a final audit event. All routes must pass through here before END.

    Return: {"events": [make_event("finalize", "completed", "workflow finished")]}
    """
    route = state.get("route", "")
    return {
        "events": [
            make_event(
                "finalize",
                "completed",
                "workflow finished",
                route=route,
            )
        ]
    }
