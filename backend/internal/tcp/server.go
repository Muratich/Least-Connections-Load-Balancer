package tcp

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"strings"
	"sync"
	"time"

	"leastconnections/backend/internal/protocol"
	"leastconnections/backend/internal/state"
)

type Server struct {
	store     *state.Store
	validator *protocol.Validator

	mu       sync.Mutex
	listener net.Listener
	conns    map[string]net.Conn
	wg       sync.WaitGroup
}

func NewServer(store *state.Store, validator *protocol.Validator) *Server {
	return &Server{
		store:     store,
		validator: validator,
		conns:     make(map[string]net.Conn),
	}
}

func (s *Server) Serve(listener net.Listener) error {
	s.mu.Lock()
	s.listener = listener
	s.mu.Unlock()

	for {
		conn, err := listener.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return err
			}

			var netErr net.Error
			if errors.As(err, &netErr) && netErr.Temporary() {
				log.Printf("temporary accept error: %v", err)
				time.Sleep(100 * time.Millisecond)
				continue
			}

			return err
		}

		connectionID := s.store.OpenConnection()
		s.trackConnection(connectionID, conn)

		s.wg.Add(1)
		go func(id string, c net.Conn) {
			defer s.wg.Done()
			s.handleConnection(id, c)
		}(connectionID, conn)
	}
}

func (s *Server) Shutdown(ctx context.Context) error {
	s.mu.Lock()
	listener := s.listener
	activeConns := make([]net.Conn, 0, len(s.conns))
	for _, conn := range s.conns {
		activeConns = append(activeConns, conn)
	}
	s.mu.Unlock()

	if listener != nil {
		_ = listener.Close()
	}
	for _, conn := range activeConns {
		_ = conn.Close()
	}

	done := make(chan struct{})
	go func() {
		s.wg.Wait()
		close(done)
	}()

	select {
	case <-done:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (s *Server) handleConnection(connectionID string, conn net.Conn) {
	defer func() {
		s.untrackConnection(connectionID)
		s.store.RemoveConnection(connectionID)
		_ = conn.Close()
	}()

	reader := bufio.NewScanner(conn)
	reader.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	sessionStarted := false
	connectedAt := time.Now().UTC()

	for reader.Scan() {
		line := strings.TrimSpace(reader.Text())
		if line == "" {
			continue
		}

		msg, err := protocol.ParseLine([]byte(line))
		if err != nil {
			s.recordProtocolError(connectionID, err)
			return
		}

		if err := s.validator.Validate(msg); err != nil {
			s.recordProtocolError(connectionID, err)
			return
		}

		switch msg.Event {
		case protocol.EventHello:
			if sessionStarted {
				s.recordProtocolError(connectionID, fmt.Errorf("duplicate hello on connection %s", connectionID))
				return
			}
			if err := s.store.BeginSession(connectionID, msg, connectedAt); err != nil {
				s.recordProtocolError(connectionID, err)
				return
			}
			sessionStarted = true
		case protocol.EventTelemetry:
			if !sessionStarted {
				s.recordProtocolError(connectionID, fmt.Errorf("telemetry before hello on connection %s", connectionID))
				return
			}
			if err := s.store.UpdateTelemetry(connectionID, msg); err != nil {
				s.recordProtocolError(connectionID, err)
				return
			}
		case protocol.EventDone:
			if !sessionStarted {
				s.recordProtocolError(connectionID, fmt.Errorf("done before hello on connection %s", connectionID))
				return
			}
			if err := s.store.CompleteSession(connectionID, msg); err != nil {
				s.recordProtocolError(connectionID, err)
				return
			}
			return
		}
	}

	if err := reader.Err(); err != nil && !errors.Is(err, io.EOF) && !errors.Is(err, net.ErrClosed) {
		log.Printf("connection %s read error: %v", connectionID, err)
	}
}

func (s *Server) recordProtocolError(connectionID string, err error) {
	s.store.IncrementProtocolError()
	log.Printf("protocol error on %s: %v", connectionID, err)
}

func (s *Server) trackConnection(connectionID string, conn net.Conn) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.conns[connectionID] = conn
}

func (s *Server) untrackConnection(connectionID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.conns, connectionID)
}
