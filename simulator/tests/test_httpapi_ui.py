import asyncio
import threading
import unittest
from urllib.request import urlopen

from simulator.config import MachineConfig
from simulator.controller import SimulatorController
from simulator.httpapi import SimulatorHTTPServer


def test_config() -> MachineConfig:
    return MachineConfig.from_payload(
        {
            "machine_types": [
                {
                    "name": "cnc",
                    "display_name": "CNC",
                    "allowed_metrics": ["temperature_c", "spindle_rpm", "completion_pct"],
                    "telemetry_interval_ms": 1000,
                    "run_duration_seconds": {"min": 1, "max": 2},
                }
            ]
        }
    )


class HTTPUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.controller = SimulatorController(test_config(), "127.0.0.1", 8000)
        self.server = SimulatorHTTPServer(("127.0.0.1", 0), self.controller, self.loop)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.loop.close()

    def test_serves_dashboard_html(self) -> None:
        with urlopen(f"{self.base_url}/", timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(200, response.status)
        self.assertIn("text/html", response.headers.get("Content-Type", ""))
        self.assertIn("Factory Simulator", body)

    def test_serves_static_assets(self) -> None:
        with urlopen(f"{self.base_url}/static/styles.css", timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(200, response.status)
        self.assertIn("text/css", response.headers.get("Content-Type", ""))
        self.assertIn(".topbar", body)

    def test_serves_dashboard_javascript(self) -> None:
        with urlopen(f"{self.base_url}/static/app.js", timeout=5) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(200, response.status)
        self.assertIn("text/javascript", response.headers.get("Content-Type", ""))
        self.assertIn("loadFormDirty", body)
