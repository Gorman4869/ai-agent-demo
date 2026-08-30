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
- Provider, MCP, tool, Store, timeout and budget failures that participate in retry policy use the content-free catalog in `backend.app.reliability`. `retryable` classifies a transient error; it never authorizes replay by itself. Unknown adapter error codes fail closed.
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
- Keep the legacy synchronous `RunObserver` separate from durable Run observability. Durable Trace, Metrics, and usage ledger projections read only the same owner-scoped persisted Run events.
- Trace and Metrics exporters are replaceable async sinks invoked only after persistence. Export failure is best effort and cannot rewrite the durable Run; EventStore remains the rebuildable source of truth.
- Durable Trace records use an explicit content-free allowlist. Prompts, answers, model deltas, RAG excerpts, Memory, tool arguments/results, raw exceptions, owner/session identifiers, and secrets never enter Trace or Metrics.
- Run-scoped aggregate usage is a cumulative event snapshot, not a single-call `UsageRecord`. Preserve every valid ledger entry, use only the latest sequence for the Run cost summary, and never sum cumulative snapshots twice.

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
- Shared tool retry is limited to idempotent, replay-safe, non-side-effecting definitions. A side-effecting tool without a trusted persistent idempotency key is never automatically retried, including after timeout or result-unknown failure and even when one approval was consumed.
- `ToolResult` may carry only stable prior-attempt error codes and bounded retry delays for reviewed progress events. Raw handler or remote exception text never enters retry events.

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
- Model and read-only tool retries use bounded exponential backoff. Initial delay must not exceed its maximum, the maximum delay must remain below the Run timeout, and direct compatibility constructors may explicitly choose zero delay without changing production defaults.
- Token and cost settings are per-run cumulative upper bounds. Request values may narrow server policy but never raise a server-owned limit.
- `ApplicationContainer` is the composition root, not a service locator. FastAPI routes continue to close over narrow dependencies, and tests may inject explicit adapters.
- A complete Container and legacy `create_app()` dependency overrides are two alternative assembly paths and must not be mixed.
- Persistence is an explicit `memory` or `postgres` setting and defaults to memory. A PostgreSQL DSN is a `SecretStr`; a configured DSN never enables PostgreSQL without the matching backend selector.
- `ApplicationContainer.create()` is the synchronous in-memory path. PostgreSQL application resources require `await ApplicationContainer.open()` and are opened by FastAPI lifespan, never at module import.

## 13. Durable Run and Store Contracts

- `backend.app.domain.run.RunRecord` is the M8+ durable domain snapshot. `backend.app.services.run_service.RunRecord` remains the legacy synchronous HTTP/SSE record after M8-T3; code that must reference the latter aliases it as `LegacyRunRecord`. M12 owns the unified API migration.
- Legacy `run_service` and new `run_store` / `event_store` coexist in the Container without dual writes. M8-T3 exposes the durable path programmatically through `run_coordinator`; old routes remain isolated. New Stores are injected as a pair, and an explicit EventStore validates ownership against the matching RunStore.
- Run creation scopes idempotency to `(owner_id, idempotency_key_digest)`. A versioned canonical request digest distinguishes a safe replay from a conflicting request, and the raw key is never retained.
- Run transitions use a monotonically increasing `version` compare-and-set. Terminal states never transition again, including to themselves.
- M12 durable HTTP routes are isolated below `/api/durable`; legacy `/api/sessions/.../runs`, `/api/runs/{id}` and SSE remain compatibility-only and never dual-write. A durable Run is created before a background Coordinator command is scheduled; HTTP reads, cancellation and approval all use the same durable owner scope.
- Authenticated durable owners come only from the verified `Principal`. For an anonymous initial Run, the client supplies a 32-byte-minimum random `Idempotency-Key`; its SHA-256-derived owner is stored, the raw capability is returned only to that caller, and later requests use `X-Session-Token`. A supplied `session_id` is accepted only after an owner-scoped stored Run proves that session exists.
- Durable approval HTTP accepts only an approval ID and decision. It reconstructs tool call/name/argument digest from the owned `run.waiting_approval` event, then the Coordinator and ApprovalStore repeat their exact stored binding checks. Client request data never selects a tool or approval arguments.
- Event IDs are caller-generated stable IDs. The Store assigns per-Run sequence and UTC time; same ID plus same content replays the original event, while changed content is a stable conflict.
- Event data and tool data accept bounded standard JSON only: finite numbers, string keys, at most 64,000 encoded bytes, bounded depth and bounded node count. Stores copy nested data on write and every return.
- Heartbeats are transport events and never consume a business event sequence. Consumers rely on unique increasing sequence values; they do not sort by timestamps.
- Durable SSE is isolated below `/api/durable/runs/{run_id}/events`. It authenticates the same owner scope as the Run, treats `after` as an exclusive EventStore sequence cursor, replays Store history before waiting, and emits heartbeat comments without a business sequence. A live notifier may coalesce wakeups but must not retain event payloads or be the source of truth; close only after a terminal Run has no unread stored events.
- Durable snapshot citations and aggregate usage are projections of that same owner-scoped Run's persisted events, never a fresh KnowledgeBase search or a reconstruction from `prompt_context`. Context may emit `rag.citations` only from RAG fragments selected into the assembled prompt and only with reviewed public fields. Ignore malformed events, keep the last valid projection, and preserve unknown usage/cost as `null`; M12 does not create a usage ledger, pricing source, or zero-cost inference.
- M13 durable observability promotes valid `scope=run` usage events into an event-sourced ledger and latest cumulative cost summary without adding a second persistence write. PostgreSQL durability comes from the existing EventStore; no adapter may silently create a separate non-atomic usage write path.
- `UsageRecord` describes exactly one model call. Unknown cost remains `None`; persisted currency uses `Decimal`, never a float conversion.
- Side-effecting `ToolExecution` records require an idempotency digest at creation. Raw arguments and raw results are not retained; safe summaries and digests are bounded.
- A generic retry wrapper must not surround Store mutations, lifecycle commits, terminal settlement, or an entire Runtime. Existing stable command IDs, event IDs, compare-and-set, lease and recovery protocols own their replay semantics; a result-unknown Store operation fails closed until its durable winner is read.
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
- Retry waits use the same Run `CancellationToken`, consume the same deadline, and stop before the next attempt when cancellation wins. `model.retrying` and `tool.retrying` expose only reviewed attempt, delay, identity metadata and stable error code fields.
- A durable start replay with `created=false` does not execute Runtime again. Multiple coordinators wait for the Store winner; process restart, lease expiry and orphaned-running recovery remain separate persistence concerns.
- A progress Store failure is fail closed: do not notify or invent a terminal state when commit outcome is unavailable. Leave the durable Run for the recovery service and surface the stable Store error.
- Default tests inject Manual/Mock or fake Runtime implementations and must not hide SDK or network calls. Online execution remains behind explicit Settings and a separately authorized verification command.

