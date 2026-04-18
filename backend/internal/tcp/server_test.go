package tcp

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http/httptest"
	"testing"
	"time"

	"leastconnections/backend/internal/config"
	"leastconnections/backend/internal/httpapi"
	"leastconnections/backend/internal/protocol"
	"leastconnections/backend/internal/state"
)

func TestServerLifecycleAndHTTPStatus(t *testing.T) {
	store, srv, cleanup := startTestServer(t)
	defer cleanup()

	conn, err := net.Dial("tcp", srv.Addr().String())
	if err != nil {
		t.Fatalf("Dial() error: %v", err)
	}
	defer conn.Close()

	now := time.Now().UTC()
	writeLine(t, conn, fmt.Sprintf(`{"event":"hello","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"%s"}`, now.Format(time.RFC3339)))
	writeLine(t, conn, fmt.Sprintf(`{"event":"telemetry","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"%s","metrics":{"temperature_c":70.5,"spindle_rpm":4200,"completion_pct":15}}`, now.Add(time.Second).Format(time.RFC3339)))

	waitForCondition(t, func() bool {
		return store.Status().ActiveConnections == 1
	})

	machines := fetchMachines(t, store)
	if len(machines) != 1 {
		t.Fatalf("expected 1 active machine, got %d", len(machines))
	}
	if machines[0].TelemetryCount != 1 {
		t.Fatalf("expected telemetry_count 1, got %d", machines[0].TelemetryCount)
	}

	status := fetchStatus(t, store)
	if status.ActiveConnections != 1 {
		t.Fatalf("expected 1 active connection, got %d", status.ActiveConnections)
	}
	if status.TotalConnectionsAccepted != 1 {
		t.Fatalf("expected 1 accepted connection, got %d", status.TotalConnectionsAccepted)
	}

	writeLine(t, conn, fmt.Sprintf(`{"event":"done","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"%s"}`, now.Add(2*time.Second).Format(time.RFC3339)))
	waitForCondition(t, func() bool {
		status := store.Status()
		return status.ActiveConnections == 0 && status.TotalSessionsCompleted == 1
	})
}

func TestServerRejectsProtocolViolations(t *testing.T) {
	store, srv, cleanup := startTestServer(t)
	defer cleanup()

	conn, err := net.Dial("tcp", srv.Addr().String())
	if err != nil {
		t.Fatalf("Dial() error: %v", err)
	}

	now := time.Now().UTC()
	writeLine(t, conn, fmt.Sprintf(`{"event":"telemetry","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"%s","metrics":{"temperature_c":70.5}}`, now.Format(time.RFC3339)))
	_ = conn.Close()

	waitForCondition(t, func() bool {
		return store.Status().ProtocolErrors == 1
	})
}

func TestServerRejectsDuplicateHello(t *testing.T) {
	store, srv, cleanup := startTestServer(t)
	defer cleanup()

	conn, err := net.Dial("tcp", srv.Addr().String())
	if err != nil {
		t.Fatalf("Dial() error: %v", err)
	}
	defer conn.Close()

	now := time.Now().UTC()
	writeLine(t, conn, fmt.Sprintf(`{"event":"hello","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"%s"}`, now.Format(time.RFC3339)))
	writeLine(t, conn, fmt.Sprintf(`{"event":"hello","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"%s"}`, now.Add(time.Second).Format(time.RFC3339)))

	waitForCondition(t, func() bool {
		return store.Status().ProtocolErrors == 1
	})
}

func TestServerRejectsDoneBeforeHello(t *testing.T) {
	store, srv, cleanup := startTestServer(t)
	defer cleanup()

	conn, err := net.Dial("tcp", srv.Addr().String())
	if err != nil {
		t.Fatalf("Dial() error: %v", err)
	}
	defer conn.Close()

	now := time.Now().UTC()
	writeLine(t, conn, fmt.Sprintf(`{"event":"done","machine_id":"oven-01","machine_type":"oven","job_id":"job-1","timestamp":"%s"}`, now.Format(time.RFC3339)))

	waitForCondition(t, func() bool {
		return store.Status().ProtocolErrors == 1
	})
}

