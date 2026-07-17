from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from backend.app.integrations.mcp.config import McpServerConfig
from backend.app.settings import McpClientSettings


class _SafeStdioLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage().startswith(
            "Failed to parse JSONRPC message from server"
        ):
            record.msg = "MCP server sent invalid JSON-RPC"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


logging.getLogger("mcp.client.stdio").addFilter(_SafeStdioLogFilter())


class McpClientState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class McpClientConfigurationError(ValueError):
    """Raised before process startup for an unknown server-owned selector."""

    def __init__(self, server_id: str) -> None:
        self.code = "server_not_allowed"
        self.server_id = server_id
        super().__init__(f"MCP server '{server_id}' is not allowed")


class McpClientLifecycleError(RuntimeError):
    """Safe process or protocol failure without raw command/error details."""

    def __init__(self, *, server_id: str, code: str) -> None:
        self.code = code
        self.server_id = server_id
        super().__init__(f"MCP server '{server_id}' failed with {code}")


@dataclass
class _McpConnection:
    config: McpServerConfig
    stop_requested: asyncio.Event
    ready: asyncio.Future[ClientSession]
    task: asyncio.Task[None] | None = None


class McpClientManager:
    """Own MCP STDIO sessions for one application lifespan."""

    def __init__(
        self,
        *,
        settings: McpClientSettings,
        allowed_servers: Mapping[str, McpServerConfig],
    ) -> None:
        self._settings = settings
        self._configs = self._select_configs(allowed_servers)
        self._connections: list[_McpConnection] = []
        self._sessions: dict[str, ClientSession] = {}
        self._state = McpClientState.CREATED
        self._failure_code: str | None = None

    @property
    def state(self) -> McpClientState:
        return self._state

    @property
    def failure_code(self) -> str | None:
        return self._failure_code

    @property
    def connected_server_ids(self) -> tuple[str, ...]:
        return tuple(self._sessions)

    async def start(self) -> None:
        if self._state == McpClientState.RUNNING:
            return
        if self._state != McpClientState.CREATED:
            raise McpClientLifecycleError(
                server_id="lifecycle",
                code="invalid_state",
            )

        self._state = McpClientState.STARTING
        try:
            for config in self._configs:
                await self._start_connection(config)
        except asyncio.CancelledError:
            self._failure_code = "startup_cancelled"
            try:
                await self._stop_connections()
            finally:
                self._state = McpClientState.CLOSED
            raise
        except McpClientLifecycleError as error:
            self._failure_code = error.code
            try:
                await self._stop_connections()
            finally:
                self._state = McpClientState.FAILED
            raise

        self._state = McpClientState.RUNNING

    async def close(self) -> None:
        if self._state == McpClientState.CLOSED:
            return
        if self._state == McpClientState.CREATED:
            self._state = McpClientState.CLOSED
            return
        if self._state != McpClientState.RUNNING:
            raise McpClientLifecycleError(
                server_id="lifecycle",
                code="invalid_state",
            )

        self._state = McpClientState.CLOSING
        try:
            await self._stop_connections()
        except asyncio.CancelledError:
            self._failure_code = "shutdown_cancelled"
            self._state = McpClientState.FAILED
            raise
        except Exception:
            self._failure_code = "shutdown_failed"
            self._state = McpClientState.FAILED
            raise McpClientLifecycleError(
                server_id="lifecycle",
                code="shutdown_failed",
            ) from None
        self._state = McpClientState.CLOSED

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        await self.start()
        try:
            yield
        finally:
            await self.close()

    async def _start_connection(self, config: McpServerConfig) -> None:
        loop = asyncio.get_running_loop()
        connection = _McpConnection(
            config=config,
            stop_requested=asyncio.Event(),
            ready=loop.create_future(),
        )
        connection.task = asyncio.create_task(
            self._run_connection(connection),
            name=f"mcp-client-{config.server_id}",
        )
        self._connections.append(connection)
        try:
            async with asyncio.timeout(
                self._settings.startup_timeout_ms / 1000
            ):
                session = await connection.ready
        except TimeoutError:
            raise McpClientLifecycleError(
                server_id=config.server_id,
                code="startup_timeout",
            ) from None
        self._sessions[config.server_id] = session

    async def _run_connection(self, connection: _McpConnection) -> None:
        config = connection.config
        parameters = StdioServerParameters(
            command=config.command,
            args=list(config.args),
            cwd=config.cwd,
        )
        try:
            with open(os.devnull, "w", encoding="utf-8") as errlog:
                async with stdio_client(parameters, errlog=errlog) as streams:
                    async with ClientSession(*streams) as session:
                        initialized = asyncio.create_task(session.initialize())
                        stopped = asyncio.create_task(
                            connection.stop_requested.wait()
                        )
                        done, _pending = await asyncio.wait(
                            {initialized, stopped},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if stopped in done:
                            initialized.cancel()
                            await self._consume_task(initialized)
                            return
                        stopped.cancel()
                        await self._consume_task(stopped)
                        await initialized
                        if not connection.ready.done():
                            connection.ready.set_result(session)
                        await connection.stop_requested.wait()
        except OSError:
            self._set_connection_error(connection, "process_unavailable")
        except asyncio.CancelledError:
            if not connection.ready.done():
                connection.ready.cancel()
            raise
        except Exception:
            self._set_connection_error(connection, "protocol_error")

    async def _stop_connections(self) -> None:
        for connection in self._connections:
            connection.stop_requested.set()
        tasks = tuple(
            connection.task
            for connection in self._connections
            if connection.task is not None
        )
        try:
            if tasks:
                cleanup = asyncio.gather(*tasks, return_exceptions=True)
                try:
                    results = await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await cleanup
                    raise
                if any(
                    isinstance(result, BaseException) for result in results
                ):
                    raise McpClientLifecycleError(
                        server_id="lifecycle",
                        code="shutdown_failed",
                    )
        finally:
            self._connections.clear()
            self._sessions.clear()

    def _set_connection_error(
        self,
        connection: _McpConnection,
        code: str,
    ) -> None:
        if not connection.ready.done():
            connection.ready.set_exception(
                McpClientLifecycleError(
                    server_id=connection.config.server_id,
                    code=code,
                )
            )

    async def _consume_task(self, task: asyncio.Task[object]) -> None:
        try:
            await task
        except BaseException:
            return

    def _select_configs(
        self,
        allowed_servers: Mapping[str, McpServerConfig],
    ) -> tuple[McpServerConfig, ...]:
        selected: list[McpServerConfig] = []
        for server_id in self._settings.server_ids:
            config = allowed_servers.get(server_id)
            if config is None or config.server_id != server_id:
                raise McpClientConfigurationError(server_id)
            selected.append(config)
        return tuple(selected)