## 15. OpenAI Agents SDK Adapter

- Construct a fresh, explicit `openai.AsyncOpenAI` client and `OpenAIResponsesModel` for each Run through the injected model factory. Never call `set_default_openai_key`, mutate environment variables, or change SDK-global provider state. Container construction may capture a factory but must not create a client or start network work.
- Every Run supplies an explicit `RunConfig` with `tracing_disabled=True` and `trace_include_sensitive_data=False`. If those controls cannot be applied, fail closed; never fall back to SDK trace defaults or persist raw traces.
- Use the public `Runner.run_streamed` API and consume its `stream_events()` async iterator. Do not depend on private SDK run-loop internals.
- Build a fresh trusted Run context and tool snapshot for every Run. The context binds the server-owned `run_id`, `ToolExecutionContext`, and cancellation token. Tool definitions are role-filtered, deep-copied, revalidated, schema-bounded, and placed in an isolated registry; execution repeats authorization.
- Runtime paths without the M10 approval pause/resume contract must still omit and fail closed on every approval-required, high-risk, write, or otherwise side-effecting tool even when an approval record exists. Bound tool arguments and results, and never persist or log their raw values.
- Structured agent output uses the JSON shape `{"answer": ...}`. The raw `response.output_text.delta` decoder may emit only decoded answer text plus a bounded positive `segment`, never JSON framing, field names, or escape syntax. Chunks from one object share a segment; later objects increment it, and only the last segment is verified against the final structured output so UI consumers never concatenate draft and final without a boundary.
- Provider events use an explicit allowlist: accept only reviewed answer deltas and safe `tool_called` / `tool_output` metadata. Ignore reviewed non-content raw response types and only the SDK's first initial-agent update; a later agent update is an unsupported handoff and fails closed, as does an unknown SDK wrapper. Provider objects, raw responses, tool arguments, tool results, and raw exceptions never cross the Runtime boundary.
- Cancellation targets the same `RunResultStreaming` instance with immediate cancellation and drains the same async iterator once. Suppress late events, keep cleanup bounded, and re-raise an outer `CancelledError`. Do not claim provider, tool, worker-thread, or transport hard cancellation; read-only synchronous tools executed with `asyncio.to_thread` retain the KI-017 limitation.
- `emit()` awaits the Coordinator Store path. A `StoreError` propagates unchanged and must not be reclassified as a provider/runtime failure, trigger model or tool re-execution, or notify subscribers before durable append succeeds.
- SDK context usage is currently aggregate, Run-scoped evidence and is emitted as `model.usage` with `scope=run`. It is not a domain `UsageRecord`, because that record represents one model call and the aggregate lacks per-call duration and cost.
- Unknown cost stays `None` with `cost_source=unknown`; never report zero, guess a value, or hard-code unversioned pricing. `max_turns` is a Run-loop bound and configured output tokens are a per-model-request bound, while model-call and input-token checks are aggregate post-run or approximate. The HTTP client timeout is not a strict whole-workflow wall clock, and `max_cost_usd` is not yet enforced. Code and teaching material must disclose KI-018 instead of claiming hard budget guarantees.
- Keep the OpenAI HTTP client's internal retries disabled. The SDK `ModelRetrySettings` is the single model retry layer, with explicit bounded backoff and provider-suggested policy; SDK tools remain read-only snapshots and use the shared replay-safe tool policy.
- Offline construction and fake-Runner contract tests establish only code-complete evidence. Do not claim online verification; M8-T6 owns the separately authorized real-provider streaming and tool-call smoke test.

## 16. MCP Client Lifecycle and Tool Adapter

- `Settings.mcp` selects only stable IDs from a server-owned `McpServerConfig` catalog. HTTP or model input must never provide an executable, arguments, working directory, environment, or transport policy.
- The default MCP selection is empty and must not start a process. Enabling a local Server remains offline evidence and must not be described as a remote or production MCP deployment.
- Each STDIO connection enters `stdio_client`, enters `ClientSession`, initializes, and exits in one worker task. Manager timeout and cancellation signal that worker and await cleanup instead of exiting anyio cancel scopes from another task.
- FastAPI lifespan owns Manager start and close. Startup is all-or-nothing; a partial set of initialized Servers is closed before a stable startup failure leaves the boundary.
- Public diagnostics expose only the reviewed lifecycle code and safe Server ID. Raw commands, arguments, stderr, invalid protocol lines, and exception text do not enter logs or errors.
- `list_tools` and `call_tool` requests run through the same connection worker that owns the SDK contexts. A `ClientSession` must not be used from a manager task or leaked as a public object.
- Treat discovery metadata as untrusted. Local names, descriptions, roles, risk, side-effect, and approval policy come only from the server-owned `McpToolPolicy`; an unlisted remote tool is neither mapped nor directly callable.
- Normalize only the reviewed object-schema subset, remove remote prompt text, force `additionalProperties=false`, and reject unknown keywords or structural limits. Bound schemas, arguments, results, pages, cursors, depth, node count, and byte size.
- Expose mapped tools through the existing shared `ToolDefinition` and `ToolRegistry` so Manual, Agents SDK, and LangGraph retain the same validation and authorization boundary. Cross-Server local-name conflicts fail closed.
- Each remote call has a separately configured timeout. Return structured JSON when available, accept only bounded text fallback, and map timeout, disconnect, remote failure, invalid response and request rejection to distinct catalog codes without raw result or exception leakage. Any later retry is owned by the shared replay-safe tool policy, never by the MCP transport itself.
- M9-T3 proves the same Client adapter against the built TypeScript Knowledge Server over real local STDIO. The TypeScript process remains a server-owned catalog entry; tests must exercise initialize, discovery, valid and invalid calls, and close without importing Server functions directly.
- Local Python and TypeScript STDIO evidence is E3, not remote or production E4. Reconnect, invocation idempotency, production capacity, and Skill behavior remain later work.

