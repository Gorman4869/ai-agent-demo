from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from time import perf_counter

from backend.app.container import create_embedding_model
from backend.app.knowledge import (
    DashScopePgVectorKnowledgeBase,
    Document,
    EmbeddingError,
    EmbeddingUsage,
    create_psycopg_connection_factory,
)
from backend.app.settings import Settings, SettingsError


_DSN_ENVIRONMENT = "AI_AGENT_TEST_PGVECTOR_DSN"
_SMOKE_DOCUMENT_ID = "m11-t7-dashscope-embedding-smoke"
_SMOKE_DOCUMENT = Document(
    id=_SMOKE_DOCUMENT_ID,
    title="DashScope Embedding Smoke",
    source="course/m11-t7-dashscope-smoke.md",
    content="DashScope text-embedding-v4 converts a short course note into a vector.",
)
_SMOKE_QUERY = "How does DashScope create an embedding vector?"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicitly authorized DashScope embedding smoke check."
    )
    parser.add_argument("--authorized", action="store_true")
    arguments = parser.parse_args()
    if not arguments.authorized:
        print(json.dumps({"error_code": "online_authorization_required"}))
        return 2

    dsn = os.environ.get(_DSN_ENVIRONMENT, "").strip()
    if not dsn:
        print(json.dumps({"error_code": "pgvector_dsn_required"}))
        return 2
    try:
        settings = Settings.from_environment()
    except SettingsError as error:
        print(json.dumps({"error_code": str(error)}))
        return 2
    if (
        settings.embedding.provider != "dashscope"
        or settings.embedding.batch_size != 1
        or settings.embedding.max_retries != 0
    ):
        print(json.dumps({"error_code": "dashscope_smoke_settings_invalid"}))
        return 2

    usages: list[EmbeddingUsage] = []
    started_at = perf_counter()
    knowledge = DashScopePgVectorKnowledgeBase(
        create_psycopg_connection_factory(dsn),
        create_embedding_model(settings, usage_sink=usages.append),
        chunk_size=160,
        overlap=30,
    )
    document_written = False
    cleanup_completed = False
    payload: dict[str, object] | None = None
    exit_code = 1
    try:
        knowledge.initialize_schema()
        document_written = knowledge.add(_SMOKE_DOCUMENT) > 0
        results = knowledge.search(_SMOKE_QUERY, limit=1)
        if (
            len(results) != 1
            or results[0].citation.document_id != _SMOKE_DOCUMENT_ID
        ):
            payload = {"error_code": "dashscope_smoke_query_failed"}
        else:
            payload = {
                "provider": settings.embedding.provider,
                "model": settings.embedding.model,
                "dimensions": settings.embedding.dimensions,
                "batch_size": settings.embedding.batch_size,
                "provider_requests": len(usages),
                "input_tokens": sum(usage.input_tokens for usage in usages),
                "total_tokens": sum(usage.total_tokens for usage in usages),
                "elapsed_ms": round((perf_counter() - started_at) * 1_000),
                "cost_usd": None,
                "cost_source": "unknown",
            }
            exit_code = 0
    except EmbeddingError as error:
        payload = {"error_code": str(error)}
    except Exception:
        payload = {"error_code": "dashscope_smoke_failed"}
    finally:
        if document_written:
            try:
                cleanup_completed = knowledge.delete(_SMOKE_DOCUMENT_ID)
            except Exception:
                cleanup_completed = False
        if document_written and not cleanup_completed:
            payload = {"error_code": "dashscope_smoke_cleanup_failed"}
            exit_code = 1
    print(json.dumps(payload, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
