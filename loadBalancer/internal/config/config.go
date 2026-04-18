package config

import (
	"encoding/json"
	"os"
)

type Backend struct {
	Host string `json:"host"`
	Port int    `json:"port"`
}

type Config struct {
	ListenAddr string    `json:"listen_addr"`
	Backends   []Backend `json:"backends"`
}

func Load(path string) (Config, error) {
	var cfg Config

	data, err := os.ReadFile(path)
	if err != nil {
		return cfg, err
	}

	err = json.Unmarshal(data, &cfg)

	return cfg, err
}