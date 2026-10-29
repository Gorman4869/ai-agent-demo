"""Explicit loopback-only synthetic review demo; no credentials or Provider calls."""
from __future__ import annotations

import os
import struct
import zlib

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.app.advanced.browser_agent import BrowserAgent
from backend.app.advanced.browser_driver import BrowserFixtureSite, PlaywrightBrowserDriver
from backend.app.advanced.browser_network import BrowserNetworkPolicy, StaticBrowserAddressResolver
from backend.app.advanced.multimodal import MultimodalVisionAgent, OfflineVisionModel
from backend.app.advanced.review_application import create_review_app
from backend.app.advanced.review_publication import InMemoryReviewPublicationStore
from backend.app.advanced.postgres_review_application import create_postgres_review_app
from backend.app.advanced.postgres_review_publication import PostgresReviewPublicationStore
from backend.app.advanced.review_tools import (
    AsyncReviewToolRegistry, BrowserReviewPageReader, ReviewImageAsset, ReviewPageFixture, ReviewPublisher, ReviewResourceCatalog,
    create_multisource_review_registry,
)
from backend.app.knowledge import Document, InMemoryKnowledgeBase
from backend.app.security import Principal, StaticTokenAuthenticator
from backend.app.settings import Settings


_OWNER = "local-review-demo"
_ORIGIN = "https://review.demo.test"


class _LocalDemoIdentity(StaticTokenAuthenticator):
    def authenticate(self, authorization: str | None) -> Principal:
        return Principal(_OWNER, roles=frozenset({"reviewer"}))


def create_demo_review_app() -> FastAPI:
    """Synthetic local identity only; never mount this factory in production."""
    registry = _demo_registry(InMemoryReviewPublicationStore({(_OWNER, "demo-review"): 1}))
    return _loopback_only(create_review_app(registry=registry, authenticator=_LocalDemoIdentity()))


def create_postgres_demo_review_app() -> FastAPI:
    """Explicit local PostgreSQL demo; read only its operator-supplied DSN file."""
    settings = Settings.from_environment({
        "AI_AGENT_PERSISTENCE": "postgres",
        "AI_AGENT_POSTGRES_DSN_FILE": os.environ.get("AI_AGENT_REVIEW_DEMO_DSN_FILE", ""),
    })
    app = create_postgres_review_app(
        settings=settings,
        registry_factory=lambda persistence: _demo_registry(
            PostgresReviewPublicationStore(persistence.pool, {(_OWNER, "demo-review"): 1}),
        ),
        authenticator=_LocalDemoIdentity(),
    )
    return _loopback_only(app)


def _demo_registry(publisher: ReviewPublisher) -> AsyncReviewToolRegistry:
    knowledge = InMemoryKnowledgeBase()
    knowledge.add(Document(
        id="review-disclosure", title="合成资料审查规则",
        content="review disclosure: verify the image, policy and page before publication. Exact human approval is required.",
        source="policy://local-demo/disclosure",
    ))
    site = BrowserFixtureSite(_ORIGIN, {
        "/facts": "<!doctype html><html><head><title>合成商品资料</title></head>"
        "<body><main data-agent-id='facts'>Synthetic review disclosure fixture. "
        "No personal data, public network or external publication.</main></body></html>",
    })
    driver = PlaywrightBrowserDriver(
        site, network_policy=BrowserNetworkPolicy(
            StaticBrowserAddressResolver({"review.demo.test": ("93.184.216.34",)})
        ),
    )
    return create_multisource_review_registry(
        catalog=ReviewResourceCatalog(
            images={"demo-image": ReviewImageAsset("demo-image", _OWNER, _demo_png())},
            pages={"demo-page": ReviewPageFixture("demo-page", _OWNER, _ORIGIN + "/facts")},
        ),
        vision_agent=MultimodalVisionAgent(OfflineVisionModel(), timeout_ms=1_000),
        knowledge_base=knowledge,
        page_reader=BrowserReviewPageReader(BrowserAgent(allowed_origins=[_ORIGIN]), driver),
        publisher=publisher,
    )


def _loopback_only(app: FastAPI) -> FastAPI:
    app.title = "Loopback synthetic review demo (no login)"
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def loopback_only(request: Request, call_next):
        if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
            return JSONResponse(status_code=403, content={"detail": "Local demo accepts loopback clients only"})
        return await call_next(request)

    return app


def _demo_png() -> bytes:
    width, height = 64, 32
    pixels = b"".join(b"\x00" + b"\x40\x70\x90" * width for _ in range(height))
    chunks = [(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
              (b"IDAT", zlib.compress(pixels)), (b"IEND", b"")]
    return b"\x89PNG\r\n\x1a\n" + b"".join(
        struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        for kind, data in chunks
    )


def main() -> None:
    import uvicorn

    uvicorn.run("backend.app.review_demo:create_demo_review_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
