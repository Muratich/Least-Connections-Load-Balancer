package protocol

import (
	"testing"
	"time"

	"leastconnections/backend/internal/config"
)

func TestValidatorAcceptsKnownTelemetry(t *testing.T) {
	validator := NewValidator(config.File{
		MachineTypes: []config.MachineType{
			{
				Name:           "cnc",
				AllowedMetrics: []string{"temperature_c", "spindle_rpm", "completion_pct"},
			},
		},
	})

	msg := Message{
		Event:       EventTelemetry,
		MachineID:   "cnc-01",
		MachineType: "cnc",
		JobID:       "job-1",
		Timestamp:   time.Now().UTC(),
		Metrics: map[string]float64{
			"temperature_c": 70.5,
			"spindle_rpm":   3200,
		},
	}

	if err := validator.Validate(msg); err != nil {
		t.Fatalf("Validate() returned error: %v", err)
	}
}

func TestValidatorRejectsUnknownMachineType(t *testing.T) {
	validator := NewValidator(config.File{
		MachineTypes: []config.MachineType{
			{Name: "cnc", AllowedMetrics: []string{"temperature_c"}},
		},
	})

	msg := Message{
		Event:       EventHello,
		MachineID:   "oven-01",
		MachineType: "oven",
		JobID:       "job-1",
		Timestamp:   time.Now().UTC(),
	}

	if err := validator.Validate(msg); err == nil {
		t.Fatal("Validate() expected error for unknown machine type")
	}
}

func TestValidatorRejectsUnexpectedMetric(t *testing.T) {
	validator := NewValidator(config.File{
		MachineTypes: []config.MachineType{
			{Name: "conveyor", AllowedMetrics: []string{"motor_temp_c", "belt_speed_mps"}},
		},
	})

	msg := Message{
		Event:       EventTelemetry,
		MachineID:   "conv-01",
		MachineType: "conveyor",
		JobID:       "job-1",
		Timestamp:   time.Now().UTC(),
		Metrics: map[string]float64{
			"temperature_c": 88.1,
		},
	}

	if err := validator.Validate(msg); err == nil {
		t.Fatal("Validate() expected error for invalid metric")
	}
}
