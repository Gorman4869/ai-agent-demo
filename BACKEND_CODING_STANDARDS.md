# Backend Coding Standards

## 1. Project Basics

- Language: Python 3.11+ syntax; verified with Python 3.12.10.
- Frameworks: FastAPI for HTTP, LangGraph for explicit state workflows, OpenAI Agents SDK for the SDK comparison, and MCP SDK for protocol labs.
- Dependency management: project-local `.venv` with direct versions locked in `backend/requirements-m2.txt`.
- Layers: `domain` owns stable types, `models` owns model adapters, `tools` owns tool contracts, `knowledge` owns retrieval, `memory` owns memory policies, `services` owns use cases, `agent` owns orchestration, `observability` owns run summaries, and `evals` owns offline behavior checks.

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
