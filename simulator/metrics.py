import random

from .config import MachineType


def _round(value: float) -> float:
    return round(value, 2)


def generate_metrics(machine_type: MachineType, progress_pct: float) -> dict[str, float]:
    progress = max(0.0, min(100.0, progress_pct))
    values = {
        "temperature_c": _round(62 + progress * 0.12 + random.uniform(-2.5, 3.5)),
        "spindle_rpm": _round(random.uniform(2800, 4700)),
        "motor_temp_c": _round(38 + progress * 0.08 + random.uniform(-1.5, 2.5)),
        "belt_speed_mps": _round(random.uniform(0.6, 2.4)),
        "chamber_temp_c": _round(145 + progress * 1.4 + random.uniform(-7, 9)),
        "power_kw": _round(random.uniform(18, 42)),
        "completion_pct": _round(progress),
    }

    metrics: dict[str, float] = {}
    for metric_name in machine_type.allowed_metrics:
        metrics[metric_name] = values.get(metric_name, _round(random.uniform(0, 100)))
    return metrics
