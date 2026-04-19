import asyncio
import contextlib
import random
import time
from dataclasses import dataclass, field
from typing import Literal

from .config import DurationRange, MachineType
from .metrics import generate_metrics
from .protocol import build_message, encode_line

MachineState = Literal["starting", "running", "stopping", "completed", "broken", "failed"]


@dataclass
class MachineRuntime:
    machine_id: str
    machine_type: MachineType
    job_id: str
    duration_seconds: float
    telemetry_interval_ms: int
    fault_probability_per_minute: float
    managed: bool
    state: MachineState = "starting"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    telemetry_count: int = 0
    last_error: str | None = None
    stop_requested: bool = False
    break_requested: bool = False

    def snapshot(self) -> dict[str, object]:
        now = self.finished_at or time.time()
        return {
            "machine_id": self.machine_id,
            "machine_type": self.machine_type.name,
            "job_id": self.job_id,
            "state": self.state,
            "managed": self.managed,
            "duration_seconds": round(self.duration_seconds, 3),
            "telemetry_interval_ms": self.telemetry_interval_ms,
            "fault_probability_per_minute": self.fault_probability_per_minute,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "age_seconds": round(now - self.started_at, 3),
            "telemetry_count": self.telemetry_count,
            "last_error": self.last_error,
        }


class MachineRunner:
    def __init__(self, target_host: str, target_port: int) -> None:
        self._target_host = target_host
        self._target_port = target_port

    async def run(self, runtime: MachineRuntime) -> None:
        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.open_connection(self._target_host, self._target_port)
            del reader
            await self._write_event(writer, runtime, "hello")
            runtime.state = "running"

            interval = runtime.telemetry_interval_ms / 1000
            deadline = runtime.started_at + runtime.duration_seconds

            while time.time() < deadline:
                if runtime.break_requested or self._fault_happened(runtime, interval):
                    runtime.break_requested = True
                    runtime.state = "broken"
                    return
                if runtime.stop_requested:
                    runtime.state = "stopping"
                    break

                progress = ((time.time() - runtime.started_at) / runtime.duration_seconds) * 100
                await self._write_event(
                    writer,
                    runtime,
                    "telemetry",
                    generate_metrics(runtime.machine_type, progress),
                )
                runtime.telemetry_count += 1
                await asyncio.sleep(interval)

            if runtime.break_requested:
                runtime.state = "broken"
                return

            await self._write_event(writer, runtime, "done")
            runtime.state = "completed"
        except (OSError, asyncio.TimeoutError) as exc:
            runtime.state = "failed"
            runtime.last_error = str(exc)
        except asyncio.CancelledError:
            runtime.state = "broken"
            raise
        finally:
            runtime.finished_at = time.time()
            if writer is not None:
                writer.close()
                with contextlib.suppress(OSError, ConnectionError):
                    await writer.wait_closed()

    async def _write_event(
        self,
        writer: asyncio.StreamWriter,
        runtime: MachineRuntime,
        event: str,
        metrics: dict[str, float] | None = None,
    ) -> None:
        writer.write(
            encode_line(
                build_message(
                    event=event,
                    machine_id=runtime.machine_id,
                    machine_type=runtime.machine_type.name,
                    job_id=runtime.job_id,
                    metrics=metrics,
                )
            )
        )
        await writer.drain()

    def _fault_happened(self, runtime: MachineRuntime, interval_seconds: float) -> bool:
        probability = runtime.fault_probability_per_minute
        if probability <= 0:
            return False
        chance = min(1.0, probability * (interval_seconds / 60))
        return random.random() < chance


def choose_duration(machine_type: MachineType, override: DurationRange | None) -> float:
    duration_range = override or machine_type.run_duration_seconds
    return random.uniform(duration_range.min, duration_range.max)