## 17. Read-Only Skill Catalog

- The default Skill root is server-owned and fixed to the repository `skills` directory. Request or model input may select only loaded Skill names; it must never supply a root or file path.
- M9-T4 accepts a strict frontmatter subset containing only scalar `name` and `description`. It is not a general YAML loader and must reject tags, collections, duplicate or unknown keys, mismatched directory names, controls, and oversized metadata.
- Load only `SKILL.md` plus bounded UTF-8 Markdown files explicitly linked below `references/`. Do not load or execute `agents/`, Python, shell, binaries, arbitrary local links, percent-encoded paths, or query-bearing references.
- Resolve every file under the canonical fixed root, reject symlink components and traversal, cap Skill count, files, references, total bytes, query length, and frontmatter lines, and expose only stable error codes without raw paths or content.
- Catalog snapshots contain frozen dataclasses and tuples. `load()` reuses one immutable snapshot; only the trusted application may call `refresh()` to replace it.
- Resolver behavior is deterministic and offline: `$skill-name` is an explicit trigger; automatic matching requires every hyphen-separated Skill name token as a complete query word. An unknown explicit name fails closed.
- M9-T4 only discovers and resolves Skill content. Runtime context injection, effect/cost evaluation, and permission interaction belong to M9-T5.

## 18. Skill Runtime Context

- Keep Skill guidance separate from `RuntimeRequest.input_text` and `ToolExecutionContext`. `prompt_context` is application-owned, hidden from repr, bounded to 32,000 UTF-8 bytes, and added after existing positional fields for compatibility.
- Build context only from an immutable M9-T4 Resolver snapshot. Inject at most four Skills and 24,000 UTF-8 bytes, use deterministic JSON, embed reviewed reference content without its source path, and fail closed with stable errors.
- The default Container wraps only its built-in Runtime map with `SkillAwareRuntime`. Explicitly injected Runtime objects remain unchanged so dependency injection is predictable; callers opt in by composing the wrapper themselves.
- Manual and LangGraph use a system message while the Agents SDK default factory uses agent instructions. Every path keeps the original user input unchanged and must never derive identity, roles, approvals, tools, or Schema from Skill text.
- Tool visibility and execution continue through the shared `ToolRegistry`. Tests must prove malicious Skill wording cannot bypass role checks, exact approvals, or argument validation and that denied handlers do not run.
- Offline Skill cost reports may record exact UTF-8 bytes and a clearly labeled `ceil(bytes / 4)` heuristic. Provider usage remains unavailable and financial cost remains `None`; this comparison is not a tokenizer, billing, or online-model claim and does not close `KI-018`.

## 19. LangGraph Checkpoint State

- `RunCoordinator` derives `RuntimeCheckpointContext` from the stored owner and Run. Request, model, tool, and client data never supply a checkpoint thread; the context stores only versioned owner/thread digests and validates its Run binding.
- Keep checkpoint state minimal and versioned. Persist only reviewed workflow fields and normalized Runtime outcomes; pass requests, prompts, event sinks, cancellation controls, tools, and delegates through invocation context instead of state.
- Read and validate existing state before invoking a checkpointed graph. Unknown versions, wrong owner scope, malformed counters, and unavailable storage fail closed with stable categories; do not silently migrate or discard state.
- A Schema upgrade requires an explicit migrator and fixed old-version fixtures before increasing the current version. Until then, rejecting every non-current version is the migration boundary.
- Save a side-effect-free progress boundary before a fallible node. A node exception must not expose raw text or trigger an automatic delegate retry; `StoreError` and outer cancellation retain their existing propagation semantics.
- `InMemorySaver` proves only same-process recovery when Runtime instances share one saver. It is not process-restart, multi-process, encrypted, capacity-managed, or PostgreSQL persistence evidence.
- Keep checkpoint-enabled LangGraph modules on explicit imports so the M1 standard-library path remains runnable with `python -S`. Do not switch the default Container Runtime as part of an isolated checkpoint task.

## 20. LangGraph Approval Pause and Resume

- Keep `RuntimeResult` terminal. A Runtime returns `RuntimeApprovalPause` for approval waits and implements `ApprovalResumableRuntime` before the Coordinator may call its resume path.
- Bind approval requests to server-owned Run ID, principal, tool call ID, tool name and canonical argument digest. Raw arguments remain in a private server-side store and never enter checkpoint state, Run events, repr output or client resume data.
- Accept only explicit `approve` or `reject` decisions. A boolean, model field, client-supplied grant or changed binding cannot authorize execution; expiry is derived from the server clock.
- Split the graph into a side-effect-free request preparation node and an interrupting execution node. Resume only with `Command(resume=...)` after validating the stored checkpoint and server resolution; never rerun the planner to reconstruct an approved call.
- Persist `running -> waiting_approval + run.waiting_approval` with `commit_pause()` and `waiting_approval -> running + run.resumed` with `commit_resume()`. Ordinary append rejects both lifecycle event types.
- Only the actor that creates the resume commit may invoke the Runtime. Tool execution still traverses `ToolRegistry` and consumes the exact Run-bound approval once; rejection, expiry, tampering and replay do not call the handler.
- Treat an already-consumed approval with a non-terminal checkpoint as an unknown side-effect outcome: return `side_effect_resume_unsafe`, emit `approval.stopped`, and never call the handler again. Shared `InMemorySaver` and ApprovalStore prove same-process recovery across Runtime instances only; process restart, multi-process arbitration, durable private arguments, persistent ToolExecution results and recovery scanning remain M11 work.

## 21. Bounded LangGraph Replanning

