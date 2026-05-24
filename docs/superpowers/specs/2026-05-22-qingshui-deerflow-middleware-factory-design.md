# Qingshui DeerFlow-Style Middleware Factory Design

Date: 2026-05-22

## Context

Qingshui currently uses LangGraph through LangChain `create_agent()`, but the middleware system is thin. The runtime path only injects a small set of middleware from `lead_agent.py`, while several files and documents imply a richer DeerFlow-style chain. This creates a mismatch between architecture intent and actual execution.

The goal is not to copy every DeerFlow middleware. The goal is to adopt DeerFlow's governance model: a declared runtime feature set, a fixed default ordering, deterministic extension insertion, chain validation, and tests that prove middleware is actually passed into `create_agent()`.

## Reference Findings

DeerFlow's useful patterns for Qingshui are:

- Middleware order is explicit and documented.
- `before_*` hooks run in list order; `after_*` hooks run in reverse order.
- Clarification is placed last so its `after_model` hook runs first.
- Runtime features decide which middleware and tools are enabled.
- Custom middleware can be inserted with anchor decorators.
- Chain invariants are tested instead of being trusted by comments.

Qingshui should skip DeerFlow concepts that do not fit the current investment-research runtime:

- Sandbox and uploads infrastructure.
- Vision/image injection.
- Deferred MCP tool filtering.
- Default guardrails until a concrete policy exists.

Memory, title generation, SSE bridging, and run journaling should remain lifecycle concerns in the first implementation phase. They should not be forced into LangGraph middleware unless they need to participate in the model/tool loop.

## Target Architecture

The lead-agent flow should be split into four layers:

```text
run_lead_agent()
  +-- Context preflight
  |   +-- clarification precheck
  |   +-- Qdrant pre-search
  |   +-- Neo4j graph context
  |   +-- memory context load
  |
  +-- Qingshui agent factory
  |   +-- resolve model
  |   +-- resolve tools
  |   +-- build middleware chain
  |   +-- validate middleware chain
  |   +-- create_agent(...)
  |
  +-- LangGraph agent execution
  |   +-- agent.astream(...)
  |
  +-- Lifecycle
      +-- SSE event bridge
      +-- RunJournal
      +-- title generation
      +-- memory async update
      +-- final report packaging
```

### Layer Rules

AgentMiddleware layer:
Only capabilities that should participate in the LangGraph model/tool loop belong here, such as context compression, tool error handling, subagent limiting, loop detection, and graph-time clarification interception.

Lifecycle layer:
SSE conversion, final report packaging, title generation, memory queue updates, and journal finalization stay outside the middleware chain.

Context preflight layer:
Qdrant retrieval, Neo4j graph context, memory loading, and obvious clarification prechecks happen before agent creation. These operations should not block the LangGraph event loop through synchronous middleware hooks.

Factory layer:
Agent construction should move behind a single factory that owns feature flags, default middleware order, custom insertion, validation, and tool augmentation.

## Proposed Middleware Chain

Qingshui's default LangGraph middleware chain should be:

```text
0. DynamicContextMiddleware
1. DanglingToolCallMiddleware
2. ToolErrorHandlingMiddleware
3. ContextCompressorMiddleware
4. TodoMiddleware
5. TokenUsageMiddleware
6. SubagentLimitMiddleware
7. LoopDetectionMiddleware
8. ReasoningValidationMiddleware
9. ClarificationMiddleware
```

`TodoMiddleware` is only enabled in plan mode.

`SubagentLimitMiddleware` is only enabled when subagents are enabled.

`ClarificationMiddleware` is always last when enabled.

### Middleware Responsibilities

DynamicContextMiddleware:
Inject lightweight runtime reminders, such as current date and mode. Large retrieval context remains in preflight.

DanglingToolCallMiddleware:
Repair message history where an AI tool call lacks a corresponding `ToolMessage`, preventing provider and LangGraph protocol errors.

ToolErrorHandlingMiddleware:
Wrap tool calls and convert ordinary tool exceptions into structured error `ToolMessage` values. Control-flow exceptions must not be swallowed.

ContextCompressorMiddleware:
Compress oversized message state before model calls. It should keep the current pruning behavior but become configurable and observable.

TodoMiddleware:
Track `write_todos` behavior only in plan mode. It should not add noise to ordinary investment-research chat.

TokenUsageMiddleware:
Record token usage metadata from model responses. The first version records data only and does not implement billing.

SubagentLimitMiddleware:
Truncate excessive `task` tool calls in `after_model` when the model requests more subagents than allowed.

LoopDetectionMiddleware:
Detect repeated tool-call patterns and steer the model away from loops. Repeat threshold and window size should be configurable.

