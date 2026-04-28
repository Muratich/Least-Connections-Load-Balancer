import subprocess
import os
import sys
import time

BACKEND_1_TCP, BACKEND_1_HTTP = ":9001", ":8081"
BACKEND_2_TCP, BACKEND_2_HTTP = ":9002", ":8082"
BACKEND_3_TCP, BACKEND_3_HTTP = ":9003", ":8083"

LB_LISTEN_PORT = ":8000"

SIM_TARGET_HOST = "127.0.0.1"
SIM_TARGET_PORT = "8000"
SIM_HTTP_ADDR = "127.0.0.1:8100"

processes = []

def run_all():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(current_dir, ".."))
    backend_dir = os.path.join(root_dir, "backend")
    lb_dir = os.path.join(root_dir, "loadBalancer")

    configs = [
        {"cmd": ["go", "run", "./cmd/server", "--tcp-addr", BACKEND_1_TCP, "--http-addr", BACKEND_1_HTTP, "--machine-config", "../config/machine_types.json"], "cwd": backend_dir},
        {"cmd": ["go", "run", "./cmd/server", "--tcp-addr", BACKEND_2_TCP, "--http-addr", BACKEND_2_HTTP, "--machine-config", "../config/machine_types.json"], "cwd": backend_dir},
        {"cmd": ["go", "run", "./cmd/server", "--tcp-addr", BACKEND_3_TCP, "--http-addr", BACKEND_3_HTTP, "--machine-config", "../config/machine_types.json"], "cwd": backend_dir},
        {"cmd": ["go", "run", "./cmd/loadBalancer", "--config", "../config/backends-localRun.json"], "cwd": lb_dir},
        {"cmd": ["python", "-m", "simulator", "--target-host", SIM_TARGET_HOST, "--target-port", SIM_TARGET_PORT, "--http-addr", SIM_HTTP_ADDR, "--machine-config", "config/machine_types.json"], "cwd": root_dir}
    ]

    print("Starting system...")

    for item in configs:
        try:
            p = subprocess.Popen(item["cmd"], cwd=item["cwd"])
            processes.append(p)
            time.sleep(0.5)
        except Exception as e:
            print(f"Failed to start: {e}")
            cleanup()

    print("System is running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()

def cleanup():
    print("\nShutting down...")
    for p in processes:
        if p.poll() is None:
            p.terminate()
    time.sleep(1)
    for p in processes:
        if p.poll() is None:
            p.kill()
    sys.exit(0)

if __name__ == "__main__":
    run_all()