func TestServerCleansUpDroppedConnections(t *testing.T) {
	store, srv, cleanup := startTestServer(t)
	defer cleanup()

	connOne, err := net.Dial("tcp", srv.Addr().String())
	if err != nil {
		t.Fatalf("Dial() error: %v", err)
	}
	connTwo, err := net.Dial("tcp", srv.Addr().String())
	if err != nil {
		t.Fatalf("Dial() error: %v", err)
	}

	now := time.Now().UTC()
	writeLine(t, connOne, fmt.Sprintf(`{"event":"hello","machine_id":"cnc-01","machine_type":"cnc","job_id":"job-1","timestamp":"%s"}`, now.Format(time.RFC3339)))
	writeLine(t, connTwo, fmt.Sprintf(`{"event":"hello","machine_id":"oven-01","machine_type":"oven","job_id":"job-2","timestamp":"%s"}`, now.Add(time.Second).Format(time.RFC3339)))

	waitForCondition(t, func() bool {
		return store.Status().ActiveConnections == 2
	})

	_ = connOne.Close()
	_ = connTwo.Close()

	waitForCondition(t, func() bool {
		return store.Status().ActiveConnections == 0
	})
}

func startTestServer(t *testing.T) (*state.Store, net.Listener, func()) {
	t.Helper()

	cfg := config.File{
		MachineTypes: []config.MachineType{
			{Name: "cnc", AllowedMetrics: []string{"temperature_c", "spindle_rpm", "completion_pct"}},
			{Name: "conveyor", AllowedMetrics: []string{"motor_temp_c", "belt_speed_mps", "completion_pct"}},
			{Name: "oven", AllowedMetrics: []string{"chamber_temp_c", "power_kw", "completion_pct"}},
		},
	}

	store := state.NewStore()
	server := NewServer(store, protocol.NewValidator(cfg))

	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("Listen() error: %v", err)
	}

	go func() {
		_ = server.Serve(listener)
	}()

	return store, listener, func() {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		_ = server.Shutdown(ctx)
	}
}

func fetchMachines(t *testing.T, store *state.Store) []state.Session {
	t.Helper()

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest("GET", "/api/machines", nil)
	httpapi.NewHandler(store).ServeHTTP(recorder, request)

	if recorder.Code != 200 {
		t.Fatalf("unexpected status code: %d", recorder.Code)
	}

	var machines []state.Session
	if err := json.Unmarshal(recorder.Body.Bytes(), &machines); err != nil {
		t.Fatalf("json.Unmarshal() error: %v", err)
	}

	return machines
}

func fetchStatus(t *testing.T, store *state.Store) state.StatusSnapshot {
	t.Helper()

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest("GET", "/api/status", nil)
	httpapi.NewHandler(store).ServeHTTP(recorder, request)

	if recorder.Code != 200 {
		t.Fatalf("unexpected status code: %d", recorder.Code)
	}

	var status state.StatusSnapshot
	if err := json.Unmarshal(recorder.Body.Bytes(), &status); err != nil {
		t.Fatalf("json.Unmarshal() error: %v", err)
	}

	return status
}

func writeLine(t *testing.T, conn net.Conn, line string) {
	t.Helper()

	writer := bufio.NewWriter(conn)
	if _, err := writer.WriteString(line + "\n"); err != nil {
		t.Fatalf("WriteString() error: %v", err)
	}
	if err := writer.Flush(); err != nil {
		t.Fatalf("Flush() error: %v", err)
	}
}

func waitForCondition(t *testing.T, fn func() bool) {
	t.Helper()

	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if fn() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}

	t.Fatal("condition was not met before timeout")
}
