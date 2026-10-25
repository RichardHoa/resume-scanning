# 02: Review Panel in command-line evaluation

**What to build:**

The Review Panel module, built on Microsoft Agent Framework (see ADR 0002), producing Candidate Feedback as part of command-line evaluation.

- **The panel.** Three Panelists (Leadership, Domain Expertise, People & Culture) run in three waves:
  1. **Independent views:** all three Panelists write their views at the same time.
  2. **Rebuttal Round:** each Panelist reads the other two views and responds, again at the same time.
  3. **Coordinator:** merges the final views into Candidate Feedback.

  That's 7 calls in total. Temperature is 0.0 and thinking is off.
- **Request limit.** The panel's requests must not take over the GPU. Agent Framework's client sends its own HTTP requests, not through `src/providers/vllm_client.py`, so it does not take a slot from `request_slots` (ticket 01's 70-request limit) on its own.
  - Find an **official**, documented Agent Framework setting that caps the panel's requests in flight, such as a client option, a supported custom HTTP client, or documented middleware. Use it to apply the shared 70-request limit.
  - If no official setting exists, do **not** work around it: no wrapping calls in `request_slots` by hand, no monkey-patching, no private APIs. Stop and report to the developer what you checked and what you found, then wait for their decision.
- **Inputs.**
  - Panelists get the resume JSON, the evaluation report (without `retrieved_criteria` or timing fields) and the requirement text. Each turn is free text of about 400 words.
  - The Coordinator gets the report, the requirement text and the three final views, with no resume JSON. Its output is schema-enforced JSON through vLLM structured output.
- **Candidate Feedback** is stored in the report as `candidate_feedback`:
  - `status`: `ok`, `failed` or `skipped`
  - `summary`
  - `strengths`, `weaknesses`, `interview_checks`
  - `panelist_views`: the final view of each Panelist
  - `processing_time_seconds`
  - `error`, on failure

  It is written in the evaluation's `language`. The panel never writes any score, weight, recommendation or Category field.
- **Failure handling.** On any failure, the whole panel is retried once from the beginning. If it fails again, `status` is `failed` and the evaluation report is still saved. A Failed Evaluation (`status: "error"`) never reaches the panel.
- **Mock mode.** A mock variant behind the same interface returns canned Vietnamese Candidate Feedback.
- **Logging.** Every panel call is logged through the existing LLM call logger into the candidate's log folder. Coordinator schema failures go through the broken-JSON logger.
- **Wiring.**
  - Command-line evaluation generates Candidate Feedback by default, and `--no-feedback` turns it off.
  - The bias and consistency suites always run with feedback off.

Before starting, confirm the current Agent Framework Python API for an OpenAI-compatible client with a custom base URL, for structured output against vLLM, and for an official way to limit concurrent requests (see **Request limit**).

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `agent-framework` is added to the requirements
- [ ] The panel's requests in flight are capped by an official Agent Framework setting tied to the shared limit, or, if no such setting exists, the developer has been told and nothing was built to work around it
- [ ] One `scripts/pipeline/evaluate.sh` run produces reports with `candidate_feedback.status: "ok"` and all fields filled, in Vietnamese
- [ ] Rebuttal Round turns visibly respond to the other Panelists' views
- [ ] Scores, weights and recommendations are identical with feedback on and with `--no-feedback`
- [ ] A Failed Evaluation report has no `candidate_feedback`, and no panel calls are logged for it
- [ ] A panel failure is retried once, then recorded as `status: "failed"` with an `error`, and the evaluation is still saved
- [ ] Mock mode returns canned Candidate Feedback without contacting vLLM
- [ ] Every panel call appears in the candidate's log folder, and bad Coordinator JSON appears in the broken-JSON folder
- [ ] The bias and consistency suites never run the panel
- [ ] Testing is manual and done by the developer; no automated tests are added

## Comments

Implemented (uncommitted). The acceptance boxes are left for the developer's manual run.

- **Agent Framework API, checked against the agent-framework-core 1.20.0 and agent-framework-openai 1.15.0 sources:**
  - `OpenAIChatCompletionClient(model=..., async_client=AsyncOpenAI(base_url=...), middleware=[...])` is the client.
  - The Panelists and the Coordinator are `Agent(client, instructions, default_options)`.
  - A raw JSON-schema `response_format` is sent as a strict `json_schema`, which vLLM enforces with structured output.
  - Other option keys pass through to `chat.completions.create`, so `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` turns thinking off.
- **Request limit:** this uses the documented `ChatMiddleware` hook on the client. `SharedRequestLimit` in `src/pipelines/review_panel.py` holds one `vllm_client.request_slots` slot for each panel chat call. The SDK's own retries are off (`max_retries=0`), so no retry goes out without a slot. There is no monkey-patching and no private API.
- **Requirements:** `agent-framework-core` and `agent-framework-openai` were added instead of the `agent-framework` meta-package, which installs every integration.
- **Feedback switch:** `evaluate_resume(generate_feedback=True)`. Command-line evaluation has `--no-feedback`, which writes `candidate_feedback: {"status": "skipped"}`. The consistency suite passes `False`. The bias suite never calls `evaluate_resume`. The web batch passes `False` until ticket 03 wires up progress and display.
- **Logs:** each Panelist's calls go to `review_panel_<panelist>/` and the Coordinator's to `review_panel_coordinator/`. A Coordinator schema failure goes to `broken_json/review_panel_coordinator/`.
