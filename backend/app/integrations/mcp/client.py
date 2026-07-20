from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Mapping
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, ListToolsResult, Tool

from backend.app.integrations.mcp.config import McpServerConfig
from backend.app.integrations.mcp.tools import (
    McpToolInvocationError,
    McpToolMappingError,
    map_discovered_tools,
    normalize_arguments,
    normalize_call_result,
)
from backend.app.settings import McpClientSettings
from backend.app.tools import ToolDefinition


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
    requests: asyncio.Queue[_McpRequest]
    task: asyncio.Task[None] | None = None


@dataclass
class _McpRequest:
    kind: Literal["list_tools", "call_tool"]
    response: asyncio.Future[object]
    cursor: str | None = None
    remote_name: str | None = None
    arguments: dict[str, Any] | None = None


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
        self._connections_by_id: dict[str, _McpConnection] = {}
        self._connections: list[_McpConnection] = []
        self._sessions: dict[str, ClientSession] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
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
        self._loop = asyncio.get_running_loop()
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

    async def discover_tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """Discover allowed tools and map them to shared definitions."""

        definitions: list[ToolDefinition] = []
        local_names: set[str] = set()
        for config in self._configs:
            discovered = await self._list_all_tools(config.server_id)
            mapped = map_discovered_tools(
                server_id=config.server_id,
                discovered=discovered,
                policies=config.tool_policies,
                invoke=self._invoke_tool_sync,
            )
            for definition in mapped:
                if definition.name in local_names:
                    raise McpToolMappingError(
                        server_id=config.server_id,
                        code="local_name_conflict",
                    )
                local_names.add(definition.name)
                definitions.append(definition)
        return tuple(definitions)

    async def call_tool(
        self,
        server_id: str,
        remote_name: str,
        arguments: dict[str, Any],
    ) -> object:
        connection = self._connections_by_id.get(server_id)
        if (
            connection is None
            or remote_name not in connection.config.tool_policies
        ):
            raise McpToolInvocationError(
                server_id=server_id,
                code="tool_not_allowed",
            )
        try:
            normalized_arguments = normalize_arguments(arguments)
        except ValueError:
            raise McpToolInvocationError(
                server_id=server_id,
                code="invalid_arguments",
            ) from None
        response = await self._submit_request(
            server_id,
            kind="call_tool",
            remote_name=remote_name,
            arguments=normalized_arguments,
        )
        if not isinstance(response, CallToolResult):
            raise McpToolInvocationError(
                server_id=server_id,
                code="invalid_response",
            )
        try:
            return normalize_call_result(response, server_id=server_id)
        except McpToolInvocationError:
            raise
        except ValueError:
            raise McpToolInvocationError(
                server_id=server_id,
                code="untrusted_tool_result",
            ) from None

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
            requests=asyncio.Queue(),
        )
        connection.task = asyncio.create_task(
            self._run_connection(connection),
            name=f"mcp-client-{config.server_id}",
        )
        self._connections.append(connection)
        self._connections_by_id[config.server_id] = connection
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
                        await self._serve_requests(connection, session)
        except OSError:
            self._set_connection_error(connection, "process_unavailable")
        except asyncio.CancelledError:
            if not connection.ready.done():
                connection.ready.cancel()
            raise
        except Exception:
            self._set_connection_error(connection, "protocol_error")
        finally:
            self._fail_queued_requests(connection, "client_closed")

    async def _serve_requests(
        self,
        connection: _McpConnection,
        session: ClientSession,
    ) -> None:
        while not connection.stop_requested.is_set():
            requested = asyncio.create_task(connection.requests.get())
            stopped = asyncio.create_task(connection.stop_requested.wait())
            done, _pending = await asyncio.wait(
                {requested, stopped},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stopped in done:
                if requested in done:
                    self._set_request_error(
                        connection,
                        requested.result(),
                        "client_closed",
                    )
                else:
                    requested.cancel()
                    await self._consume_task(requested)
                return
            stopped.cancel()
            await self._consume_task(stopped)
            request = requested.result()
            if request.response.cancelled():
                continue
            try:
                async with asyncio.timeout(
                    self._settings.request_timeout_ms / 1000
                ):
                    if request.kind == "list_tools":
                        result: object = await session.list_tools(
                            cursor=request.cursor
                        )
                    else:
                        assert request.remote_name is not None
                        result = await session.call_tool(
                            request.remote_name,
                            request.arguments,
                        )
            except TimeoutError:
                self._set_request_error(
                    connection,
                    request,
                    "request_timeout",
                )
            except Exception:
                self._set_request_error(
                    connection,
                    request,
                    "request_failed",
                )
            else:
                if not request.response.done():
                    request.response.set_result(result)

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
            self._connections_by_id.clear()
            self._connections.clear()
            self._sessions.clear()
            self._loop = None

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

    def _set_request_error(
        self,
        connection: _McpConnection,
        request: _McpRequest,
        code: str,
    ) -> None:
        if not request.response.done():
            request.response.set_exception(
                McpToolInvocationError(
                    server_id=connection.config.server_id,
                    code=code,
                )
            )

    def _fail_queued_requests(
        self,
        connection: _McpConnection,
        code: str,
    ) -> None:
        while not connection.requests.empty():
            request = connection.requests.get_nowait()
            self._set_request_error(connection, request, code)

    async def _list_all_tools(self, server_id: str) -> tuple[Tool, ...]:
        tools: list[Tool] = []
        seen_cursors: set[str] = set()
        cursor: str | None = None
        for _page in range(8):
            response = await self._submit_request(
                server_id,
                kind="list_tools",
                cursor=cursor,
            )
            if not isinstance(response, ListToolsResult):
                raise McpToolMappingError(
                    server_id=server_id,
                    code="invalid_discovery_response",
                )
            if len(response.tools) > 128 or len(tools) + len(response.tools) > 256:
                raise McpToolMappingError(
                    server_id=server_id,
                    code="discovery_limit_exceeded",
                )
            tools.extend(response.tools)
            next_cursor = response.nextCursor
            if next_cursor is None:
                return tuple(tools)
            if (
                not next_cursor
                or next_cursor != next_cursor.strip()
                or len(next_cursor) > 512
                or any(not character.isprintable() for character in next_cursor)
            ):
                raise McpToolMappingError(
                    server_id=server_id,
                    code="invalid_discovery_cursor",
                )
            if next_cursor in seen_cursors:
                raise McpToolMappingError(
                    server_id=server_id,
                    code="discovery_cursor_loop",
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise McpToolMappingError(
            server_id=server_id,
            code="discovery_limit_exceeded",
        )

    async def _submit_request(
        self,
        server_id: str,
        *,
        kind: Literal["list_tools", "call_tool"],
        cursor: str | None = None,
        remote_name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> object:
        loop = asyncio.get_running_loop()
        if (
            self._state != McpClientState.RUNNING
            or self._loop is not loop
            or server_id not in self._connections_by_id
        ):
            raise McpToolInvocationError(
                server_id=server_id,
                code="client_not_running",
            )
        response = loop.create_future()
        request = _McpRequest(
            kind=kind,
            response=response,
            cursor=cursor,
            remote_name=remote_name,
            arguments=arguments,
        )
        self._connections_by_id[server_id].requests.put_nowait(request)
        try:
            async with asyncio.timeout(
                self._settings.request_timeout_ms / 1000
            ):
                return await response
        except TimeoutError:
            raise McpToolInvocationError(
                server_id=server_id,
                code="request_timeout",
            ) from None

    def _invoke_tool_sync(
        self,
        server_id: str,
        remote_name: str,
        arguments: dict[str, Any],
    ) -> object:
        loop = self._loop
        if self._state != McpClientState.RUNNING or loop is None:
            raise ValueError("MCP client is not running")
        try:
            if asyncio.get_running_loop() is loop:
                raise ValueError("MCP tool handler cannot block its owner loop")
        except RuntimeError:
            pass
        future = asyncio.run_coroutine_threadsafe(
            self.call_tool(server_id, remote_name, arguments),
            loop,
        )
        try:
            return future.result(
                timeout=(self._settings.request_timeout_ms / 1000) + 1
            )
        except FutureTimeoutError:
            future.cancel()
            raise TimeoutError("MCP tool call timed out") from None
        except McpToolInvocationError as error:
            if error.code == "request_timeout":
                raise TimeoutError("MCP tool call timed out") from None
            raise ValueError("MCP tool call failed") from None

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
