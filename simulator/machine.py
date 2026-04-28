import asyncio
import contextlib
import random
import time
import json
from dataclasses import dataclass, field
from typing import Literal

from .config import DurationRange, MachineType
from .metrics import generate_metrics
from .protocol import build_message, encode_line

MachineState = Literal["starting", "running", "stopping", "completed", "broken", "failed"]
ASSIGNMENT_PEEK_TIMEOUT_SECONDS = 0.01
SLOT_POLL_TIMEOUT_SECONDS = 0.1


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
    drain_requested: bool = False
    break_requested: bool = False

    backend_addr: str | None = None
    seen_backends: tuple[str, ...] = field(default_factory=tuple)
    max_duration_seconds: float | None = None

    def snapshot(self) -> dict[str, object]:
        now = self.finished_at or time.time()
        return {
            "machine_id": self.machine_id,
            "machine_type": self.machine_type.name,
            "job_id": self.job_id,
            "state": self.state,
            "managed": self.managed,
            "duration_seconds": round(self.duration_seconds, 3),
            "backend_addr": self.backend_addr,
            "seen_backends": list(self.seen_backends),
            "telemetry_interval_ms": self.telemetry_interval_ms,
            "fault_probability_per_minute": self.fault_probability_per_minute,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "age_seconds": round(now - self.started_at, 3),
            "telemetry_count": self.telemetry_count,
            "last_error": self.last_error,
            "max_duration_seconds": self.max_duration_seconds,
        }


class MachineRunner:
    def __init__(self, target_host: str, target_port: int, max_in_flight: int = 24) -> None:
        self._target_host = target_host
        self._target_port = target_port
        self._slots = asyncio.Semaphore(max_in_flight)

    async def run(self, runtime: MachineRuntime) -> None:
        writer: asyncio.StreamWriter | None = None
        slot_acquired = False
        try:
            normal_deadline = runtime.started_at + runtime.duration_seconds
            max_deadline = (
                runtime.started_at + runtime.max_duration_seconds
                if runtime.max_duration_seconds is not None
                else None
            )
            effective_deadline = min(normal_deadline, max_deadline) if max_deadline is not None else normal_deadline

            remaining = effective_deadline - time.time()
            if remaining <= 0:
                runtime.state = "broken"
                return

            if self._abort_before_start(runtime):
                return

            reader, writer = await asyncio.open_connection(self._target_host, self._target_port)

            if not await self._capture_assignment(reader, runtime, effective_deadline):
                return

            slot_acquired = await self._acquire_slot(runtime, effective_deadline)
            if not slot_acquired:
                return

            if self._abort_before_start(runtime):
                return
            if time.time() >= effective_deadline:
                runtime.state = "broken"
                return

            await self._write_event(writer, runtime, "hello")
            runtime.state = "running"

            interval = runtime.telemetry_interval_ms / 1000

            while True:
                now = time.time()
                if runtime.break_requested:
                    runtime.state = "broken"
                    return
                if runtime.stop_requested:
                    runtime.state = "stopping"
                    return
                if runtime.drain_requested and runtime.state == "running":
                    runtime.state = "stopping"
                if now >= normal_deadline:
                    break
                if max_deadline is not None and now >= max_deadline:
                    runtime.state = "broken"
                    return

                progress = ((now - runtime.started_at) / runtime.duration_seconds) * 100
                await self._write_event(
                    writer,
                    runtime,
                    "telemetry",
                    generate_metrics(runtime.machine_type, progress),
                )
                runtime.telemetry_count += 1
                await asyncio.sleep(interval)

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
            if slot_acquired:
                self._slots.release()
            if writer is not None:
                writer.close()
                with contextlib.suppress(OSError, ConnectionError):
                    await writer.wait_closed()

    def _abort_before_start(self, runtime: MachineRuntime) -> bool:
        if runtime.break_requested:
            runtime.state = "broken"
            return True
        if runtime.stop_requested or runtime.drain_requested:
            runtime.state = "stopping"
            return True
        return False

    async def _capture_assignment(
        self,
        reader: asyncio.StreamReader,
        runtime: MachineRuntime,
        effective_deadline: float,
    ) -> bool:
        while True:
            if self._abort_before_start(runtime):
                return False

            remaining = effective_deadline - time.time()
            if remaining <= 0:
                runtime.state = "broken"
                return False

            try:
                assigned = await asyncio.wait_for(
                    reader.readline(),
                    timeout=min(ASSIGNMENT_PEEK_TIMEOUT_SECONDS, remaining),
                )
            except asyncio.TimeoutError:
                return True
            except OSError:
                return True

            if not assigned:
                return True

            try:
                payload = json.loads(assigned.decode("utf-8"))
            except json.JSONDecodeError:
                return True

            if payload.get("event") != "assigned":
                return True

            backend = payload.get("backend")
            if backend:
                runtime.backend_addr = str(backend)
            backends = payload.get("backends")
            if isinstance(backends, list):
                runtime.seen_backends = tuple(str(item) for item in backends if item)
            return True

    async def _acquire_slot(self, runtime: MachineRuntime, effective_deadline: float) -> bool:
        while True:
            if self._abort_before_start(runtime):
                return False

            remaining = effective_deadline - time.time()
            if remaining <= 0:
                runtime.state = "broken"
                return False

            try:
                await asyncio.wait_for(
                    self._slots.acquire(),
                    timeout=min(SLOT_POLL_TIMEOUT_SECONDS, remaining),
                )
                return True
            except asyncio.TimeoutError:
                continue

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
