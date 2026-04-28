import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .config import DurationRange, MachineConfig, MachineType
from .machine import MachineRunner, MachineRuntime, choose_duration


@dataclass(frozen=True)
class LoadSettings:
    target_active: int = 0
    spawn_rate_per_sec: float = 1.0
    machine_mix: dict[str, float] | None = None
    duration_seconds: DurationRange | None = None
    telemetry_interval_ms: int | None = None
    fault_probability_per_minute: float = 0.0

    def to_json(self) -> dict[str, object]:
        return {
            "target_active": self.target_active,
            "spawn_rate_per_sec": self.spawn_rate_per_sec,
            "machine_mix": self.machine_mix,
            "duration_seconds": self.duration_seconds.to_json() if self.duration_seconds else None,
            "telemetry_interval_ms": self.telemetry_interval_ms,
            "fault_probability_per_minute": self.fault_probability_per_minute,
        }


class SimulatorController:
    def __init__(
        self,
        machine_config: MachineConfig,
        target_host: str,
        target_port: int,
        recent_limit: int = 200,
    ) -> None:
        self.machine_config = machine_config
        self.target_host = target_host
        self.target_port = target_port
        self._machine_types = machine_config.by_name
        self._runner = MachineRunner(target_host, target_port)
        self._active: dict[str, MachineRuntime] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._recent: deque[dict[str, object]] = deque(maxlen=recent_limit)
        self._lock = asyncio.Lock()
        self._settings = LoadSettings(machine_mix=self._default_mix())
        self._total_spawned = 0
        self._completed_count = 0
        self._broken_count = 0
        self._failed_count = 0
        self._controller_task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        if self._controller_task is None:
            self._controller_task = asyncio.create_task(self._maintain_loop())

    async def shutdown(self) -> None:
        self._closed = True
        if self._controller_task:
            self._controller_task.cancel()
            await asyncio.gather(self._controller_task, return_exceptions=True)

        async with self._lock:
            runtimes = list(self._active.values())
            tasks = list(self._tasks.values())
        for runtime in runtimes:
            runtime.stop_requested = True

        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def set_load(self, payload: dict[str, Any]) -> dict[str, object]:
        settings = self._parse_load_settings(payload, partial=False)
        async with self._lock:
            self._settings = settings
            await self._trim_excess_locked()
        return await self.status()

    async def spawn_manual(self, payload: dict[str, Any]) -> dict[str, object]:
        count = _non_negative_int(payload.get("count", 1), "count")
        if count <= 0:
            raise ValueError("count must be greater than 0")

        spawn_rate = _positive_float(payload.get("spawn_rate_per_sec", 1.0), "spawn_rate_per_sec")
        machine_type_name = payload.get("machine_type")
        duration = _optional_duration(payload.get("duration_seconds"))
        interval = _optional_positive_int(payload.get("telemetry_interval_ms"), "telemetry_interval_ms")
        max_duration_seconds = _optional_positive_float(payload.get("max_duration_seconds"), "max_duration_seconds")

        created: list[str] = []
        for index in range(count):
            machine_type = (
                self._get_machine_type(machine_type_name)
                if machine_type_name
                else self._choose_machine_type(None)
            )
            runtime = await self._spawn_one(
                machine_type=machine_type,
                managed=False,
                duration_seconds=choose_duration(machine_type, duration),
                telemetry_interval_ms=interval or machine_type.telemetry_interval_ms,
                fault_probability_per_minute=0.0,
                max_duration_seconds=max_duration_seconds,
            )
            created.append(runtime.machine_id)
            if index < count - 1:
                await asyncio.sleep(1 / spawn_rate)

        return {"created": created}

    async def break_machine(self, machine_id: str) -> dict[str, object]:
        async with self._lock:
            runtime = self._active.get(machine_id)
            if runtime is None:
                raise KeyError(machine_id)
            runtime.break_requested = True
            runtime.state = "broken"
            return runtime.snapshot()

    async def stop_all(self) -> dict[str, object]:
        async with self._lock:
            self._settings = LoadSettings(
                target_active=0,
                spawn_rate_per_sec=self._settings.spawn_rate_per_sec,
                machine_mix=self._settings.machine_mix,
                duration_seconds=self._settings.duration_seconds,
                telemetry_interval_ms=self._settings.telemetry_interval_ms,
                fault_probability_per_minute=self._settings.fault_probability_per_minute,
            )
            for runtime in self._active.values():
                runtime.drain_requested = True
                if runtime.state in {"starting", "running"}:
                    runtime.state = "stopping"
        return await self.status()

    async def status(self) -> dict[str, object]:
        async with self._lock:
            return {
                "target": self._settings.to_json(),
                "active_count": len(self._active),
                "completed_count": self._completed_count,
                "broken_count": self._broken_count,
                "failed_count": self._failed_count,
                "total_spawned": self._total_spawned,
                "tcp_target": {"host": self.target_host, "port": self.target_port},
            }

    async def machines(self) -> dict[str, object]:
        async with self._lock:
            active = [runtime.snapshot() for runtime in self._active.values()]
            recent = list(self._recent)

        backends: list[str] = []
        seen: set[str] = set()
        for item in active + recent:
            for backend in item.get("seen_backends", []) or []:
                if backend not in seen:
                    seen.add(backend)
                    backends.append(backend)

        active.sort(key=lambda item: str(item["machine_id"]))
        return {"backends": backends, "active": active, "recent": recent}

    async def _maintain_loop(self) -> None:
        while not self._closed:
            async with self._lock:
                active_managed = sum(1 for runtime in self._active.values() if runtime.managed)
                settings = self._settings
                needed = max(0, settings.target_active - active_managed)
                if settings.target_active == 0:
                    needed = 0
                spawn_rate = settings.spawn_rate_per_sec

            for _ in range(needed):
                machine_type = self._choose_machine_type(settings.machine_mix)
                await self._spawn_one(
                    machine_type=machine_type,
                    managed=True,
                    duration_seconds=choose_duration(machine_type, settings.duration_seconds),
                    telemetry_interval_ms=settings.telemetry_interval_ms or machine_type.telemetry_interval_ms,
                    fault_probability_per_minute=settings.fault_probability_per_minute,
                    max_duration_seconds=None,
                )
                await asyncio.sleep(1 / spawn_rate)

            async with self._lock:
                await self._trim_excess_locked()
            await asyncio.sleep(0.1)

    async def _trim_excess_locked(self) -> None:
        active_managed = [
            runtime
            for runtime in self._active.values()
            if runtime.managed and not runtime.drain_requested
        ]
        excess = max(0, len(active_managed) - self._settings.target_active)
        for runtime in active_managed[:excess]:
            runtime.stop_requested = True
            if runtime.state == "running":
                runtime.state = "stopping"

    async def _spawn_one(
        self,
        machine_type: MachineType,
        managed: bool,
        duration_seconds: float,
        telemetry_interval_ms: int,
        fault_probability_per_minute: float,
        max_duration_seconds: float | None = None,
    ) -> MachineRuntime:
        async with self._lock:
            self._total_spawned += 1
            sequence = self._total_spawned
            runtime = MachineRuntime(
                machine_id=f"{machine_type.name}-{sequence:06d}",
                machine_type=machine_type,
                job_id=f"job-{uuid4().hex[:12]}",
                duration_seconds=duration_seconds,
                telemetry_interval_ms=telemetry_interval_ms,
                fault_probability_per_minute=fault_probability_per_minute,
                managed=managed,
                max_duration_seconds=max_duration_seconds,
            )
            self._active[runtime.machine_id] = runtime
            task = asyncio.create_task(self._run_machine(runtime))
            self._tasks[runtime.machine_id] = task
            return runtime

    async def _run_machine(self, runtime: MachineRuntime) -> None:
        try:
            await self._runner.run(runtime)
        except asyncio.CancelledError:
            runtime.state = "broken"
            runtime.finished_at = runtime.finished_at or time.time()
            raise
        except Exception as exc:
            runtime.state = "failed"
            runtime.last_error = str(exc)
            runtime.finished_at = runtime.finished_at or time.time()
        finally:
            async with self._lock:
                self._active.pop(runtime.machine_id, None)
                self._tasks.pop(runtime.machine_id, None)
                snapshot = runtime.snapshot()
                self._recent.appendleft(snapshot)
                if runtime.state == "completed":
                    self._completed_count += 1
                elif runtime.state == "broken":
                    self._broken_count += 1
                elif runtime.state == "failed":
                    self._failed_count += 1

    def _parse_load_settings(self, payload: dict[str, Any], partial: bool) -> LoadSettings:
        del partial
        target = _non_negative_int(payload.get("target_active", 0), "target_active")
        spawn_rate = _positive_float(payload.get("spawn_rate_per_sec", 1.0), "spawn_rate_per_sec")
        machine_mix = self._parse_machine_mix(payload.get("machine_mix"))
        duration = _optional_duration(payload.get("duration_seconds"))
        interval = _optional_positive_int(payload.get("telemetry_interval_ms"), "telemetry_interval_ms")
        fault_probability = _probability(payload.get("fault_probability_per_minute", 0.0))
        return LoadSettings(
            target_active=target,
            spawn_rate_per_sec=spawn_rate,
            machine_mix=machine_mix,
            duration_seconds=duration,
            telemetry_interval_ms=interval,
            fault_probability_per_minute=fault_probability,
        )

    def _parse_machine_mix(self, payload: Any) -> dict[str, float]:
        if payload is None:
            return self._default_mix()
        if not isinstance(payload, dict) or not payload:
            raise ValueError("machine_mix must be a non-empty object")

        result: dict[str, float] = {}
        for name, weight in payload.items():
            self._get_machine_type(str(name))
            numeric_weight = _positive_float(weight, f"machine_mix.{name}")
            result[str(name)] = numeric_weight
        return result

    def _choose_machine_type(self, mix: dict[str, float] | None) -> MachineType:
        active_mix = mix or self._settings.machine_mix or self._default_mix()
        names = list(active_mix.keys())
        weights = list(active_mix.values())
        return self._machine_types[random.choices(names, weights=weights, k=1)[0]]

    def _get_machine_type(self, name: Any) -> MachineType:
        if not isinstance(name, str) or not name:
            raise ValueError("machine_type must be a non-empty string")
        try:
            return self._machine_types[name]
        except KeyError as exc:
            raise ValueError(f"unknown machine_type {name!r}") from exc

    def _default_mix(self) -> dict[str, float]:
        return {machine_type.name: 1.0 for machine_type in self.machine_config.machine_types}


def _non_negative_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed


def _positive_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    parsed = _non_negative_int(value, field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _optional_positive_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    parsed = _positive_float(value, field_name)
    return parsed


def _optional_duration(value: Any) -> DurationRange | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("duration_seconds must be an object")
    return DurationRange.from_payload(value)


def _probability(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("fault_probability_per_minute must be numeric") from exc
    if parsed < 0 or parsed > 1:
        raise ValueError("fault_probability_per_minute must be between 0 and 1")
    return parsed
