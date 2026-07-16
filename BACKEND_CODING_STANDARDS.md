# Backend Coding Standards

## 1. Project Basics

- Language: Python 3.11+ syntax; verified with Python 3.12.10.
- Frameworks: FastAPI for HTTP, LangGraph for explicit state workflows, OpenAI Agents SDK for the SDK comparison, and MCP SDK for protocol labs.
- Dependency management: project-local `.venv` with direct versions locked in `backend/requirements-m2.txt`.
- Layers: `domain` owns stable types, `stores` owns persistence protocols and adapters, `models` owns model adapters, `tools` owns tool contracts, `knowledge` owns retrieval, `memory` owns memory policies, `services` owns use cases, `agent` owns orchestration, `observability` owns run summaries, and `evals` owns offline behavior checks.

## 2. Naming

- Files, functions and variables use `snake_case`.
- Classes and dataclasses use `PascalCase`.
- Constants use `UPPER_SNAKE_CASE`.
- Event names use dot-separated lowercase values such as `tool.started`.

## 3. Layering

- Domain modules do not import adapters or orchestration.
- Model adapters implement the domain model protocol.
- Tools do not depend on Agent orchestration.
- Agent orchestration coordinates abstractions and does not contain business-specific tool logic.

## 4. Data Layer

- M1–M3 use immutable dataclasses and explicit in-memory adapters.
- Storage implementations expose narrow interfaces so pgvector or database adapters can be added without changing orchestration.
- Store semantics use stable application exceptions. Database-driver errors must not cross the Store boundary.
- Application-owned knowledge uses reserved identifiers that arbitrary document-write APIs must not replace.

## 5. API Conventions

- Routes use `/api` prefixes except infrastructure endpoints such as `/health`.
- Pydantic models validate request and response bodies; HTTP handlers delegate to services.
- Missing resources return 404 and invalid request bodies use FastAPI's 422 response.
- Authenticated sessions bind to the server-resolved principal. Anonymous sessions use a high-entropy per-session capability token; only its digest is stored, and every run/stream/read path rechecks it.

## 6. Business and Error Handling

- Expected tool failures return structured `ToolResult` values.
- Programmer errors are not silently swallowed.
- Agent loops enforce an explicit maximum step count.
- Secrets are read from environment variables and never logged or committed.

## 7. Comments and Style

- Use four-space indentation and type annotations on public functions.
- Docstrings explain public contracts or non-obvious boundaries, not line-by-line behavior.
- Prefer focused modules and deterministic tests.

## 8. Prohibited Patterns

- No hidden network call in tests.
- No dependency introduction before its teaching milestone.
- No provider-specific response object outside a model adapter.
- No arbitrary `eval`, shell execution, unrestricted file access or embedded secret.
- No broad exception handler that discards the original failure.

## 9. Observability and Evaluation

- Every observed run uses one stable `run_id` across the service record, API response and observation.
- Default logs use an explicit field allowlist. Prompts, answers, tool arguments and raw exception text are not logged.
- Raw error details may exist in deterministic in-process evaluation objects, but a log or external API must choose fields explicitly.
- Mock evaluation is deterministic and network-free. Real-model evaluation is opt-in and must report its provider, model, usage and cost source.
- Missing usage data remains unknown; it must not be reported as zero.

## 10. Tool Security

- The application constructs `ToolExecutionContext` from authenticated state and stored approvals; model-generated arguments never supply identity, roles or approval.
- Authorization and approval checks run before argument validation and handler execution.
- High-risk or side-effecting tools always require explicit approval, even if a caller attempts to disable the flag.
- Approval is bound to principal, tool call id, tool name and canonical argument digest, then consumed exactly once.
- Tool definitions are filtered by trusted roles before they are shown to a model; execution repeats authorization regardless of model visibility.
- A denied tool call returns a structured error and must not execute the handler.
- Cancellation is cooperative and checked before model/tool boundaries. Synchronous handlers are not described as hard-cancellable.
- Client disconnect waits only for a short bounded grace period; a background thread may finish afterward and its result must be consumed without exposing raw errors.
- Only explicitly classified transient model errors receive a bounded retry; side-effect tools are never blindly retried.

## 11. Advanced-Agent Safety

- Advanced inputs and model outputs are untrusted data. They can propose only declared actions and never construct identity, policy, workspace roots or approval state.
- Code actions resolve against one server-fixed workspace. Writes require an exact canonical path approval and use atomic replacement; deletes and arbitrary shell strings are unsupported.
- Check commands use server-owned argv, environment, cwd, timeout and output limits with `shell=False`. The default child environment is empty.
- Browser plans use HTTPS exact-origin and stable server-owned element IDs. Execution revalidates compiled plans, and click/type/submit consume exact single-use approvals.
- The multimodal lab validates PNG signature and IHDR metadata only. Visual text remains explicitly untrusted and cannot authorize actions.
- Shared action and byte limits require positive integers and fail before a bounded result is returned. Application policy is defense in depth, not an OS sandbox.

## 12. Configuration and Composition