- Keep dynamic planning in an explicitly imported Runtime. Structured plans contain only stable server-reviewed step IDs, operation IDs, and side-effect/approval metadata; raw input, arguments, intermediate output, planner objects, executors, emitters, and cancellation controls never enter checkpoint state.
- `RunFailure.retryable` is necessary but not sufficient for replanning. A failure must also match the server-owned recoverable-code allowlist, avoid auth/authorization, validation, approval, security, storage, and cancellation categories, and originate from a non-side-effecting step.
- Bound total step executions and replan count independently. A replacement plan must fit the remaining step budget, cannot repeat a completed step ID or completed side-effect operation, and is rejected when its operation signature repeats a prior path even under different cosmetic IDs.
- Approval-required steps stop before executor invocation and must move through the M10 approval Runtime. Planner metadata never grants authorization; real tool execution still traverses `ToolRegistry` and its trusted context.
- A terminal checkpoint replays without invoking planner or executor. A pending read-only step may resume from a shared same-process saver; a pending side-effect step has an unknown result and fails closed without replay.
- `InMemorySaver` remains same-process E3 evidence. Persistent ToolExecution records, result-unknown recovery, process restart, multi-process arbitration, default Container migration, and HTTP APIs remain later tasks.

## 22. Manager-as-Tools Comparison

- Keep the M10 multi-Agent comparison explicitly imported and outside the default Container. It is a bounded experiment, not a replacement for `OpenAIAgentsRuntime` or its fail-closed handoff event contract.
- Build manager-as-tools with the public `Agent.as_tool()` and `Runner.run()` APIs. The manager receives only specialist tools; researcher, writer, and reviewer use distinct instructions and isolated business-tool snapshots.
- Build every role tool through the shared `build_sdk_tools()` and `ToolRegistry` boundary. Role filtering, Schema validation, low-risk policy, cancellation context, and repeated execution authorization remain application-owned; manager input cannot create identity, roles, approval, or new tools.
- Give both manager and nested specialists explicit turn limits. Specialist failures propagate instead of becoming a successful answer, and the single-Agent control receives the same business tools and fixed cases.
- Every run still uses `RunConfig(tracing_disabled=True, trace_include_sensitive_data=False)`. The standalone offline evaluator installs a process-local disabled trace provider before calling the SDK so the locked SDK cannot initialize its default exporter; do not embed this evaluator in the application process or overwrite an application trace provider.
- Compare quality, failure rate, local elapsed time, aggregate fixture usage, and topology complexity separately. Deterministic Model usage is not Provider Token or billing evidence, local latency is not production latency, and unknown online cost remains `None`.
- Retain the single-Agent design when the fixed set has no quality or failure-rate gain. Handoff, default Runtime migration, online quality, persistent usage/cost, and recovery fault injection remain separate tasks.

## 23. PostgreSQL Persistence

