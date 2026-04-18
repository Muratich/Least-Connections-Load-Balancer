package protocol

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"leastconnections/backend/internal/config"
)

type Event string

const (
	EventHello     Event = "hello"
	EventTelemetry Event = "telemetry"
	EventDone      Event = "done"
)

type Message struct {
	Event       Event              `json:"event"`
	MachineID   string             `json:"machine_id"`
	MachineType string             `json:"machine_type"`
	JobID       string             `json:"job_id"`
	Timestamp   time.Time          `json:"timestamp"`
	Metrics     map[string]float64 `json:"metrics,omitempty"`
}

type Validator struct {
	allowedMetrics map[string]map[string]struct{}
}

func NewValidator(cfg config.File) *Validator {
	allowedMetrics := make(map[string]map[string]struct{}, len(cfg.MachineTypes))
	for _, machineType := range cfg.MachineTypes {
		metrics := make(map[string]struct{}, len(machineType.AllowedMetrics))
		for _, metric := range machineType.AllowedMetrics {
			metrics[metric] = struct{}{}
		}
		allowedMetrics[machineType.Name] = metrics
	}

	return &Validator{allowedMetrics: allowedMetrics}
}

func ParseLine(line []byte) (Message, error) {
	var msg Message
	if err := json.Unmarshal(line, &msg); err != nil {
		return Message{}, fmt.Errorf("decode JSON: %w", err)
	}
	return msg, nil
}

func (v *Validator) Validate(msg Message) error {
	if msg.Event == "" {
		return errors.New("event is required")
	}
	if msg.MachineID == "" {
		return errors.New("machine_id is required")
	}
	if msg.MachineType == "" {
		return errors.New("machine_type is required")
	}
	if msg.JobID == "" {
		return errors.New("job_id is required")
	}
	if msg.Timestamp.IsZero() {
		return errors.New("timestamp is required")
	}

	switch msg.Event {
	case EventHello, EventTelemetry, EventDone:
	default:
		return fmt.Errorf("unsupported event %q", msg.Event)
	}

	metrics, exists := v.allowedMetrics[msg.MachineType]
	if !exists {
		return fmt.Errorf("unknown machine_type %q", msg.MachineType)
	}

	if msg.Event == EventTelemetry && len(msg.Metrics) == 0 {
		return errors.New("telemetry event requires metrics")
	}

	for metricName := range msg.Metrics {
		if _, allowed := metrics[metricName]; !allowed {
			return fmt.Errorf("metric %q is not allowed for machine_type %q", metricName, msg.MachineType)
		}
	}

	return nil
}

func CopyMetrics(metrics map[string]float64) map[string]float64 {
	if len(metrics) == 0 {
		return map[string]float64{}
	}

	cloned := make(map[string]float64, len(metrics))
	for key, value := range metrics {
		cloned[key] = value
	}

	return cloned
}

func (e Event) String() string {
	return string(e)
}

func NormalizeLine(line string) string {
	return strings.TrimSpace(line)
}
