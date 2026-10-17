"""
Review Panel: three Panelists discuss one evaluated candidate and a Coordinator merges their final
views into Candidate Feedback for the HR user. Built on Microsoft Agent Framework (see
docs/adr/0002-agent-framework-only-for-review-panel.md); every other LLM call stays on vllm_client.

The panel reads the evaluation report but never writes any score, weight, recommendation or Category field.
"""
import asyncio
import sys
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from agent_framework import Agent, ChatContext, ChatMiddleware
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI

from src.core.config import (
    VLLM_REQUEST_TIMEOUT, REVIEW_PANEL_TEMPERATURE, REVIEW_PANEL_PANELIST_MAX_TOKENS,
    REVIEW_PANEL_COORDINATOR_MAX_TOKENS, REVIEW_PANEL_MAX_ATTEMPTS
)
from src.core.json_utils import clean_and_parse_json
from src.core.logger import log_llm_call, log_broken_json
from src.pipelines.evaluator_mocks import get_mock_candidate_feedback
from src.pipelines.evaluator_utils import strip_identity
from src.prompts.review_panel_prompts import (
    PANELISTS,
    COORDINATOR_SCHEMA,
    get_panelist_system_prompt,
    get_panelist_view_prompt,
    get_rebuttal_prompt,
    get_coordinator_system_prompt,
    get_coordinator_prompt
)
from src.providers.vllm_client import request_slots, record_usage

# Thinking is off for every panel call, whatever the model profile says
_NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}

# Report fields Panelists and the Coordinator don't need; dropped to fit the context window. The candidate's
# name, email and resume file name are dropped too, so no LLM call on the panel sees who the candidate is
_REPORT_FIELDS_DROPPED = (
    "execution_timings", "evaluated_at", "standard_requirements", "hidden_requirements",
    "resume_path", "language", "hidden_requirements_assessment", "candidate_feedback",
    "candidate_identifier", "candidate_name", "candidate_email", "resume_name",
    # Only a candidate who passed the Must-have gate reaches the panel, so its Must-have Rejection is empty; reports
    # from before the gate carry a "missing_must_haves" the decomposer's Importance produced, which HR never chose
    "must_have_rejection", "missing_must_haves"
)
_DIMENSION_FIELDS_DROPPED = ("retrieved_criteria", "processing_time_seconds", "must_have_no_evidence_counts")

COORDINATOR_LOG_CATEGORY = "review_panel_coordinator"


class SharedRequestLimit(ChatMiddleware):
    """
    Holds one of vllm_client's process-wide request slots for each chat call the panel makes, so the
    panel and Category evaluation together never exceed the shared limit on requests in flight.
    """
    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        # The slots are a threading semaphore shared with synchronous callers; wait for one off the event loop
        await asyncio.to_thread(request_slots.acquire)
        try:
            await call_next()
        finally:
            request_slots.release()


def _panel_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """The evaluation report as the panel sees it: no retrieved criteria, timings or duplicated text."""
    stripped = {k: v for k, v in report.items() if k not in _REPORT_FIELDS_DROPPED}
    stripped["dimension_scores"] = {
        key: {k: v for k, v in dim.items() if k not in _DIMENSION_FIELDS_DROPPED}
        for key, dim in (report.get("dimension_scores") or {}).items()
    }
    return stripped


def _panel_resume(resume: Dict[str, Any]) -> Dict[str, Any]:
    """The resume as the panel sees it: without basic_information, which only identifies the candidate."""
    return strip_identity(resume)


def _full_prompt(system_prompt: str, prompt: str) -> str:
    """The prompt as the LLM call loggers record it, in the same layout as the evaluator's calls."""
    return f"--- SYSTEM PROMPT ---\n{system_prompt}\n\n--- USER PROMPT ---\n{prompt}"


