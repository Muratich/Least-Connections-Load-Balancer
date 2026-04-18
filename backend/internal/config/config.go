package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
)

type File struct {
	MachineTypes []MachineType `json:"machine_types"`
}

type MachineType struct {
	Name                string        `json:"name"`
	DisplayName         string        `json:"display_name"`
	AllowedMetrics      []string      `json:"allowed_metrics"`
	TelemetryIntervalMS int           `json:"telemetry_interval_ms"`
	RunDurationSeconds  DurationRange `json:"run_duration_seconds"`
}

type DurationRange struct {
	Min int `json:"min"`
	Max int `json:"max"`
}

func Load(path string) (File, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return File{}, err
	}

	var cfg File
	if err := json.Unmarshal(data, &cfg); err != nil {
		return File{}, fmt.Errorf("decode machine config: %w", err)
	}

	if err := cfg.Validate(); err != nil {
		return File{}, err
	}

	return cfg, nil
}

func (f File) Validate() error {
	if len(f.MachineTypes) == 0 {
		return errors.New("machine config must define at least one machine type")
	}

	seenNames := make(map[string]struct{}, len(f.MachineTypes))
	for _, machineType := range f.MachineTypes {
		if machineType.Name == "" {
			return errors.New("machine type name is required")
		}
		if _, exists := seenNames[machineType.Name]; exists {
			return fmt.Errorf("duplicate machine type: %s", machineType.Name)
		}
		seenNames[machineType.Name] = struct{}{}

		if len(machineType.AllowedMetrics) == 0 {
			return fmt.Errorf("machine type %s must define allowed metrics", machineType.Name)
		}
		if machineType.TelemetryIntervalMS <= 0 {
			return fmt.Errorf("machine type %s must define a positive telemetry interval", machineType.Name)
		}
		if machineType.RunDurationSeconds.Min <= 0 || machineType.RunDurationSeconds.Max <= 0 {
			return fmt.Errorf("machine type %s must define positive duration bounds", machineType.Name)
		}
		if machineType.RunDurationSeconds.Min > machineType.RunDurationSeconds.Max {
			return fmt.Errorf("machine type %s has invalid duration range", machineType.Name)
		}
	}

	return nil
}
