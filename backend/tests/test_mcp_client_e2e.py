from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from backend.app.integrations.mcp import (
    McpClientManager,
    McpClientState,
    McpToolInvocationError,
    default_mcp_server_configs,
)
from backend.app.settings import McpClientSettings
from backend.app.tools import ToolRegistry


_SERVER_ID = "typescript-knowledge"
_LOCAL_TOOL_NAME = "mcp_typescript_knowledge_lookup_concept"


class McpTypescriptServerCatalogTest(unittest.TestCase):
    def test_catalog_owns_typescript_command_and_tool_policy(self) -> None:
        config = default_mcp_server_configs()[_SERVER_ID]
        project_root = Path(__file__).resolve().parents[2]
        expected_root = project_root / "mcp-servers" / "knowledge-server"

        self.assertEqual("node", config.command)
        self.assertEqual(("build/index.js",), config.args)
        self.assertEqual(expected_root, config.cwd)
        self.assertTrue((expected_root / config.args[0]).is_file())
        self.assertEqual(
            _LOCAL_TOOL_NAME,
            config.tool_policies["lookup_concept"].local_name,
        )


class McpTypescriptServerE2ETest(unittest.IsolatedAsyncioTestCase):
    async def test_discovers_normalized_shared_tool_over_stdio(self) -> None:
        manager = self._manager()
        await manager.start()
        try:
            definitions = await manager.discover_tool_definitions()

            self.assertEqual((_SERVER_ID,), manager.connected_server_ids)
            self.assertEqual(1, len(definitions))
            self.assertEqual(_LOCAL_TOOL_NAME, definitions[0].name)
            self.assertEqual(
                {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 1}
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                definitions[0].input_schema,
            )
        finally:
            await manager.close()

        self.assertEqual(McpClientState.CLOSED, manager.state)
        self.assertEqual((), manager.connected_server_ids)

    async def test_calls_known_and_unknown_concepts_through_registry(
        self,
    ) -> None:
        manager = self._manager()
        await manager.start()
        try:
            registry = ToolRegistry()
            for definition in await manager.discover_tool_definitions():
                registry.register(definition)

            known = await asyncio.to_thread(
                registry.execute,
                _LOCAL_TOOL_NAME,
                {"name": " MCP "},
            )
            unknown = await asyncio.to_thread(
                registry.execute,
                _LOCAL_TOOL_NAME,
                {"name": "missing"},
            )

            self.assertTrue(known.ok)
            self.assertEqual(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "MCP 用统一协议连接 Agent 客户端与外部工具、"
                                "资源和提示。"
                            ),
                        }
                    ]
                },
                known.value,
            )
            self.assertTrue(unknown.ok)
            self.assertEqual(
                {
                    "content": [
                        {"type": "text", "text": "未找到该概念"}
                    ]
                },
                unknown.value,
            )
        finally:
            await manager.close()

    async def test_invalid_protocol_arguments_fail_stably(self) -> None:
        manager = self._manager()
        await manager.start()
        try:
            with self.assertRaises(McpToolInvocationError) as raised:
                await manager.call_tool(
                    _SERVER_ID,
                    "lookup_concept",
                    {"name": 42},
                )

            self.assertEqual("remote_tool_error", raised.exception.code)
            self.assertEqual(
                "MCP server 'typescript-knowledge' tool call failed with "
                "remote_tool_error",
                str(raised.exception),
            )

            with self.assertRaises(McpToolInvocationError) as unlisted:
                await manager.call_tool(
                    _SERVER_ID,
                    "unlisted_tool",
                    {"name": "mcp"},
                )
            self.assertEqual("tool_not_allowed", unlisted.exception.code)
        finally:
            await manager.close()

    def _manager(self) -> McpClientManager:
        return McpClientManager(
            settings=McpClientSettings(server_ids=(_SERVER_ID,)),
            allowed_servers=default_mcp_server_configs(),
        )


if __name__ == "__main__":
    unittest.main()
