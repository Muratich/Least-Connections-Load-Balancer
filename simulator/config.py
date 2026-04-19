import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DurationRange:
    min: float
    max: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DurationRange":
        try:
            minimum = float(payload["min"])
            maximum = float(payload["max"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("duration range must include numeric min and max") from exc

        if minimum <= 0 or maximum <= 0:
            raise ValueError("duration range bounds must be positive")
        if minimum > maximum:
            raise ValueError("duration range min must be less than or equal to max")
        return cls(min=minimum, max=maximum)

    def to_json(self) -> dict[str, float]:
        return {"min": self.min, "max": self.max}


@dataclass(frozen=True)
class MachineType:
    name: str
    display_name: str
    allowed_metrics: tuple[str, ...]
    telemetry_interval_ms: int
    run_duration_seconds: DurationRange

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "MachineType":
        try:
            name = str(payload["name"])
            display_name = str(payload.get("display_name") or name)
            allowed_metrics = tuple(str(item) for item in payload["allowed_metrics"])
            interval = int(payload["telemetry_interval_ms"])
            duration = DurationRange.from_payload(payload["run_duration_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid machine type entry") from exc

        if not name:
            raise ValueError("machine type name is required")
        if not allowed_metrics:
            raise ValueError(f"machine type {name} must define allowed metrics")
        if interval <= 0:
            raise ValueError(f"machine type {name} must define a positive telemetry interval")

        return cls(
            name=name,
            display_name=display_name,
            allowed_metrics=allowed_metrics,
            telemetry_interval_ms=interval,
            run_duration_seconds=duration,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "allowed_metrics": list(self.allowed_metrics),
            "telemetry_interval_ms": self.telemetry_interval_ms,
            "run_duration_seconds": self.run_duration_seconds.to_json(),
        }


@dataclass(frozen=True)
class MachineConfig:
    machine_types: tuple[MachineType, ...]

    @classmethod
    def load(cls, path: str | Path) -> "MachineConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_payload(data)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "MachineConfig":
        raw_types = payload.get("machine_types")
        if not isinstance(raw_types, list) or not raw_types:
            raise ValueError("machine config must define at least one machine type")

        machine_types = tuple(MachineType.from_payload(item) for item in raw_types)
        names: set[str] = set()
        for machine_type in machine_types:
            if machine_type.name in names:
                raise ValueError(f"duplicate machine type: {machine_type.name}")
            names.add(machine_type.name)

        return cls(machine_types=machine_types)

    @property
    def by_name(self) -> dict[str, MachineType]:
        return {machine_type.name: machine_type for machine_type in self.machine_types}

    def to_json(self) -> dict[str, Any]:
        return {"machine_types": [machine_type.to_json() for machine_type in self.machine_types]}
