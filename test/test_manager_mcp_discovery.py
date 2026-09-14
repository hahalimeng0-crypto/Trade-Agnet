import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "manager"))
sys.path.insert(0, str(ROOT))

import launcher
from agent.tools.mcp_server import MCPClientManager


class ManagerMcpDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_manager_lists_configured_and_discovered_servers(self):
        payload = await launcher.list_mcp_servers()
        servers = {item["name"]: item for item in payload["servers"]}
        self.assertTrue(servers["foreign_trade_inquiry"]["configured"])
        self.assertTrue(servers["trade_rag"]["configured"])
        self.assertTrue(servers["trade_rag"]["entry_exists"])
        self.assertTrue(servers["poetry"]["detected"])
        self.assertFalse(servers["poetry"]["configured"])

    async def test_trade_rag_mcp_stdio_handshake(self):
        manager = MCPClientManager({
            "trade_rag": {"command": "{python}", "args": ["-m", "trade_rag.server"]}
        })
        try:
            await manager.connect_all(timeout=10)
            self.assertIn("trade_rag__search_enterprise_knowledge", [tool.name for tool in manager.get_tools()])
        finally:
            await manager.shutdown()

    async def test_foreign_trade_mcp_stdio_handshake(self):
        manager = MCPClientManager({
            "foreign_trade_inquiry": {
                "command": "{python}",
                "args": ["-m", "mcp_servers.foreign_trade_inquiry_server"],
            }
        })
        try:
            await manager.connect_all(timeout=10)
            tool_names = [tool.name for tool in manager.get_tools()]
            self.assertIn("foreign_trade_inquiry__extract_rfq", tool_names)
            self.assertIn("foreign_trade_inquiry__search_product_catalog", tool_names)
            self.assertIn("foreign_trade_inquiry__query_trade_data", tool_names)
            self.assertEqual(len(tool_names), 8)
        finally:
            await manager.shutdown()


if __name__ == "__main__":
    unittest.main()
