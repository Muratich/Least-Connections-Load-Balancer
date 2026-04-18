package main

import (
	"context"
	"errors"
	"flag"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"leastconnections/backend/internal/config"
	"leastconnections/backend/internal/httpapi"
	"leastconnections/backend/internal/protocol"
	"leastconnections/backend/internal/state"
	"leastconnections/backend/internal/tcp"
)

func main() {
	tcpAddr := flag.String("tcp-addr", ":9000", "TCP listen address for telemetry ingestion")
	httpAddr := flag.String("http-addr", ":8080", "HTTP listen address for status API")
	configPath := flag.String("machine-config", "", "Path to machine type config JSON")
	flag.Parse()

	cfg, resolvedPath, err := loadMachineConfig(*configPath)
	if err != nil {
		log.Fatalf("load machine config: %v", err)
	}

	store := state.NewStore()
	validator := protocol.NewValidator(cfg)
	tcpServer := tcp.NewServer(store, validator)
	httpHandler := httpapi.NewHandler(store)

	tcpListener, err := net.Listen("tcp", *tcpAddr)
	if err != nil {
		log.Fatalf("listen TCP: %v", err)
	}
	defer tcpListener.Close()

	httpServer := &http.Server{
		Addr:              *httpAddr,
		Handler:           httpHandler,
		ReadHeaderTimeout: 5 * time.Second,
	}

	serverErr := make(chan error, 2)

	go func() {
		log.Printf("telemetry TCP listening on %s", tcpListener.Addr())
		serverErr <- tcpServer.Serve(tcpListener)
	}()

	go func() {
		log.Printf("status HTTP listening on %s", *httpAddr)
		serverErr <- httpServer.ListenAndServe()
	}()

	log.Printf("machine config loaded from %s", resolvedPath)

	signalCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	select {
	case err := <-serverErr:
		if err != nil && !errors.Is(err, net.ErrClosed) && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("server error: %v", err)
		}
	case <-signalCtx.Done():
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := tcpServer.Shutdown(shutdownCtx); err != nil {
		log.Printf("tcp shutdown error: %v", err)
	}
	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		log.Printf("http shutdown error: %v", err)
	}
}

func loadMachineConfig(explicitPath string) (config.File, string, error) {
	if explicitPath != "" {
		cfg, err := config.Load(explicitPath)
		return cfg, explicitPath, err
	}

	candidates := []string{
		"config/machine_types.json",
		"../config/machine_types.json",
		"./config/machine_types.json",
	}

	for _, candidate := range candidates {
		cfg, err := config.Load(candidate)
		if err == nil {
			return cfg, candidate, nil
		}
	}

	return config.File{}, "", errors.New("unable to resolve machine config path")
}
