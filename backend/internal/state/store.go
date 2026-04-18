package state

import (
	"fmt"
	"sort"
	"sync"
	"sync/atomic"
	"time"

	"leastconnections/backend/internal/protocol"
)

type Store struct {
	mu sync.RWMutex

	nextConnectionID atomic.Uint64
	sessions         map[string]*Session
	counters         Counters
}

type Session struct {
	ConnectionID   string             `json:"connection_id"`
	MachineID      string             `json:"machine_id"`
	MachineType    string             `json:"machine_type"`
	JobID          string             `json:"job_id"`
	Status         string             `json:"status"`
	ConnectedAt    time.Time          `json:"connected_at"`
	LastSeenAt     time.Time          `json:"last_seen_at"`
	TelemetryCount uint64             `json:"telemetry_count"`
	LastMetrics    map[string]float64 `json:"last_metrics"`
}

type Counters struct {
	TotalConnectionsAccepted uint64 `json:"total_connections_accepted"`
	TotalSessionsCompleted   uint64 `json:"total_sessions_completed"`
	ProtocolErrors           uint64 `json:"protocol_errors"`
}

type StatusSnapshot struct {
	ActiveConnections        uint64 `json:"active_connections"`
	TotalConnectionsAccepted uint64 `json:"total_connections_accepted"`
	TotalSessionsCompleted   uint64 `json:"total_sessions_completed"`
	ProtocolErrors           uint64 `json:"protocol_errors"`
}

func NewStore() *Store {
	return &Store{
		sessions: make(map[string]*Session),
	}
}

func (s *Store) OpenConnection() string {
	id := s.nextConnectionID.Add(1)
	connectionID := fmt.Sprintf("conn-%06d", id)

	s.mu.Lock()
	defer s.mu.Unlock()
	s.counters.TotalConnectionsAccepted++

	return connectionID
}

func (s *Store) BeginSession(connectionID string, msg protocol.Message, connectedAt time.Time) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.sessions[connectionID]; exists {
		return fmt.Errorf("connection %s already has an active session", connectionID)
	}

	s.sessions[connectionID] = &Session{
		ConnectionID:   connectionID,
		MachineID:      msg.MachineID,
		MachineType:    msg.MachineType,
		JobID:          msg.JobID,
		Status:         "connected",
		ConnectedAt:    connectedAt.UTC(),
		LastSeenAt:     msg.Timestamp.UTC(),
		TelemetryCount: 0,
		LastMetrics:    protocol.CopyMetrics(msg.Metrics),
	}

	return nil
}

func (s *Store) UpdateTelemetry(connectionID string, msg protocol.Message) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	session, exists := s.sessions[connectionID]
	if !exists {
		return fmt.Errorf("connection %s has no active session", connectionID)
	}

	session.Status = "running"
	session.LastSeenAt = msg.Timestamp.UTC()
	session.TelemetryCount++
	session.LastMetrics = protocol.CopyMetrics(msg.Metrics)

	return nil
}

func (s *Store) CompleteSession(connectionID string, msg protocol.Message) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	session, exists := s.sessions[connectionID]
	if !exists {
		return fmt.Errorf("connection %s has no active session", connectionID)
	}

	session.Status = "done"
	session.LastSeenAt = msg.Timestamp.UTC()
	if len(msg.Metrics) > 0 {
		session.LastMetrics = protocol.CopyMetrics(msg.Metrics)
	}

	delete(s.sessions, connectionID)
	s.counters.TotalSessionsCompleted++

	return nil
}

func (s *Store) RemoveConnection(connectionID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.sessions, connectionID)
}

func (s *Store) IncrementProtocolError() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.counters.ProtocolErrors++
}

func (s *Store) Status() StatusSnapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()

	return StatusSnapshot{
		ActiveConnections:        uint64(len(s.sessions)),
		TotalConnectionsAccepted: s.counters.TotalConnectionsAccepted,
		TotalSessionsCompleted:   s.counters.TotalSessionsCompleted,
		ProtocolErrors:           s.counters.ProtocolErrors,
	}
}

func (s *Store) Machines() []Session {
	s.mu.RLock()
	defer s.mu.RUnlock()

	machines := make([]Session, 0, len(s.sessions))
	for _, session := range s.sessions {
		machines = append(machines, Session{
			ConnectionID:   session.ConnectionID,
			MachineID:      session.MachineID,
			MachineType:    session.MachineType,
			JobID:          session.JobID,
			Status:         session.Status,
			ConnectedAt:    session.ConnectedAt,
			LastSeenAt:     session.LastSeenAt,
			TelemetryCount: session.TelemetryCount,
			LastMetrics:    protocol.CopyMetrics(session.LastMetrics),
		})
	}

	sort.Slice(machines, func(i, j int) bool {
		if machines[i].MachineID == machines[j].MachineID {
			return machines[i].ConnectionID < machines[j].ConnectionID
		}
		return machines[i].MachineID < machines[j].MachineID
	})

	return machines
}
