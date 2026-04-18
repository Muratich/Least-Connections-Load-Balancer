# Backend Service

## Overview

This backend is a Go service for receiving factory machine telemetry over persistent TCP connections.

The project models a virtual factory:

- each machine opens one TCP connection;
- sends `hello` when a job starts;
- sends `telemetry` messages while the job is running;
- sends `done` when the job finishes;
- closes the connection and frees backend capacity.

The backend keeps only the current in-memory state of active machines and exposes a simple HTTP API for status and monitoring.

## Current responsibilities

The service currently does the following:

- accepts TCP telemetry connections from machines;
- validates incoming JSON Lines messages;
- enforces the lifecycle `hello -> telemetry* -> done`;
- tracks active machine sessions in memory;
- counts accepted connections, completed sessions, and protocol errors;
- exposes read-only HTTP endpoints for health and current state.

The service does not currently do the following:

- store historical telemetry in a database;
- render a web UI;
- know anything about the future load balancer internals.

## Project structure

- [cmd/server/main.go](C:/Users/Retr046/Desktop/DNP/project/Least-Connections-Load-Balancer/backend/cmd/server/main.go) — application entrypoint, startup, config loading, TCP + HTTP server lifecycle
- [internal/config/config.go](C:/Users/Retr046/Desktop/DNP/project/Least-Connections-Load-Balancer/backend/internal/config/config.go) — machine type config loading and validation
- [internal/protocol/message.go](C:/Users/Retr046/Desktop/DNP/project/Least-Connections-Load-Balancer/backend/internal/protocol/message.go) — TCP message schema and protocol validation
- [internal/state/store.go](C:/Users/Retr046/Desktop/DNP/project/Least-Connections-Load-Balancer/backend/internal/state/store.go) — in-memory active session registry and counters
- [internal/tcp/server.go](C:/Users/Retr046/Desktop/DNP/project/Least-Connections-Load-Balancer/backend/internal/tcp/server.go) — TCP accept loop and per-connection processing
- [internal/httpapi/handlers.go](C:/Users/Retr046/Desktop/DNP/project/Least-Connections-Load-Balancer/backend/internal/httpapi/handlers.go) — HTTP monitoring endpoints
- [../config/machine_types.json](C:/Users/Retr046/Desktop/DNP/project/Least-Connections-Load-Balancer/config/machine_types.json) — shared machine type definitions

## Machine type config

Machine profiles are defined in `../config/machine_types.json`.

Current machine types:

- `cnc`
- `conveyor`
- `oven`

Each machine type defines:

- machine name and display name;
- allowed telemetry metric names;
- default telemetry interval in milliseconds;
- default job duration range.

Example:

```json
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
}
```

The backend uses this config to validate `machine_type` and allowed metric keys.

## TCP protocol

The backend accepts JSON Lines over TCP.

This means:

- one JSON object per line;
- each line is one event;
- one TCP connection corresponds to one machine job session.

### Supported events

- `hello` — starts a session
- `telemetry` — updates current state
- `done` — completes the session

### Common fields

Each message may contain:

- `event`
- `machine_id`
- `machine_type`
- `job_id`
- `timestamp`
- `metrics`

### Lifecycle rules

- the first valid message on a connection must be `hello`;
- `telemetry` is allowed only after `hello`;
- `done` is allowed only after `hello`;
- a second `hello` on the same connection is a protocol error;
- unknown `machine_type` is rejected;
- unknown metric keys for a known machine type are rejected;
- `telemetry` must contain `metrics`.

### Example message flow

```json
{"event":"hello","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"2026-04-18T12:00:00Z"}
{"event":"telemetry","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"2026-04-18T12:00:01Z","metrics":{"temperature_c":71.2,"spindle_rpm":4200,"completion_pct":15}}
{"event":"telemetry","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"2026-04-18T12:00:02Z","metrics":{"temperature_c":72.0,"spindle_rpm":4180,"completion_pct":30}}
{"event":"done","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"2026-04-18T12:00:10Z"}
```

## In-memory state model

For each active machine session, the backend stores:

- `connection_id`
- `machine_id`
- `machine_type`
- `job_id`
- `status`
- `connected_at`
- `last_seen_at`
- `telemetry_count`
- `last_metrics`

Global counters:

- `total_connections_accepted`
- `total_sessions_completed`
- `protocol_errors`
- `active_connections`

Important behavior:

- active sessions are removed from memory after `done`;
- if a TCP connection drops before `done`, the active session is removed;
- completed session history is not persisted after process restart.

## HTTP API

The backend exposes a small read-only monitoring API.

### `GET /healthz`

Returns a simple health response.

Example:

```json
{"status":"ok"}
```

### `GET /api/status`

Returns global process counters.

Example:

```json
{
  "active_connections": 1,
  "total_connections_accepted": 3,
  "total_sessions_completed": 1,
  "protocol_errors": 0
}
```

### `GET /api/machines`

Returns the list of currently active machines.

Example:

```json
[
  {
    "connection_id": "conn-000003",
    "machine_id": "cnc-01",
    "machine_type": "cnc",
    "job_id": "job-42",
    "status": "running",
    "connected_at": "2026-04-18T12:00:00Z",
    "last_seen_at": "2026-04-18T12:00:05Z",
    "telemetry_count": 5,
    "last_metrics": {
      "temperature_c": 71.2,
      "spindle_rpm": 4200,
      "completion_pct": 15
    }
  }
]
```

## How to run

### Requirements

- Go installed locally

### Start the service

From the `backend` directory:

```powershell
cd C:\Users\Retr046\Desktop\DNP\project\Least-Connections-Load-Balancer\backend
go run ./cmd/server
```

Default ports:

- TCP telemetry server: `:9000`
- HTTP status server: `:8080`

### Command-line flags

- `--tcp-addr` — TCP listen address
- `--http-addr` — HTTP listen address
- `--machine-config` — path to machine config JSON

Example:

```powershell
go run ./cmd/server --tcp-addr :9100 --http-addr :8181 --machine-config ..\config\machine_types.json
```

## How to check the HTTP API

From PowerShell:

```powershell
Invoke-RestMethod http://localhost:8080/healthz
Invoke-RestMethod http://localhost:8080/api/status
Invoke-RestMethod http://localhost:8080/api/machines
```

## How to send a test TCP session manually

You can open a TCP client directly from PowerShell and send JSON Lines.

```powershell
$client = [System.Net.Sockets.TcpClient]::new("127.0.0.1", 9000)
$stream = $client.GetStream()
$writer = New-Object System.IO.StreamWriter($stream)
$writer.AutoFlush = $true

$writer.WriteLine('{"event":"hello","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"2026-04-18T12:00:00Z"}')
$writer.WriteLine('{"event":"telemetry","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"2026-04-18T12:00:01Z","metrics":{"temperature_c":71.2,"spindle_rpm":4200,"completion_pct":15}}')
$writer.WriteLine('{"event":"done","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"2026-04-18T12:00:02Z"}')

$writer.Dispose()
$stream.Dispose()
$client.Dispose()
```

After the first two messages, `GET /api/machines` should show one active machine.

After `done`, the machine should disappear from `/api/machines`, and `/api/status` should show `total_sessions_completed` incremented.

## How to run tests

From the `backend` directory:

```powershell
go test ./...
```

The tests currently cover:

- valid `hello -> telemetry -> done` lifecycle;
- status and machine list updates;
- `telemetry` before `hello`;
- duplicate `hello`;
- `done` before `hello`;
- unknown machine type and invalid metrics;
- cleanup after dropped TCP connections.
