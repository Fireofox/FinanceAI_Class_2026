import json
import sys
import unittest
from datetime import datetime, timedelta, timezone

from simple_agent.mcp_client import MCPManager


class ClockServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_and_call_system_datetime_over_stdio(self):
        config = {
            "clock": {
                "command": sys.executable,
                "args": ["-m", "simple_agent.clock_server"],
            }
        }
        async with MCPManager(config) as manager:
            tools = await manager.list_tools()
            self.assertEqual(len(tools), 1)
            function = tools[0]["function"]
            self.assertTrue(function["name"].startswith("clock__get_system_datetime_"))
            self.assertEqual(function["parameters"].get("properties", {}), {})

            before = datetime.now(timezone.utc)
            result = json.loads(await manager.call_tool(function["name"], {}))
            after = datetime.now(timezone.utc)

        self.assertFalse(result.get("isError", False))
        data = result.get("structuredContent")
        if data is None:
            data = json.loads(result["content"][0]["text"])

        local = datetime.fromisoformat(data["local_datetime"])
        utc = datetime.fromisoformat(data["utc_datetime"])
        self.assertIsNotNone(local.utcoffset())
        self.assertEqual(utc.utcoffset(), timedelta(0))
        # The server reports seconds, so its timestamp can be truncated by up to a second.
        self.assertLessEqual(before - timedelta(seconds=1), utc)
        self.assertLessEqual(utc, after)
        self.assertEqual(local.astimezone(timezone.utc), utc)

        offset = datetime.fromisoformat("2000-01-01T00:00:00" + data["utc_offset"])
        self.assertEqual(offset.utcoffset(), local.utcoffset())
        system_local = utc.astimezone()
        self.assertEqual(local.utcoffset(), system_local.utcoffset())
        self.assertEqual(data["timezone_name"], system_local.tzname())
