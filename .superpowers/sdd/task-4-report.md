# Task 4 Report: Prompt and Agent Integration

## Status

DONE

## Files changed

- `backend/app/reasoning/langchain_agent/prompts/lead_system_prompt.py`
- `backend/app/reasoning/langchain_agent/client.py`
- `backend/tests/reasoning/test_freshness_gate.py`

## Implementation

- Added optional freshness context to the Lead Agent system prompt with explicit stale, missing, and failed conclusion boundaries.
- Loaded readiness context during the normal preflight path and passed it to the prompt template.
- Added an unavailable freshness context fallback when the preflight loader raises.
- Preserved `skip_preflight` behavior, which avoids readiness database reads.

## Tests

```bash
cd backend
.venv/bin/python -m pytest tests/reasoning/test_freshness_gate.py -q
.venv/bin/python -m pytest tests/reasoning/test_prompt_template.py tests/reasoning/test_message_builder.py -q
```

Result: PASS - 3 freshness tests and 23 nearby prompt/message-builder tests.

## Concerns

- The freshness test run retains one existing Pydantic deprecation warning from `backend/app/config.py`; it is outside this task's ownership.
