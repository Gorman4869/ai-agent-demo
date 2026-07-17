from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.container import ApplicationContainer
from backend.app.integrations.mcp import (
    McpClientConfigurationError,
    McpClientLifecycleError,
    McpClientManager,
    McpClientState,
    McpServerConfig,
    default_mcp_server_configs,
)
from backend.app.main import create_app
from backend.app.settings import McpClientSettings, Settings


class McpServerConfigurationTest(unittest.TestCase):
    def test_server_config_rejects_unstable_ids_commands_and_cwd(self) -> None:
        cases = (
            {"server_id": "Bad ID", "command": sys.executable},
            {"server_id": "safe-id", "command": "bad\ncommand"},
            {
                "server_id": "safe-id",
                "command": sys.executable,
                "args": ("bad\x00argument",),
            },
            {
                "server_id": "safe-id",
                "command": sys.executable,
                "cwd": Path("relative"),
            },
        )

        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    McpServerConfig(**values)

    def test_unknown_selector_is_rejected_without_accepting_a_command(self) -> None:
        settings = McpClientSettings(server_ids=("request-command",))

        with self.assertRaises(McpClientConfigurationError) as raised:
            McpClientManager(settings=settings, allowed_servers={})

        self.assertEqual("server_not_allowed", raised.exception.code)
        self.assertEqual("request-command", raised.exception.server_id)


class McpClientLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_server_selection_has_no_process_lifecycle(self) -> None:
        manager = McpClientManager(
            settings=McpClientSettings(),
            allowed_servers={},
        )

        await manager.start()
        self.assertEqual(McpClientState.RUNNING, manager.state)
        self.assertEqual((), manager.connected_server_ids)
        await manager.close()

        self.assertEqual(McpClientState.CLOSED, manager.state)

    async def test_missing_process_has_safe_stable_diagnostic(self) -> None:
        secret_command = "missing-mcp-command-with-secret-fragment"
        manager = self._manager(
            McpServerConfig(
                server_id="missing-process",
                command=secret_command,
                cwd=Path.cwd().resolve(),
            )
        )

        with self.assertRaises(McpClientLifecycleError) as raised:
            await manager.start()

        self.assertEqual("process_unavailable", raised.exception.code)
        self.assertEqual(McpClientState.FAILED, manager.state)
        self.assertEqual("process_unavailable", manager.failure_code)
        self.assertNotIn(secret_command, str(raised.exception))

    async def test_server_that_never_initializes_hits_startup_timeout(self) -> None:
        manager = self._manager(
            self._python_server(
                "slow-server",
                "import sys; sys.stdin.buffer.read()",
            ),
            timeout_ms=100,
        )

        with self.assertRaises(McpClientLifecycleError) as raised:
            await manager.start()

        self.assertEqual("startup_timeout", raised.exception.code)
        self.assertEqual(McpClientState.FAILED, manager.state)
        self.assertEqual((), manager.connected_server_ids)

    async def test_invalid_stdio_protocol_has_stable_diagnostic(self) -> None:
        manager = self._manager(
            self._python_server(
                "invalid-protocol",
                "print('not-json', flush=True)",
            ),
            timeout_ms=2_000,
        )

        with self.assertLogs("mcp.client.stdio", level="ERROR") as captured:
            with self.assertRaises(McpClientLifecycleError) as raised:
                await manager.start()

        self.assertEqual("protocol_error", raised.exception.code)
        self.assertEqual(McpClientState.FAILED, manager.state)
        self.assertEqual((), manager.connected_server_ids)
        self.assertEqual(
            ["ERROR:mcp.client.stdio:MCP server sent invalid JSON-RPC"],
            captured.output,
        )
        self.assertNotIn("not-json", "\n".join(captured.output))

    async def test_cancelled_startup_cleans_partial_transport(self) -> None:
        manager = self._manager(
            self._python_server(
                "cancelled-server",
                "import sys; sys.stdin.buffer.read()",
            ),
            timeout_ms=30_000,
        )
        startup = asyncio.create_task(manager.start())
        await asyncio.sleep(0.1)

        startup.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await startup

        self.assertEqual(McpClientState.CLOSED, manager.state)
        self.assertEqual("startup_cancelled", manager.failure_code)
        self.assertEqual((), manager.connected_server_ids)

    async def test_later_startup_failure_closes_initialized_servers(self) -> None:
        allowed_servers = dict(default_mcp_server_configs())
        missing = McpServerConfig(
            server_id="missing-second",
            command="missing-second-mcp-process",
            cwd=Path.cwd().resolve(),
        )
        allowed_servers[missing.server_id] = missing
        manager = McpClientManager(
            settings=McpClientSettings(
                server_ids=("python-knowledge", missing.server_id),
            ),
            allowed_servers=allowed_servers,
        )

        with self.assertRaises(McpClientLifecycleError) as raised:
            await manager.start()

        self.assertEqual("process_unavailable", raised.exception.code)
        self.assertEqual(McpClientState.FAILED, manager.state)
        self.assertEqual((), manager.connected_server_ids)

    def _manager(
        self,
        config: McpServerConfig,
        *,
        timeout_ms: int = 5_000,
    ) -> McpClientManager:
        return McpClientManager(
            settings=McpClientSettings(
                server_ids=(config.server_id,),
                startup_timeout_ms=timeout_ms,
            ),
            allowed_servers={config.server_id: config},
        )

    def _python_server(self, server_id: str, source: str) -> McpServerConfig:
        return McpServerConfig(
            server_id=server_id,
            command=sys.executable,
            args=("-X", "utf8", "-B", "-c", source),
            cwd=Path.cwd().resolve(),
        )


class McpFastApiLifespanTest(unittest.TestCase):
    def test_fastapi_lifespan_initializes_real_sdk_session_and_closes_it(
        self,
    ) -> None:
        settings = Settings.from_environment(
            {"AI_AGENT_MCP_SERVERS": "python-knowledge"}
        )
        container = ApplicationContainer.create(
            settings=settings,
            mcp_server_configs=default_mcp_server_configs(),
        )
        app = create_app(container=container)

        with TestClient(app) as client:
            self.assertEqual({"status": "ok"}, client.get("/health").json())
            self.assertEqual(McpClientState.RUNNING, container.mcp_clients.state)
            self.assertEqual(
                ("python-knowledge",),
                container.mcp_clients.connected_server_ids,
            )

        self.assertEqual(McpClientState.CLOSED, container.mcp_clients.state)
        self.assertEqual((), container.mcp_clients.connected_server_ids)


if __name__ == "__main__":
    unittest.main()