- PostgreSQL code stays explicit opt-in. The default offline Container remains on the in-memory Store pair; only `AI_AGENT_PERSISTENCE=postgres` plus a valid secret DSN may select the verified PostgreSQL application composition.
- Pin `psycopg[binary,pool]` and `langgraph-checkpoint-postgres`. One `AsyncConnectionPool` with `dict_row`, autocommit, and prepared statements disabled is shared by the Run/Event adapters and `AsyncPostgresSaver`; application operations still open explicit transactions.
- Application migrations are ordered SQL files with immutable SHA-256 checksums. Apply pending versions under one PostgreSQL advisory transaction lock; checksum drift, unknown history, or a failed statement must fail closed and never mark a version applied.
- PostgreSQL Run/Event adapters inherit the adapter-independent Store contract. Lock the owned Run row before CAS and event work, allocate event sequence through the per-Run counter row, and commit lifecycle state plus event in one database transaction. Never use `MAX(sequence) + 1`.
- Driver, pool, and SQL failures cross the adapter boundary only as stable Store or migration errors. Database unavailability never selects an in-memory fallback.
- The official async checkpointer requires `setup()` before first use. On Windows, Psycopg async integration runs on a Selector event loop; libraries do not mutate the process-wide event-loop policy at import time.
- PostgreSQL integration tests require an explicit local DSN and are not part of default offline discovery. They must execute a real database, shared Run/Event contract, migration rollback, transaction rollback, and separate-process checkpoint recovery before claiming real PostgreSQL evidence.
- The first M11-T1 slice persisted Run/Event and LangGraph checkpoint state only. Later verified slices added PostgreSQL Approval/Memory, private approval arguments, ToolExecution arbitration, lease/recovery scanning, async Store facades, and the opt-in Container/FastAPI lifecycle; retain the slice boundaries when interpreting older evidence.
- Keep `ApprovalStore` and `MemoryStore` synchronous while the existing ToolRegistry and memory HTTP boundary are synchronous. `PostgresPersistence` owns a separate shared synchronous pool for these adapters alongside the async Run/Event/checkpoint pool; both pools share one DSN and lifecycle, but never claim a transaction across pools.
- Persist approval requests and grants separately. Private arguments stay only in the request table as bounded JSON; public objects, checkpoints, events, probes, and logs expose only IDs and digests. Resolve the request and create its grant in one transaction, then consume the exact grant under a row lock.
- Allocate conversation message sequence through a per-session counter and trim the bounded window in the same transaction. Long-term facts require explicit approval and every read/delete remains owner-scoped.
- Run memory and approval adapter-independent contracts against both in-memory and PostgreSQL implementations. A separate-process probe must recover private arguments, one-time approval state, messages, and facts without printing their content.
- The synchronous database adapters are not approved for direct use on an async event loop. Application async paths must use the verified bounded facades; direct compatibility calls remain caller-owned. Cross-pool consistency and encryption at rest remain incomplete; the pgvector knowledge schema uses the separate contract below.
- `ToolExecutionStore` stays async and derives ownership through its parent Run. A new execution requires a running owned Run; `(run_id, tool_call_id)` is unique, and every supplied idempotency digest is scoped by Run and tool name. Side-effecting executions always require that digest.
- Tool claim and terminal settlement use version CAS. A matching idempotency replay returns the existing authoritative state; changed arguments fail with a stable conflict. Raw idempotency keys, arguments, and results never enter the table or probe output.
- Recovery may claim a pending execution. A recovered running execution has an unknown side-effect outcome and may only become terminal `unknown`; it must never be automatically replayed. A recovered terminal execution is reused as-is.
- PostgreSQL ToolExecution uses the same async pool as Run/Event but remains a separate transaction. This proves durable arbitration, not an atomic commit with an external side effect, approval's sync pool, checkpoint state, or Run/Event terminal state.
- Run leases are async, owner-bound, and one-per-Run. The Store generates an opaque token, returns it only in a repr-safe handle, and persists only its SHA-256 digest. PostgreSQL lease expiry always uses database time rather than an application process clock.
- A lease-aware Coordinator reserves execution against the exact `queued` or `waiting_approval` predecessor before `commit_start()` or `commit_resume()`. The existing running-only `acquire()` remains unchanged; a reservation commit with unknown outcome keeps its lease for scanner convergence.
- Heartbeat and release require the exact unexpired token/version. Expired rows are never replaced by a normal executor; a bounded recovery scan rotates credentials with `FOR UPDATE SKIP LOCKED`, and stale handles fail with `run_lease_lost`.
- Each active Coordinator execution owns one serialized heartbeat session. Lease loss cancels the Runtime and propagates the stable Store failure unless a durable terminal/waiting winner already exists; it never invents a terminal result. Pause, terminal, and cancel stop heartbeat before lifecycle commit and release only after the durable transition.
- Orphan recovery settles running ToolExecutions as `unknown`, cancels pending or approval-waiting executions, and only then commits the Run as non-retryable `run_orphaned`. These are convergent separate transactions, not distributed exactly-once.
- An explicit `RunRecoverySupervisor` owns exactly one serialized scan task. It runs the first scan immediately, waits only after a completed scan, continues after stable Store failures, and surfaces non-Store programmer errors instead of swallowing them.
- Supervisor close cancels and awaits its task before persistence closes. The lifecycle is created/running/closing/failed/closed; a closed or failed instance is never restarted, and a start during closing fails closed.
- `PostgresExecutionComposition` is the explicit owner for `PostgresPersistence.open/setup`, lease-aware Coordinator construction, recovery supervisor start, and `supervisor.close -> persistence.close`. Startup is all-or-nothing: setup, configuration, or supervisor start failure closes every resource already obtained before propagating the original failure.
- `RunCoordinator.quiesce()` atomically changes accepting to quiescing under the active lock, rejects new execute/resume with `coordinator_not_accepting`, and shares one drain task across concurrent callers. A quiesced Coordinator is never reopened.
- The quiesce timeout is a natural-completion grace period. After it expires, mark active controls with the internal `coordinator_shutdown` reason, cancel and await their tasks, stop heartbeat, and abandon rather than release the lease. Never translate application shutdown into `cancelled_by_user` or another durable cancelled result.
- Composition close orders `coordinator.quiesce -> supervisor.close -> persistence.close`. If quiesce cannot establish that Runtime/heartbeat work stopped, do not close persistence underneath it. Caller cancellation is propagated only after owned cleanup completes.
- Keep PostgreSQL composition explicit opt-in even after HTTP/command admission, Container/FastAPI lifecycle, and synchronous Approval/Memory async isolation have verified contracts. Default memory operation, hard process termination, and production restart evidence remain separate claims.
- Async code must use `PostgresPersistence.async_approval_store` and `async_memory_store` rather than invoke the synchronous PostgreSQL adapters on the event loop. Both facades share one bounded `PostgresSyncStoreBridge`; its worker count follows the synchronous pool capacity, and approval arguments are detached before submission.
- A queued sync Store submission may be cancelled before it starts. Once its worker is running, timeout or caller cancellation cannot hard-cancel PostgreSQL: keep tracking the worker, mark timeout results as unknown, discard late results safely, and never automatically retry a write with an uncertain outcome.
- Persistence shutdown orders sync Store bridge drain before sync pool close and async pool close. The sync pool open worker is also owned: cancellation waits for open to finish before cleanup. Direct compatibility calls through the synchronous adapters are outside bridge tracking and must stop before persistence closes.
- FastAPI application startup orders PostgreSQL execution composition before MCP, then opens shared HTTP/command admission. Startup failure closes already-opened composition without selecting memory fallback.
- Application shutdown first stops and drains HTTP/command admission across the complete ASGI response body, then closes PostgreSQL composition, and closes MCP last so active Coordinator work can quiesce while MCP remains available.
- Async application code uses Container `async_approval_store` and `async_memory_store`. Synchronous compatibility adapters remain for legacy worker-thread paths only and are not an async application API.
- Legacy `InMemoryRunService` HTTP/SSE remains isolated without durable dual writes until M12. Legacy static auth approvals remain process-local; do not replay them into persistent one-time grants during application startup.
- On Windows, a PostgreSQL application host must select a Selector event loop before creating the loop. Library imports must not mutate process-wide event-loop policy.

## 24. PgVector Knowledge Storage

- Keep pgvector knowledge migrations in `backend/knowledge_migrations` with their own advisory lock and immutable `knowledge_schema_migrations` checksums. Do not make the verified M11-T1 Run Store migrations require the vector extension.
- The M11-T2 course schema is fixed to `knowledge_documents` plus `knowledge_chunks.embedding vector(3)`. Retrieval uses cosine distance `<=>` and the HNSW `vector_cosine_ops` index; changing dimensions or distance semantics requires a new versioned schema decision.
- Replace one document atomically: upsert metadata, delete old chunks, and insert every new chunk in one transaction. A failed vector write must preserve the prior document and chunks; document deletion relies on the reviewed cascading foreign key.
- Demo content is seeded only by an explicit application command. Compare a canonical SHA-256 document digest under a transaction advisory lock and skip database rewrites for unchanged content; application import, `create_app()`, and lifespan must not seed implicitly.
- Fake cursors may prove parameterization and rollback branches, but real pgvector evidence requires the integration-only Compose service and explicit DSN. It must execute migration, fixed dimensions/index inspection, insert, replace, delete, similarity search, dimension failure, and transaction rollback.
- `deploy/compose.integration.yaml` is localhost-only trust/tmpfs test infrastructure. It is not the production Compose, persistence, authentication, TLS, backup, capacity, or high-availability contract.
- M11-T2 uses a deterministic three-dimensional test embedding only. Provider caching/retry, online authorization, retrieval metrics, and production integration remain M11-T3/M11-T6/M11-T7/M13 work.

