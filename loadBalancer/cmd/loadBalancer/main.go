package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"leastconnections/loadBalancer/internal/config"
	lb "leastconnections/loadBalancer/internal/loadBalancer"
)

func main() {
	configPath := flag.String("config", "config/backends.json", "path to config")
	flag.Parse()	

	cfg, err := config.Load(*configPath)
	if err != nil {
		log.Fatal(err)
	}

	backends := make([]lb.Backend, 0, len(cfg.Backends))

	for _, b := range cfg.Backends {
		backends = append(backends, lb.Backend{
			Host: b.Host,
			Port: b.Port,
		})
	}

	balancer := lb.NewLoadBalancer(backends)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM,)
	defer stop()

	if err := balancer.Serve(ctx, cfg.ListenAddr); err != nil {
		log.Fatal(err)
	}
}