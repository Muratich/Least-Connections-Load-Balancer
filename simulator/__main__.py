import argparse
import asyncio
import contextlib
import signal
import threading

from .config import MachineConfig
from .controller import SimulatorController
from .httpapi import SimulatorHTTPServer


def parse_addr(value: str) -> tuple[str, int]:
    if ":" not in value:
        raise argparse.ArgumentTypeError("address must be in host:port format")
    host, raw_port = value.rsplit(":", 1)
    if not host:
        host = "127.0.0.1"
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if port <= 0 or port > 65535:
        raise argparse.ArgumentTypeError("port must be in range 1..65535")
    return host, port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Virtual factory load simulator master")
    parser.add_argument("--target-host", default="127.0.0.1", help="TCP load balancer host")
    parser.add_argument("--target-port", type=int, default=8000, help="TCP load balancer port")
    parser.add_argument(
        "--http-addr",
        type=parse_addr,
        default=("127.0.0.1", 8100),
        help="HTTP master listen address in host:port format",
    )
    parser.add_argument(
        "--machine-config",
        default="config/machine_types.json",
        help="path to shared machine_types.json",
    )
    return parser


async def async_main() -> None:
    args = build_parser().parse_args()
    machine_config = MachineConfig.load(args.machine_config)
    controller = SimulatorController(machine_config, args.target_host, args.target_port)
    await controller.start()

    loop = asyncio.get_running_loop()
    httpd = SimulatorHTTPServer(args.http_addr, controller, loop)
    thread = threading.Thread(target=httpd.serve_forever, name="simulator-http", daemon=True)
    thread.start()

    host, port = httpd.server_address
    print(f"simulator HTTP listening on http://{host}:{port}")
    print(f"simulator TCP target is {args.target_host}:{args.target_port}")

    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        await controller.shutdown()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
