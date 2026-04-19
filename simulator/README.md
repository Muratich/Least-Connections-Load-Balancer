# Virtual Factory Simulator

## Goal

The simulator represents a virtual factory where different machines open TCP connections, send telemetry while working, and then finish their jobs.

Its purpose is to create realistic long-lived TCP sessions for the load balancer and backend service.

## Component roles

- Simulator: spawns temporary machine clients.
- Load balancer: forwards persistent TCP connections to backend servers.
- Backend: validates messages, tracks active machines, and exposes current status through HTTP.

## Machine lifecycle

Each simulated machine uses one TCP connection for one job:

1. Open a TCP connection.
2. Send `hello` with machine identity and job metadata.
3. Send `telemetry` messages every second while the job is running.
4. Send `done` when the job is complete.
5. Close the connection and free backend capacity.

## Initial machine types

The first simulator profiles are:

- `cnc`: `temperature_c`, `spindle_rpm`, `completion_pct`
- `conveyor`: `motor_temp_c`, `belt_speed_mps`, `completion_pct`
- `oven`: `chamber_temp_c`, `power_kw`, `completion_pct`

Shared machine profiles live in [config/machine_types.json](../config/machine_types.json).

## TCP message format

The simulator sends JSON Lines over TCP, one JSON object per line.

Common fields:

- `event`
- `machine_id`
- `machine_type`
- `job_id`
- `timestamp`
- `metrics`

Example telemetry message:

```json
{"event":"telemetry","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1001","timestamp":"2026-04-18T12:00:01Z","metrics":{"temperature_c":71.2,"spindle_rpm":4200,"completion_pct":15}}
```

## Configuration

The simulator is expected to read JSON configuration for machine profiles and runtime parameters such as telemetry interval and job duration range.

For the first stage, the shared config already defines:

- allowed metric names per machine type;
- default telemetry interval in milliseconds;
- minimum and maximum job duration in seconds.

## Python master

The simulator now includes a stdlib-only Python master process. Run it from the repository root:

```powershell
python -m simulator --target-host 127.0.0.1 --target-port 8000 --http-addr 127.0.0.1:8100 --machine-config config/machine_types.json
```

Default ports:

- TCP target: `127.0.0.1:8000` (load balancer)
- HTTP master API: `127.0.0.1:8100`

Open the simulator dashboard:

```text
http://127.0.0.1:8100/
```

### Master API

- `GET /healthz`
- `GET /api/config/machine-types`
- `GET /api/status`
- `GET /api/machines`
- `PUT /api/load`
- `POST /api/machines`
- `POST /api/machines/{machine_id}/break`
- `POST /api/stop`

Example sustained load:

```powershell
Invoke-RestMethod -Method Put http://127.0.0.1:8100/api/load -ContentType "application/json" -Body '{"target_active":30,"spawn_rate_per_sec":3,"machine_mix":{"cnc":1,"conveyor":1,"oven":1}}'
```

Example one-shot clients:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8100/api/machines -ContentType "application/json" -Body '{"count":3,"machine_type":"cnc","spawn_rate_per_sec":1}'
```

Stop sustained load and gracefully finish active machines:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8100/api/stop
```

Run simulator tests:

```powershell
python -m unittest discover simulator/tests
```
