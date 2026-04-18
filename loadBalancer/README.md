# Load Balancer

## Overview

This service is a TCP reverse proxy that implements the **Least Connections** algorithm.

Its job is simple:

- accept incoming client TCP connections;
- choose the backend with the smallest number of active connections;
- proxy bytes between client and backend in both directions;
- keep the connection open until one side closes it.

The balancer is designed for persistent TCP sessions, not for short stateless HTTP requests.

## How it works

For every new client connection:

1. the load balancer reads the backend list from `config/backends.json`;
2. it selects the backend with the lowest active connection count;
3. if multiple backends are tied, it uses round robin among the tied candidates;
4. it opens a TCP connection to the selected backend;
5. it relays traffic between client and backend until the session ends;
6. it decrements the backend connection counter on shutdown.

### Important behavior

- each TCP client connection counts as one active session;
- the backend is chosen before the connection is proxied;
- connection counters are protected with a mutex;
- graceful shutdown is handled through `SIGINT` and `SIGTERM`.

## Project structure

- `cmd/loadBalancer/main.go` — application entrypoint, config loading, signal handling, service startup
- `internal/config/config.go` — JSON config loading for listen address and backend list
- `internal/loadBalancer/balancer.go` — Least Connections logic, TCP relay, connection tracking, graceful shutdown
- `go.mod` — Go module definition and dependencies
- `README.md` — project documentation

## How to run

### Requirements

- Go installed locally

### Start the service

You need to be in the `loadBalancer` directory:
```powershell
cd loadBalancer
```
You must specify config in the flag when running loadBalancer!

If you use Docker compose use:

```powershell
go run ./cmd/loadBalancer --config ../config/backends.json
```

Else if you run locally in CLI (without Docker compose) use:

```powershell
go run ./cmd/loadBalancer --config ../config/backends-localRun.json
```

Default ports:

Load balancer listens on:
http://localhost:8000 (TCP proxy)

### Command-line flags

- `--config` — specify config path