## 25. Embedding Adapter and Batching

- Embedding contracts live in `backend.app.knowledge.embeddings`. A Provider handles one bounded batch; a Model exposes single and arbitrary-length batch calls. PgVector depends only on the Model and never reads environment settings or creates an SDK client.
- Every Model exposes frozen provider, model, revision, and dimension metadata. Metadata drift, output-count mismatch, dimension mismatch, non-numeric values, and non-finite values fail with stable content-free errors.
- Single embedding calls use the same batch path. Normalize whitespace before the Provider, preserve input order across batches, return an empty tuple for an empty batch, and reject blank batch items before any Provider call.
- Resolve all document embeddings before opening a PgVector transaction. A failed or partial Provider batch must not return a prefix or rewrite existing document rows.
- The offline SHA-256 token-hash Provider is deterministic course infrastructure, not semantic-quality, tokenizer, online Provider, or billing evidence. Its metadata dimensions must match the fixed pgvector schema.
- Cache keys use the versioned canonical metadata namespace plus a normalized-text digest and expose only `embedding:v1:<sha256>`; raw text never enters a key, log, or error. The bounded process-local cache accepts only that key shape and stores immutable vector copies.
- A caching Batching Model revalidates hits, deduplicates normalized misses, and writes new entries only after every Provider batch succeeds and validates. A failed later batch or retry exhaustion must not cache a completed prefix.
- Only `RetryingEmbeddingProvider` may retry `RetryableEmbeddingError` by immutable Provider batch. It uses a bounded `max_retries + 1` attempt count and maps exhaustion to `embedding_retry_exhausted`; input, metadata, protocol, dimension, authentication, and policy errors are not retryable.
- The current cache is process-local without persistence, TTL, or cross-process invalidation. The current retry wrapper has no delay/backoff and applies only to read-only Embedding batches; it must not be reused for tools, database operations, or side effects.
- Online Embedding adapters receive configuration and secrets from composition only after the global online gate and embedding-specific provider/model gate pass. They never read environment state directly, and real execution still requires per-run user authorization.
- The OpenAI Embedding adapter uses the locked SDK public `client.embeddings.create()` API, requests float vectors with explicit dimensions, restores input order from response indices, and validates provider usage before publishing it to an injected sink. Empty Provider batches must not construct a client.
- Create online SDK clients lazily per Provider batch and close them deterministically. Set SDK `max_retries=0`; only the shared retry wrapper owns the bounded retry policy. Connection and internal-server failures are retryable, while authentication, permission, quota/rate-limit, invalid request, response protocol, usage, dimension, and value failures are not.
- `EmbeddingSettings` defaults to `offline`. Online composition requires the global online switch, embedding provider/model/revision, shared secret key, and bounded dimensions/batch/cache/timeout/retry settings. Safe summaries expose only configured booleans and numeric limits, never provider labels or secrets.
- SDK `MockTransport` tests prove local request/response mapping and error policy only. They must not be described as network reachability, provider model availability, semantic quality, billing, or online E4 evidence.

## 26. Bounded Context Assembly

