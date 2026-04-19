import json
from datetime import UTC, datetime


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_message(
    event: str,
    machine_id: str,
    machine_type: str,
    job_id: str,
    metrics: dict[str, float] | None = None,
) -> dict[str, object]:
    message: dict[str, object] = {
        "event": event,
        "machine_id": machine_id,
        "machine_type": machine_type,
        "job_id": job_id,
        "timestamp": utc_timestamp(),
    }
    if metrics:
        message["metrics"] = metrics
    return message


def encode_line(message: dict[str, object]) -> bytes:
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
