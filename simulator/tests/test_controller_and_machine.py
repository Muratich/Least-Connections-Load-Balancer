import asyncio
import json
import unittest

from simulator.config import DurationRange, MachineConfig
from simulator.controller import SimulatorController
from simulator.machine import MachineRunner, MachineRuntime


class FakeTCPServer:
    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.host = "127.0.0.1"
        self.port = 0
        self.connections: list[list[dict[str, object]]] = []

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, self.host, 0)
        sock = self.server.sockets[0]
        self.port = int(sock.getsockname()[1])

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection: list[dict[str, object]] = []
        self.connections.append(connection)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                connection.append(json.loads(line.decode("utf-8")))
        finally:
            writer.close()
            await writer.wait_closed()

    def events(self) -> list[str]:
        return [str(message["event"]) for connection in self.connections for message in connection]


async def wait_for_condition(fn, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if fn():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def test_config() -> MachineConfig:
    return MachineConfig.from_payload(
        {
            "machine_types": [
                {
                    "name": "cnc",
                    "display_name": "CNC",
                    "allowed_metrics": ["temperature_c", "spindle_rpm", "completion_pct"],
                    "telemetry_interval_ms": 10,
                    "run_duration_seconds": {"min": 0.05, "max": 0.05},
                },
                {
                    "name": "oven",
                    "display_name": "Oven",
                    "allowed_metrics": ["chamber_temp_c", "power_kw", "completion_pct"],
                    "telemetry_interval_ms": 10,
                    "run_duration_seconds": {"min": 0.05, "max": 0.05},
                },
            ]
        }
    )


class MachineRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = FakeTCPServer()
        await self.server.start()
        self.machine_type = test_config().by_name["cnc"]

    async def asyncTearDown(self) -> None:
        await self.server.stop()

    async def test_runner_sends_hello_telemetry_done(self) -> None:
        runtime = MachineRuntime(
            machine_id="cnc-000001",
            machine_type=self.machine_type,
            job_id="job-1",
            duration_seconds=0.05,
            telemetry_interval_ms=10,
            fault_probability_per_minute=0,
            managed=False,
        )

        await MachineRunner(self.server.host, self.server.port).run(runtime)
        await wait_for_condition(lambda: bool(self.server.events()) and self.server.events()[-1] == "done")

        events = self.server.events()
        self.assertEqual("hello", events[0])
        self.assertIn("telemetry", events)
        self.assertEqual("done", events[-1])
        self.assertEqual("completed", runtime.state)

    async def test_runner_breaks_without_done(self) -> None:
        runtime = MachineRuntime(
            machine_id="cnc-000002",
            machine_type=self.machine_type,
            job_id="job-2",
            duration_seconds=1,
            telemetry_interval_ms=10,
            fault_probability_per_minute=0,
            managed=False,
            break_requested=True,
        )

        await MachineRunner(self.server.host, self.server.port).run(runtime)
        await wait_for_condition(lambda: bool(self.server.events()))

        self.assertEqual(["hello"], self.server.events())
        self.assertEqual("broken", runtime.state)


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_bad_payloads(self) -> None:
        controller = SimulatorController(test_config(), "127.0.0.1", 1)

        with self.assertRaises(ValueError):
            await controller.set_load({"target_active": -1})
        with self.assertRaises(ValueError):
            await controller.set_load({"target_active": 1, "machine_mix": {"missing": 1}})
        with self.assertRaises(ValueError):
            await controller.set_load({"duration_seconds": {"min": 3, "max": 2}})
        with self.assertRaises(ValueError):
            await controller.spawn_manual({"count": 1, "machine_type": "missing"})

    async def test_target_controller_spawns_to_requested_active_count(self) -> None:
        server = FakeTCPServer()
        await server.start()
        controller = SimulatorController(test_config(), server.host, server.port)
        await controller.start()
        try:
            await controller.set_load(
                {
                    "target_active": 2,
                    "spawn_rate_per_sec": 100,
                    "duration_seconds": {"min": 1, "max": 1},
                    "telemetry_interval_ms": 10,
                }
            )
            await wait_for_condition(lambda: len(server.connections) >= 2)
            status = await controller.status()

            self.assertEqual(2, status["active_count"])
            self.assertEqual(2, status["total_spawned"])

            await controller.stop_all()
            await wait_for_condition(lambda: "done" in server.events())
        finally:
            await controller.shutdown()
            await server.stop()

    async def test_manual_spawn_returns_created_machine_ids(self) -> None:
        server = FakeTCPServer()
        await server.start()
        controller = SimulatorController(test_config(), server.host, server.port)
        try:
            result = await controller.spawn_manual(
                {
                    "count": 2,
                    "machine_type": "cnc",
                    "spawn_rate_per_sec": 100,
                    "duration_seconds": {"min": 0.05, "max": 0.05},
                    "telemetry_interval_ms": 10,
                }
            )

            self.assertEqual(2, len(result["created"]))
            await wait_for_condition(lambda: len(server.connections) >= 2)
        finally:
            await controller.shutdown()
            await server.stop()