def _validate_coordinator_output(parsed: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(parsed, dict):
        return None
    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    result = {"summary": summary.strip()}
    for field in ("strengths", "weaknesses"):
        items = parsed.get(field)
        if not isinstance(items, list):
            return None
        items = [i.strip() for i in items if isinstance(i, str) and i.strip()]
        if not items:
            return None
        result[field] = items
    return result


async def _run_wave(calls: Dict[str, Awaitable[str]]) -> Dict[str, str]:
    """
    Runs one wave of calls at once. Waits for every call before raising the first failure, so no call is
    cancelled while it waits for or holds a request slot.
    """
    results = await asyncio.gather(*calls.values(), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return dict(zip(calls.keys(), results))


class ReviewPanel:
    """Runs the Review Panel against the vLLM server."""

    def __init__(self, vllm_url: str, model_name: str):
        self.vllm_url = vllm_url
        self.model_name = model_name

    def review(
        self,
        report: Dict[str, Any],
        resume: Dict[str, Any],
        standard_req: str,
        hidden_req: str,
        language: str = "vietnamese",
        resume_name: str = "candidate",
        log_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Returns Candidate Feedback for one successfully evaluated candidate: `status: "ok"` with every field
        filled, or `status: "failed"` with an `error` once the panel has failed twice. Never raises.
        """
        start = time.time()
        error = ""
        for attempt in range(1, REVIEW_PANEL_MAX_ATTEMPTS + 1):
            try:
                feedback = asyncio.run(self._discuss(
                    _panel_report(report), _panel_resume(resume), standard_req or "", hidden_req or "", language, resume_name, log_dir, attempt
                ))
                return {"status": "ok", **feedback, "processing_time_seconds": round(time.time() - start, 2)}
            except Exception as e:
                error = f"{type(e).__name__}: {e}"[:500]
                print(f"[Review Panel] Attempt {attempt}/{REVIEW_PANEL_MAX_ATTEMPTS} for '{resume_name}' failed: {error}", file=sys.stderr)
        return {"status": "failed", "error": error, "processing_time_seconds": round(time.time() - start, 2)}

    async def _discuss(
        self,
        report: Dict[str, Any],
        resume: Dict[str, Any],
        standard_req: str,
        hidden_req: str,
        language: str,
        resume_name: str,
        log_dir: Optional[str],
        attempt: int
    ) -> Dict[str, Any]:
        # A fresh OpenAI client per run: its connection pool is bound to this run's event loop.
        # Retries are the panel's own (the whole panel, once), so the SDK does not retry on its own
        async with AsyncOpenAI(
            base_url=self.vllm_url, api_key="EMPTY", timeout=VLLM_REQUEST_TIMEOUT, max_retries=0
        ) as openai_client:
            client = OpenAIChatCompletionClient(
                model=self.model_name, async_client=openai_client, middleware=[SharedRequestLimit()]
            )
            panelist_options = {
                "temperature": REVIEW_PANEL_TEMPERATURE,
                "max_tokens": REVIEW_PANEL_PANELIST_MAX_TOKENS,
                "extra_body": _NO_THINKING
            }
            panelist_system_prompts = {key: get_panelist_system_prompt(key, language) for key in PANELISTS}
            panelists = {
                key: Agent(client=client, instructions=system_prompt, default_options=panelist_options)
                for key, system_prompt in panelist_system_prompts.items()
            }
            coordinator_system_prompt = get_coordinator_system_prompt(language)
            coordinator = Agent(
                client=client,
                instructions=coordinator_system_prompt,
                default_options={
                    "temperature": REVIEW_PANEL_TEMPERATURE,
                    "max_tokens": REVIEW_PANEL_COORDINATOR_MAX_TOKENS,
                    # Schema-enforced by vLLM structured output
                    "response_format": {**COORDINATOR_SCHEMA, "title": "candidate_feedback"},
                    "extra_body": _NO_THINKING
                }
            )

            async def ask(agent: Agent, system_prompt: str, prompt: str, category: str) -> str:
                full_prompt = _full_prompt(system_prompt, prompt)
                try:
                    response = await agent.run(prompt)
                except Exception as e:
                    log_llm_call(full_prompt, f"[REQUEST FAILED] {type(e).__name__}: {e}", category, resume_name, log_dir=log_dir)
                    raise
                usage = response.usage_details or {}
                max_tokens = REVIEW_PANEL_COORDINATOR_MAX_TOKENS if category == COORDINATOR_LOG_CATEGORY else REVIEW_PANEL_PANELIST_MAX_TOKENS
                record_usage(category, usage.get("input_token_count"), usage.get("output_token_count"), response.finish_reason, max_tokens, resume_name)
                text = response.text.strip()
                log_llm_call(full_prompt, text, category, resume_name, log_dir=log_dir)
                if not text:
                    raise RuntimeError(f"Empty response for {category}")
                return text

            # 1. Independent views
            views = await _run_wave({
                key: ask(agent, panelist_system_prompts[key], get_panelist_view_prompt(resume, report, standard_req, hidden_req), f"review_panel_{key}")
                for key, agent in panelists.items()
            })
            # 2. Rebuttal Round: each Panelist reads the other two views and gives its final view
            final_views = await _run_wave({
                key: ask(agent, panelist_system_prompts[key], get_rebuttal_prompt(key, resume, report, standard_req, hidden_req, views), f"review_panel_{key}")
                for key, agent in panelists.items()
            })
            # 3. Coordinator: merges the final views; sees no resume JSON
            coordinator_prompt = get_coordinator_prompt(report, standard_req, hidden_req, final_views)
            raw = await ask(coordinator, coordinator_system_prompt, coordinator_prompt, COORDINATOR_LOG_CATEGORY)

        feedback = _validate_coordinator_output(clean_and_parse_json(raw))
        if feedback is None:
            log_broken_json(
                _full_prompt(coordinator_system_prompt, coordinator_prompt), raw, COORDINATOR_LOG_CATEGORY, resume_name, attempt=attempt,
                error_reason="Coordinator output does not match the Candidate Feedback schema", log_dir=log_dir
            )
            raise ValueError("Coordinator output does not match the Candidate Feedback schema")
        return {**feedback, "panelist_views": final_views}


class MockReviewPanel:
    """Same interface as ReviewPanel; returns canned Vietnamese Candidate Feedback without contacting vLLM."""

    def review(
        self,
        report: Dict[str, Any],
        resume: Dict[str, Any],
        standard_req: str,
        hidden_req: str,
        language: str = "vietnamese",
        resume_name: str = "candidate",
        log_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        return {"status": "ok", **get_mock_candidate_feedback(), "processing_time_seconds": 0.0}


def create_review_panel(mock: bool, vllm_url: str, model_name: str):
    return MockReviewPanel() if mock else ReviewPanel(vllm_url, model_name)