- Context assembly lives in the standard-library-only `backend.app.context` layer. Its first slice consumes already collected fragments and must not query Stores, call a model, or mutate Runtime/Container state.
- Sources are exactly system, recent, summary, memory, RAG, and Skill. Trust is server-owned by source: only system is trusted policy; Skill is bounded application guidance, recent is user content, summary/memory are owner-scoped data, and RAG is untrusted evidence. Fragment content cannot supply or override trust or priority.
- Validate every owner scope before selection. Recent, summary, and memory require the exact assembly owner; system and Skill are global-only; an explicitly scoped RAG fragment must match. Any mismatch fails the complete assembly with a stable content-free error.
- Selection priority is `system -> memory -> recent -> summary -> skill -> rag`; recent candidates select newest first. Render order is `system -> skill -> summary -> memory -> recent -> rag`, with selected recent messages restored chronologically. Both orders must appear in the safe report.
- Keep or drop complete fragments. Enforce per-source budgets and an exact rendered-prompt total; never truncate JSON or a fragment in place. A system fragment that cannot fit fails closed instead of being dropped.
- Render non-empty output as the fixed safety header plus deterministic `context-assembly-v1` JSON. Instruction-like RAG or user text stays in its content field with non-policy trust and cannot forge JSON structure through quotes or brackets.
- Context budget units use the labeled `ceil(UTF-8 bytes / 4)` heuristic. The default 8,000-unit total keeps output within RuntimeRequest's 32,000-byte prompt-context limit, but it is not Provider tokenizer usage, a model context-window claim, billing, or cost evidence.
- Reports may expose stable fragment IDs, sources, trust, counts, estimated units, availability, decisions, and reasons. They never expose fragment content or owner IDs and always report Provider usage unavailable and estimated cost unknown.
- Source collection uses an explicit `ContextCollectionInput` constructed by the trusted application caller. Owner, session, query, and system constraints never come from model-produced fields; owner/session/query and system policy content are hidden from normal representations, while reviewed stable constraint IDs may remain visible.
- Reuse the existing synchronous `MemoryStore.messages()` / `facts()`, `KnowledgeBase.search()`, and `SkillContextBuilder.build()` contracts without widening them. Validate every returned fact owner before querying downstream sources; a mismatch fails the whole collection without a partial result.
- Map messages, facts, citations, and Skill context to deterministic complete fragments. Report-safe IDs use a source-specific versioned digest; recent ordinals preserve Store order, RAG ordinals preserve search rank, and source content never enters report IDs in plaintext.
- Summary is an injected result protocol, not an implicit model call. `available=false` marks only the summary source unavailable; it never restores history outside the Store's bounded message window and never carries raw failure text.
- A collected result binds its owner to the Assembler call so callers cannot accidentally re-scope the fragment set. The current synchronous collector trusts the server-resolved session-to-owner relationship because the existing MemoryStore message contract has no owner field; Runtime/Container wiring must preserve that boundary explicitly.
- `ContextAwareRuntime` is an explicit request adapter around an existing `AgentRuntime`. Its injected binding factory supplies only trusted owner, session, and system constraints; collection query text always comes from the original `RuntimeRequest.input_text`, never from model output or tool arguments.
- Reject an existing `prompt_context` before resolving a binding or querying a source. A non-empty assembly uses `dataclasses.replace()` and changes only `prompt_context`; an empty assembly delegates the exact original request object. Preserve execution and checkpoint context object identity.
- Map only expected context preparation, collection, and assembly failures to the stable content-free Runtime failure `context_unavailable`. Do not swallow binding-factory or dependency programmer errors. Terminal results and approval pauses from the delegate pass through unchanged, and a failed preparation never calls the delegate.
- Do not stack the existing `SkillAwareRuntime` outside `ContextAwareRuntime`: both own `prompt_context` and intentionally fail on a pre-populated value. When default composition later adopts the context adapter, its collector must be the single Skill source and explicit caller-supplied Runtime mappings must remain untouched.
- The current adapter calls the synchronous collector and is verified only as an explicit offline/in-memory path. Never put synchronous PostgreSQL Memory or pgvector calls on the async event loop. Default Container integration requires a server-owned RunRecord owner/session binding or an async source boundary; deriving session identity from input text, tool arguments, principal ID, or run ID is forbidden.
- The Agent Runtime layer owns the frozen, repr-safe `RuntimeContextIdentity`. Keep it as an optional trailing `RuntimeRequest` field so direct Runtime teaching calls remain compatible; it is an application-internal scope object, not an external authentication DTO or prompt field.
- `RunCoordinator` is the only default application producer of Runtime context identity. Build it from the currently owned `RunRecord.owner_id/session_id` on both execute and approval resume paths. Never infer or override either value from input text, tool arguments, execution principal, model output, or run ID.
- When checkpoint and context identities coexist, their owner binding must match before Runtime execution. Context binding factories may only map the supplied identity and application-owned system constraints; missing identity fails closed for `ContextAwareRuntime` and must not trigger a Store lookup fallback or delegate call.
- The default in-memory `ApplicationContainer.create()` path resolves its Memory and Knowledge instances before built-in Runtimes, then shares one Skill builder and one `ContextSourceCollector` across the built-in Manual, LangGraph, and SDK Runtime wrappers. Use one `ContextAwareRuntime`; never stack the legacy `SkillAwareRuntime` around it.
- Default application context includes a fixed server-owned system constraint covering identity, roles, approvals, tools, schemas, and source trust. The constraint is application policy, not user input or configuration, and its content must remain bounded and non-secret.
- Explicit caller-supplied Runtime mappings are preserved byte-for-byte as object mappings and receive no hidden Context or Skill wrapper. The opt-in PostgreSQL `ApplicationContainer.open()` default path uses one `AsyncContextAwareRuntime` per built-in Runtime and its composition-owned async Memory façade; never pass its synchronous Memory adapter into either Context collector on the event loop.
- On the default Context path, Skill resolution failures are normalized with all other preparation failures to `context_unavailable`; the standalone legacy `SkillAwareRuntime` keeps `skill_context_unavailable`. Neither failure may expose the query, Skill name, source content, owner, or session.
- `AsyncMemoryContextSourceCollector` changes only Memory reads to the existing `AsyncMemoryStore.messages()` / `facts()` façade. It snapshots those results and then reuses the synchronous collector for validation, process-local Knowledge, Skill, summary, fragment mapping, and assembly; it does not widen either Store protocol.
- Bound both Memory reads by one collector timeout. Normalize outer and stable Store timeouts to content-free `memory_context_timeout`, map other Store failures to `memory_context_unavailable`, and propagate caller cancellation unchanged. Never continue to Knowledge, Skill, or summary after a Memory read failure, timeout, cancellation, invalid payload, or fact owner mismatch.
- PostgreSQL Context reads must enter through `AsyncPostgresMemoryStore` and its owned bridge; never call the synchronous PostgreSQL Memory adapter on the event loop. The remaining synchronous Knowledge, Skill, and summary dependencies on this seam must be process-local and non-blocking until their own async boundary is verified.
- Keep async Runtime preparation in the independent `backend.app.context.async_runtime` module. `AsyncContextAwareRuntime` must await `AsyncMemoryContextSourceCollector` before delegation, while the synchronous `ContextAwareRuntime` module and behavior remain unchanged.
- Async preparation rejects an existing prompt before binding or Store access, changes only `prompt_context`, preserves execution/checkpoint/context identity, and delegates exactly once. Normalize only expected preparation/collection/assembly failures to `context_unavailable`; caller cancellation and programmer errors propagate unchanged.
- PostgreSQL execution composition may create built-in Runtimes only through a synchronous factory invoked after persistence setup and before Coordinator/supervisor construction. Require exactly one of an explicit Runtime mapping or the factory; snapshot and expose the resolved mapping, and close persistence if factory construction fails or returns no mapping.
- Default PostgreSQL composition supplies its owned async Memory façade to one shared async collector and wraps each built-in Runtime exactly once with `AsyncContextAwareRuntime`; keep Knowledge, Skill, summary, and system sources process-local and non-blocking. Default in-memory composition and explicit caller Runtime mappings remain unchanged.
- `RunCoordinator` is the only main-Run message publisher because it owns the trusted stored session and terminal CAS result. Only the `created=true` winner of a `completed` terminal commit publishes one user message from the stored Run input followed by one assistant message from the terminal answer; failed, cancelled, approval-paused, and replayed terminal paths publish nothing.
- Publish a completed turn after the durable terminal commit and before the live terminal notification, and keep that owned publication inside Coordinator quiesce tracking. Memory write failure cannot roll back or rewrite the already durable Run, must be logged with only a stable code/run identifier/result-unknown flag, and must not be retried automatically.
- Main-Run conversation writes use the frozen, repr-safe `PublishTurn` command. It binds the trusted Run ID, hidden session, one plain user message, and one plain assistant message to a versioned canonical SHA-256 digest. Changed binding on the same Run raises content-free `memory_turn_conflict`.
- Both Memory adapters implement `publish_turn()` as one all-or-nothing command. The process-local adapter holds one message lock and stores only session/digest in its idempotency ledger; PostgreSQL migration 5 stores the same ledger and commits ledger insert, two-sequence allocation, both message rows, and window pruning in one sync-pool transaction.
- A new completed terminal publishes before live notification. An existing completed Run replay publishes the same command without invoking Runtime, so a terminal-after-crash gap can converge and an already published turn remains one pair. Keep ordinary `append_message()` only for compatibility and fixtures, not main-Run publication.
- Run/Event terminal and Memory turn remain separate async/sync-pool transactions. The guarantee is atomic idempotent turn publication plus explicit terminal replay convergence, not a shared commit or external exactly-once. Do not delete/expire the digest ledger while its Run can replay; production retention/GC remains separate work.
- Long-term facts start at version 0. Correction and deletion use frozen, repr-safe commands with an explicit expected-version CAS; correction remains approval-gated and changes only the value, while every lookup and mutation stays owner-scoped. Expose only stable `memory_fact_conflict` and `memory_fact_not_found` errors without owner, key, or value content.
- Commit a fact correction/delete and its audit row in the same Store operation. The in-memory adapter holds one fact lock; PostgreSQL locks the fact row and commits the state transition plus audit append in one sync-pool transaction. A deleted fact is a tombstone with cleared key/value and must not appear in active Context reads.
- Fact audit records contain only fact identity, version, created/corrected/deleted action, value digest, and time. Public repr, errors, probes, and logs never include owner, key, or value. A versioned SHA-256 digest is an integrity/reconciliation aid, not encryption or anonymization; low-entropy values remain guessable.
- Keep fact audit append-only within the application/schema guard. Reject ordinary database UPDATE/DELETE, but do not describe a trigger as an external tamper-proof ledger: a database owner can disable it or truncate data, and migration cannot reconstruct facts deleted before the audit table existed.
- Async fact mutations continue through the bounded Store façade. A timeout, cancellation, or connection break can be result-unknown; reconcile through the authoritative current version and audit digest, and never automatically retry correction/delete without a durable mutation idempotency key.
- Preserve the existing `POST /api/memories` response and the no-version `DELETE /api/memories/{fact_id}` compatibility behavior. Version-aware clients use the dedicated read/correct/audit routes and may add `expected_version` to DELETE; do not silently make legacy callers supply a version.
- Resolve every versioned fact HTTP owner exclusively from the authenticated `Principal`. A request body, query, path, model output, or stored content must never select or override owner scope. Active list/detail reads and every mutation stay owner-scoped; missing, deleted, and cross-owner facts are indistinguishable as a content-free 404.
- Versioned correction requires explicit approval and expected-version CAS. Normalize unauthenticated, unapproved, missing/cross-owner/deleted, and stale requests to 401, 403, 404, and 409 respectively; validation remains 422. Error bodies must not contain owner, key, current value, submitted value, or current version.
- Public fact audit exposes only fact ID, version, created/corrected/deleted action, and the validated lowercase SHA-256 value digest. It may remain readable by the fact owner after tombstone deletion, but must never expose owner, key, value, timestamps, or database details.
- HTTP handlers call only the bounded async Memory façade and remain inside application admission/lifespan ownership. A timeout, cancellation, or connection break during correction/delete can still be result-unknown; clients reconcile with current version/audit and must not automatically retry without a durable mutation idempotency key.