ReasoningValidationMiddleware:
Keep Qingshui's investment-research quality check for unsupported assertions and missing data references. It should warn by default and not mutate output.

ClarificationMiddleware:
Handle graph-time clarification tool calls. It must be last in the list so its `after_model` hook sees model output first.

## Factory And Feature Model

Add these modules:

```text
backend/app/reasoning/langchain_agent/features.py
backend/app/reasoning/langchain_agent/middleware_chain.py
backend/app/reasoning/langchain_agent/factory.py
```

### Runtime Features

`features.py` should define `QingshuiRuntimeFeatures`:

```python
@dataclass
class QingshuiRuntimeFeatures:
    dynamic_context: bool | AgentMiddleware = True
    dangling_tool_call: bool | AgentMiddleware = True
    tool_error_handling: bool | AgentMiddleware = True
    context_compression: bool | AgentMiddleware = True
    todo: bool | AgentMiddleware = False
    token_usage: bool | AgentMiddleware = True
    subagent_limit: bool | AgentMiddleware = False
    loop_detection: bool | AgentMiddleware = True
    reasoning_validation: bool | AgentMiddleware = True
    clarification: bool | AgentMiddleware = True
    guardrail: bool | AgentMiddleware = False
```

Rules:

- `False` disables a feature.
- `True` creates the default middleware.
- An `AgentMiddleware` instance replaces the default implementation.
- `guardrail=True` is rejected until there is a default guardrail policy; a custom instance is allowed.
- Clarification, when enabled, is forced to the end of the chain.

### Runtime Data

Define `QingshuiAgentRuntime` to collect values currently scattered across function parameters and `RunnableConfig.configurable`:

```python
@dataclass
class QingshuiAgentRuntime:
    thread_id: str
    model_name: str
    plan_mode: bool = False
    subagent_enabled: bool = False
    max_concurrent_subagents: int = 3
    title_enabled: bool = True
    reasoning_validation_enabled: bool = True
    token_usage_enabled: bool = True
    context_compression_enabled: bool = True
```

### Middleware Builder

`middleware_chain.py` should expose:

```python
def build_qingshui_middlewares(
    *,
    features: QingshuiRuntimeFeatures,
    runtime: QingshuiAgentRuntime,
    extra_middlewares: list[AgentMiddleware] | None = None,
) -> list[AgentMiddleware]:
    ...
```

It should build the default chain in the fixed order, insert extras, and validate the result.

### Extension Anchors

Implement `Next(anchor)` and `Prev(anchor)` decorators:

- A custom middleware cannot use both decorators.
- Two custom middleware cannot claim conflicting insertion around the same anchor.
- Missing anchors fail fast.
- Unanchored custom middleware are inserted before `ClarificationMiddleware`.
- `ClarificationMiddleware` is moved back to the end after insertion if necessary.

### Agent Factory

`factory.py` should expose:

```python
def build_qingshui_agent(
    *,
    model,
    tools: list,
    system_prompt: str,
    config: RunnableConfig,
    runtime: QingshuiAgentRuntime,
    features: QingshuiRuntimeFeatures | None = None,
    extra_middlewares: list[AgentMiddleware] | None = None,
):
    ...
```

This function should:

- Build and validate middleware.
- Filter invalid tools.
- Add feature-driven tools when needed.
- Call `create_agent()`.
- Log the final middleware chain.

`lead_agent.py` keeps `make_lead_agent()` as a compatibility wrapper and delegates to the new factory.

## Implementation Scope

### New Files

```text
backend/app/reasoning/langchain_agent/features.py
backend/app/reasoning/langchain_agent/middleware_chain.py
backend/app/reasoning/langchain_agent/factory.py
backend/app/reasoning/langchain_agent/middlewares/dynamic_context.py
backend/app/reasoning/langchain_agent/middlewares/dangling_tool_call.py
backend/app/reasoning/langchain_agent/middlewares/tool_error_handling.py
backend/app/reasoning/langchain_agent/middlewares/token_usage.py
```

### Changed Files

```text
backend/app/reasoning/langchain_agent/lead_agent.py
backend/app/reasoning/langchain_agent/client.py
backend/app/reasoning/langchain_agent/middlewares/context_compressor.py
backend/app/reasoning/langchain_agent/middlewares/loop_detection.py
backend/app/reasoning/langchain_agent/middlewares/reasoning_validation.py
backend/app/reasoning/langchain_agent/middlewares/clarification.py
backend/app/reasoning/langchain_agent/middlewares/subagent_limit.py
backend/app/reasoning/langchain_agent/middlewares/todo_list.py
backend/app/reasoning/langchain_agent/middlewares/__init__.py
```

### Lifecycle-Only In First Phase

These should remain outside the LangGraph middleware chain initially:

- Memory queue update.
- Title generation.
- SSE event bridge.
- RunJournal finalization.
- Final report construction.

Middleware can emit structured journal events through a light helper, but it should not call API-level SSE functions directly.

## Chain Validation

Add `validate_middleware_chain(middlewares, runtime)`.

Validation rules:

- Every element is an `AgentMiddleware` instance.
- `ClarificationMiddleware` exists and is last when clarification is enabled.
- `ToolErrorHandlingMiddleware` appears before `ClarificationMiddleware`.
- `SubagentLimitMiddleware` appears only when `runtime.subagent_enabled` is true.
- `TodoMiddleware` appears only when `runtime.plan_mode` is true.
- Middleware names are unique.
- Extra middleware anchors resolve.
- Lifecycle-only components are rejected from the AgentMiddleware chain.

The factory should log a chain snapshot:

```text
[LeadAgent] middleware_chain=[
  dynamic_context,
  dangling_tool_call,
  tool_error_handling,
  context_compressor,
  token_usage,
  loop_detection,
  reasoning_validation,
  clarification
]
```

## Tests

### `test_middleware_chain.py`

Cover:

- Default chain order.
- Clarification is always last.
- `plan_mode=True` enables Todo.
- `subagent_enabled=True` enables SubagentLimit.
- Custom instance replaces default middleware.
- `@Next` insertion.
- `@Prev` insertion.
- Missing anchor failure.
- Anchor conflict failure.
- Duplicate middleware name failure.

### `test_lead_agent_factory.py`

Cover:

- `build_qingshui_agent()` passes the full middleware chain to `create_agent()`.
- Invalid tools are filtered.
- Feature flags augment tools where needed.
- Runtime configuration reaches `RunnableConfig.configurable`.
- `make_lead_agent()` remains compatible with the old entry point.

### `test_tool_error_handling.py`

Cover:

- Successful tool call passes through.
- Sync tool exception becomes `ToolMessage(status="error")`.
- Async tool exception becomes `ToolMessage(status="error")`.
- Control-flow exceptions are re-raised.
- Long traceback details are not leaked in tool-visible content.

### `test_subagent_limit_middleware.py`

Cover:

- Non-`task` tool calls are unaffected.
- Task calls within the limit pass through.
- Task calls beyond the limit are truncated.
- The first N task calls are preserved.
- The response explains which calls were truncated.
- The middleware is absent when subagents are disabled.

### `test_clarification_middleware.py`

Cover:

- The existing precheck still handles obviously vague input.
- Graph-time `clarify` or `ask_clarification` tool calls are intercepted.
- Non-clarification tool calls are unaffected.
- The chain order makes clarification's `after_model` run first.

### `test_context_compressor.py`

Cover:

- Messages below the threshold are unchanged.
- Oversized old `ToolMessage` values are pruned.
- Head and tail messages are preserved.
- Sync and async hook paths match.
- Compression is observable through logs or journal events.

## Implementation Phases

### Phase 1: Factory Skeleton

Add feature declarations, middleware builder, factory, and chain validation. Keep current middleware behavior, but route agent construction through the new factory.

Acceptance:

- Existing agent behavior remains compatible.
- Middleware chain is logged.
- Tests prove `create_agent()` receives middleware from the new factory.

### Phase 2: Stability Middleware

Add dangling tool-call repair, tool error handling, and token usage tracking. Make context compression, loop detection, and reasoning validation configurable.

Acceptance:

- Tool exceptions no longer crash the graph.
- Compression, loop detection, and token usage are covered by tests.

### Phase 3: Interaction Governance

Convert clarification and subagent limiting into real AgentMiddleware behavior. Enable todo tracking only in plan mode.

Acceptance:

- Graph-time clarification is intercepted.
- Excess subagent tool calls are truncated.
- Plan-mode todo behavior is feature-gated.

### Phase 4: Documentation Correction

Update the existing Agent architecture docs and roadmap to match the actual code.

Acceptance:

- The docs no longer claim a middleware chain is complete unless it is actually passed into `create_agent()`.
- Lifecycle-only capabilities are documented separately from AgentMiddleware.

## Compatibility Requirements

- `make_lead_agent()` remains available.
- `run_lead_agent()` response shape remains stable.
- Existing SSE event names remain stable.
- New middleware may add events or journal entries but must not rename existing API events.
- Default feature values should preserve current successful-path behavior while improving failure handling.

## Final Acceptance Criteria

- The middleware count and order passed to `create_agent()` are tested.
- Every feature flag has enable and disable tests.
- The Clarification-last invariant is tested.
- Tool errors, repeated tool calls, subagent overflow, and oversized context are tested.
- `client.py` no longer hand-assembles middleware chains.
- Documentation reflects the code path used at runtime.
