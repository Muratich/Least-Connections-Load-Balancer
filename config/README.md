# Configs

## machine_types.json

This file contains machine type definitions used by the backend and future simulator.

The root JSON object contains one field:

- `machine_types` — an array of machine type objects

## Machine type fields

Each object inside `machine_types` must contain:

- `name` — unique internal machine type name, for example `cnc`
- `display_name` — human-readable machine name
- `allowed_metrics` — list of metric names allowed for this machine type
- `telemetry_interval_ms` — how often the machine usually sends telemetry
- `run_duration_seconds.min` — minimum job duration
- `run_duration_seconds.max` — maximum job duration

## How to add a new machine type

1. Open [machine_types.json](C:/Users/Retr046/Desktop/DNP/project/Least-Connections-Load-Balancer/config/machine_types.json).
2. Go to the `machine_types` array.
3. Add a new JSON object separated by a comma from the previous one.
4. Choose a unique `name`.
5. Add metric names that this machine is allowed to send.
6. Set default telemetry interval and job duration range.

## Example

Example of adding a new `robot_arm` type:

```json
{
  "machine_types": [
    {
      "name": "cnc",
      "display_name": "CNC Machine",
      "allowed_metrics": [
        "temperature_c",
        "spindle_rpm",
        "completion_pct"
      ],
      "telemetry_interval_ms": 1000,
      "run_duration_seconds": {
        "min": 20,
        "max": 45
      }
    },
    {
      "name": "robot_arm",
      "display_name": "Robot Arm",
      "allowed_metrics": [
        "joint_temp_c",
        "load_pct",
        "completion_pct"
      ],
      "telemetry_interval_ms": 1000,
      "run_duration_seconds": {
        "min": 15,
        "max": 35
      }
    }
  ]
}
```

## Important rules

- `name` must not repeat an existing machine type.
- Metric names should match what the simulator or clients actually send.
- `telemetry_interval_ms` must be greater than `0`.
- `run_duration_seconds.min` and `run_duration_seconds.max` must be greater than `0`.
- `min` must be less than or equal to `max`.

If the JSON is invalid or a machine type is configured incorrectly, the backend will fail to load the config at startup.