## 27. Fixed RAG Retrieval Evaluation

- Fixed retrieval evaluation lives in the explicit `backend.app.evals.rag_retrieval` module and never runs during application import, Container construction, or FastAPI lifespan. Its default path is deterministic, offline, network-free, and independent of provider secrets.
- The repository-owned fixture uses the strict `rag-retrieval-dataset-v1` schema, a stable version, a canonical-JSON SHA-256 content digest, bounded documents, and at least 50 uniquely identified cases. The digest must be independent of whitespace and checkout line endings. Each case names only existing relevant documents and evidence terms that are actually present in those relevant documents.
- Keep `top_k` and per-retriever Recall@K, mean reciprocal rank, and grounding-accuracy thresholds in the versioned fixture. A result below any threshold fails the evaluation command; do not add unrelated documents or text to hide a miss. A corrected fixture requires an explicit version change and a new recorded digest.
- Recall@K is macro-averaged over annotated relevant document IDs. MRR uses the first relevant rank. Grounding is correct only when every annotated evidence term appears in retrieved excerpts from a relevant document; an unrelated excerpt containing the term cannot satisfy the check.
- Reports expose only reviewed dataset/retriever labels, case IDs, configured document IDs, metrics, thresholds, local latency scope, and stable failure codes. Queries, evidence terms, excerpts, titles, sources, and unconfigured returned document IDs do not enter report records or normal representations.
- Local wall-clock latency is a same-process comparison only. Provider usage remains unavailable and estimated cost remains `None`; sparse or deterministic pgvector fixture results are not online semantic quality, tokenizer, billing, or production-capacity evidence.
- The first M11-T6 slice fixes the shared evaluator and sparse baseline only. Real pgvector comparison must reuse the exact dataset version, digest, annotations, `top_k`, and thresholds before M11-T6 can close; optional reranking may be added only as a separately identified retriever.

## 28. Layered Verification and CI

- The stable verification layers are `offline`, `mcp`, `postgresql`, `frontend`, `e2e`, `docker`, and `online`. The default profile selects only the key-free, DSN-free `offline + mcp + frontend` gate.
- Every layer appears in the final summary as `PASSED`, `FAILED`, or `SKIPPED` with a stable reason. A required failure must return non-zero and must never reach an all-passed message; unselected or unauthorized work is not success evidence.
- Explicit `postgresql`, `e2e`, and `docker` profiles fail closed when their DSN, browser, executable, or dependency prerequisite is missing. Only the online layer may skip because one-time authorization is absent.
- Default CI has read-only repository permissions, references no repository secret, and never supplies online authorization. Its online-policy job proves only the explicit skip path, not Provider compatibility.
- PostgreSQL CI uses only the workflow-owned localhost trust test service. Docker verification in M13-T3 is configuration-only; image build, service startup, health, migration, Nginx SSE, and restart evidence remain M13-T4.
- A checked-in workflow and local profile success are not proof that remote CI ran. Until a remote workflow run is recorded, keep M13-T3 `code_complete` and `KI-008` open or mitigated.
