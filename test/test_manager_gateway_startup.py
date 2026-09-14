import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "manager"))

from gateway_manager import get_gateway
from config import load_config


class ManagerGatewayStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_starts_web_channel(self):
        gateway = get_gateway()
        try:
            message = await gateway.start()
            self.assertIn("已启动", message)
            cfg = load_config()
            ready = False
            for _ in range(160):
                await asyncio.sleep(.25)
                try:
                    reader, writer = await asyncio.open_connection(cfg.web_host, cfg.web_port)
                    writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                    await writer.drain(); data = await reader.read(512)
                    writer.close(); await writer.wait_closed()
                    ready = b"200 OK" in data
                    if ready: break
                except OSError:
                    continue
            if not ready:
                self.fail("Web channel did not become ready. Logs:\n" + "\n".join(gateway.get_status()["logs"]))
        finally:
            await gateway.stop()


if __name__ == "__main__": unittest.main()
