package loadbalancer

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"net"
	"sync"
	"time"
)

const (
	ConnectionIdleTimeout = 120 * time.Second
	DialTimeout  = 5 * time.Second
)

type Backend struct {
	Host string
	Port int
}

func (b Backend) Addr() string {
	return fmt.Sprintf("%s:%d", b.Host, b.Port)
}

type LoadBalancer struct {
	backends []Backend

	mu       sync.Mutex
	activeConnections   map[string]int
	rrCursor uint64

	wg sync.WaitGroup
}

func NewLoadBalancer(backends []Backend) *LoadBalancer {
	activeConnections := make(map[string]int, len(backends))
	for _, b := range backends {
		activeConnections[b.Addr()] = 0
	}

	return &LoadBalancer{
		backends: backends,
		activeConnections:   activeConnections,
	}
}

func (lb *LoadBalancer) selectBackend() (string, bool) {
	lb.mu.Lock()
	defer lb.mu.Unlock()

	if len(lb.backends) == 0 {
		return "", false
	}

	minConn := math.MaxInt
	candidates := make([]string, 0, len(lb.backends))

	for _, b := range lb.backends {
		addr := b.Addr()
		count := lb.activeConnections[addr]

		if count < minConn {
			minConn = count
			candidates = candidates[:0]
			candidates = append(candidates, addr)
		} else if count == minConn {
			candidates = append(candidates, addr)
		}
	}

	if len(candidates) == 0 {
		return "", false
	}

	chosen := candidates[lb.rrCursor%uint64(len(candidates))]
	lb.rrCursor++
	lb.activeConnections[chosen]++

	return chosen, true
}

func (lb *LoadBalancer) releaseBackend(addr string) {
	lb.mu.Lock()
	defer lb.mu.Unlock()

	if lb.activeConnections[addr] > 0 {
		lb.activeConnections[addr]--
	}
}

func relay(src net.Conn, dst net.Conn) {
	buf := make([]byte, 4096)

	for {
		_ = src.SetReadDeadline(time.Now().Add(ConnectionIdleTimeout))

		n, err := src.Read(buf)
		if err != nil {
			return
		}

		_ = dst.SetWriteDeadline(time.Now().Add(ConnectionIdleTimeout))

		_, err = dst.Write(buf[:n])
		if err != nil {
			return
		}
	}
}

func (lb *LoadBalancer) handleClient(client net.Conn) {
	defer lb.wg.Done()
	defer client.Close()

	clientAddr := client.RemoteAddr().String()

	backendAddr, ok := lb.selectBackend()
	if !ok {
		log.Printf("No backend available for %s", clientAddr)
		return
	}

	defer lb.releaseBackend(backendAddr)

	log.Printf("Client %s -> %s", clientAddr, backendAddr)

	backend, err := net.DialTimeout("tcp", backendAddr, DialTimeout)
	if err != nil {
		log.Printf("Dial backend %s failed: %v", backendAddr, err)
		return
	}
	defer backend.Close()

	assignment, _ := json.Marshal(map[string]any{
	"event":   "assigned",
	"backend": backendAddr,
	"backends": lb.backendAddrs(),
	})
	assignment = append(assignment, '\n')

	if _, err := client.Write(assignment); err != nil {
		log.Printf("Send assignment to %s failed: %v", clientAddr, err)
		return
	}
	
	done := make(chan struct{}, 2)

	go func() {
		relay(client, backend)
		done <- struct{}{}
	}()

	go func() {
		relay(backend, client)
		done <- struct{}{}
	}()

	<-done
}

func (lb *LoadBalancer) Serve(ctx context.Context, addr string) error {
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	defer listener.Close()

	log.Printf("Load balancer listening on %s", addr)
	log.Printf("Backends loaded: %v", lb.backends)

	go func() {
		<-ctx.Done()
		log.Println("Shutdown signal received")
		_ = listener.Close()
	}()

	for {
		conn, err := listener.Accept()
		if err != nil {
			select {
			case <-ctx.Done():
				lb.wg.Wait()
				log.Println("Graceful shutdown complete")
				return nil
			default:
				continue
			}
		}

		lb.wg.Add(1)
		go lb.handleClient(conn)
	}
}

func (lb *LoadBalancer) backendAddrs() []string {
	lb.mu.Lock()
	defer lb.mu.Unlock()

	addrs := make([]string, 0, len(lb.backends))
	for _, b := range lb.backends {
		addrs = append(addrs, b.Addr())
	}
	return addrs
}