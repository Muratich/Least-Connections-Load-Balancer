import json
import unittest
from pathlib import Path

from simulator.config import DurationRange, MachineConfig
from simulator.metrics import generate_metrics
from simulator.protocol import build_message, encode_line


class ConfigMetricsProtocolTests(unittest.TestCase):
    def test_loads_shared_machine_config(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        config = MachineConfig.load(repo_root / "config" / "machine_types.json")

        self.assertEqual({"cnc", "conveyor", "oven"}, set(config.by_name))
        self.assertGreater(config.by_name["cnc"].telemetry_interval_ms, 0)

    def test_rejects_invalid_config(self) -> None:
        with self.assertRaises(ValueError):
            MachineConfig.from_payload({"machine_types": []})

        with self.assertRaises(ValueError):
            MachineConfig.from_payload(
                {
                    "machine_types": [
                        {
                            "name": "cnc",
                            "allowed_metrics": ["temperature_c"],
                            "telemetry_interval_ms": 1000,
                            "run_duration_seconds": {"min": 5, "max": 2},
                        }
                    ]
                }
            )

    def test_generates_only_allowed_metrics(self) -> None:
        config = MachineConfig.from_payload(
            {
                "machine_types": [
                    {
                        "name": "custom",
                        "display_name": "Custom",
                        "allowed_metrics": ["completion_pct", "unknown_load"],
                        "telemetry_interval_ms": 1000,
                        "run_duration_seconds": {"min": 1, "max": 2},
                    }
                ]
            }
        )
        machine_type = config.by_name["custom"]

        metrics = generate_metrics(machine_type, 42)

        self.assertEqual(set(machine_type.allowed_metrics), set(metrics))
        self.assertAlmostEqual(42, metrics["completion_pct"], delta=0.01)

    def test_builds_json_line_messages(self) -> None:
        message = build_message(
            event="telemetry",
            machine_id="cnc-000001",
            machine_type="cnc",
            job_id="job-1",
            metrics={"temperature_c": 71.25},
        )

        decoded = json.loads(encode_line(message).decode("utf-8"))

        self.assertEqual("telemetry", decoded["event"])
        self.assertEqual("cnc-000001", decoded["machine_id"])
        self.assertEqual({"temperature_c": 71.25}, decoded["metrics"])
        self.assertTrue(decoded["timestamp"].endswith("Z"))

    def test_duration_range_validation(self) -> None:
        self.assertEqual(DurationRange(1.0, 2.5), DurationRange.from_payload({"min": 1, "max": 2.5}))

        with self.assertRaises(ValueError):
            DurationRange.from_payload({"min": 0, "max": 1})