- Application configuration is an immutable `Settings` snapshot created by explicit `from_environment()` parsing. The application does not silently load `.env` files.
- Runtime (`manual`, `agents_sdk`, `langgraph`) and model provider (`mock`, `openai`) are separate choices. A key or model name never enables online access by itself.
- Provider secrets use `SecretStr` and are excluded from normal dumps, representations, safe summaries, errors, and logs.
- Run, model, tool, MCP, and database timeouts or retries use separately scoped names. Only explicitly classified transient model errors use `max_model_retries`; side effects never inherit that policy.
- Token and cost settings are per-run cumulative upper bounds. Request values may narrow server policy but never raise a server-owned limit.
- `ApplicationContainer` is the composition root, not a service locator. FastAPI routes continue to close over narrow dependencies, and tests may inject explicit adapters.
- A complete Container and legacy `create_app()` dependency overrides are two alternative assembly paths and must not be mixed.

## 13. Durable Run and Store Contracts

- `backend.app.domain.run.RunRecord` is the M8+ durable domain snapshot. `backend.app.services.run_service.RunRecord` remains the legacy synchronous HTTP/SSE record after M8-T3; code that must reference the latter aliases it as `LegacyRunRecord`. M12 owns the unified API migration.
- Legacy `run_service` and new `run_store` / `event_store` coexist in the Container without dual writes. M8-T3 exposes the durable path programmatically through `run_coordinator`; old routes remain isolated. New Stores are injected as a pair, and an explicit EventStore validates ownership against the matching RunStore.
- Run creation scopes idempotency to `(owner_id, idempotency_key_digest)`. A versioned canonical request digest distinguishes a safe replay from a conflicting request, and the raw key is never retained.
- Run transitions use a monotonically increasing `version` compare-and-set. Terminal states never transition again, including to themselves.
- Event IDs are caller-generated stable IDs. The Store assigns per-Run sequence and UTC time; same ID plus same content replays the original event, while changed content is a stable conflict.
- Event data and tool data accept bounded standard JSON only: finite numbers, string keys, at most 64,000 encoded bytes, bounded depth and bounded node count. Stores copy nested data on write and every return.
- Heartbeats are transport events and never consume a business event sequence. Consumers rely on unique increasing sequence values; they do not sort by timestamps.
- `UsageRecord` describes exactly one model call. Unknown cost remains `None`; persisted currency uses `Decimal`, never a float conversion.
- Side-effecting `ToolExecution` records require an idempotency digest at creation. Raw arguments and raw results are not retained; safe summaries and digests are bounded.
- Logs use `safe_summary()` or an explicit allowlist. `repr=False` is defense in depth and does not authorize `dataclasses.asdict()` on records containing content.
- In-memory Store locks are single-event-loop and single-process only. The fixed nested order is Run lock before Event lock; code must never acquire them in reverse.
- The shared Store contract tests are adapter-independent. PostgreSQL fixtures inherit the same contract instead of copying it.
- Lifecycle start must use `commit_start()` and terminal settlement must use `commit_terminal()`. Ordinary `append()` rejects `run.started`, `run.completed`, `run.failed` and `run.cancelled`; Coordinator code must never simulate a lifecycle transaction with separate `transition()` and `append()` calls.
- The in-memory lifecycle commit holds the Run lock before the Event lock and mutates both snapshots in one critical section. PostgreSQL must implement the same Protocol with one database transaction; the in-memory proof is not a multi-process or restart proof.

## 14. Runtime and Coordination Contracts

- `AgentRuntime` is async and SDK-independent. Its request, control, progress event and result types must not expose provider response objects through application layers.
- Runtime owns model/tool/workflow execution and non-lifecycle progress only. `RunCoordinator` uniquely owns lifecycle events, Runtime selection, singleflight, cancellation arbitration and execution deadlines.
- `RuntimeResult` currently represents only terminal completed, failed or cancelled outcomes. Approval pause and resume extend the contract in M10; they must not be encoded as a fake failure.
- `PersistentEventEmitter` always awaits Store append before notifier delivery. A replay with `created=false` is not notified twice. Notifier failure or timeout is best effort and cannot roll back a durable event or change the Run outcome.
- Store locks must be released before model, tool or notifier work. No callback or subscriber await is allowed inside the Run→Event critical section.
- Runtime and notifier exceptions are converted to stable, safe categories or safe diagnostics. Raw exception text, prompts, tool arguments, tool results and provider payloads do not cross the persistence or logging boundary.
- ManualRuntime creates a fresh synchronous Loop per Run and executes it in a worker thread. It maps only reviewed event fields, preserves old Loop behavior, and uses cooperative cancellation with a bounded cleanup grace. Code must not claim that a Python worker thread was hard-cancelled.
- A durable start replay with `created=false` does not execute Runtime again. Multiple coordinators wait for the Store winner; process restart, lease expiry and orphaned-running recovery remain separate persistence concerns.
- A progress Store failure is fail closed: do not notify or invent a terminal state when commit outcome is unavailable. Leave the durable Run for the recovery service and surface the stable Store error.
- Default tests inject Manual/Mock or fake Runtime implementations and must not hide SDK or network calls. Online execution remains behind explicit Settings and a separately authorized verification command.
