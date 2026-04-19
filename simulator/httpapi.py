import asyncio
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .controller import SimulatorController

STATIC_DIR = Path(__file__).with_name("static")


class SimulatorHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        controller: SimulatorController,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__(server_address, SimulatorRequestHandler)
        self.controller = controller
        self.loop = loop


class SimulatorRequestHandler(BaseHTTPRequestHandler):
    server: SimulatorHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = self._path()
        if path in {"/", "/index.html"}:
            self._write_file(STATIC_DIR / "index.html")
            return
        if path.startswith("/static/"):
            self._serve_static(path)
            return
        if path == "/healthz":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/api/config/machine-types":
            self._write_json(HTTPStatus.OK, self.server.controller.machine_config.to_json())
            return
        if path == "/api/status":
            self._write_json(HTTPStatus.OK, self._call(self.server.controller.status()))
            return
        if path == "/api/machines":
            self._write_json(HTTPStatus.OK, self._call(self.server.controller.machines()))
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_PUT(self) -> None:
        path = self._path()
        if path == "/api/load":
            payload = self._read_json_or_error()
            if payload is not None:
                self._handle_controller_call(self.server.controller.set_load(payload))
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        path = self._path()
        if path == "/api/machines":
            payload = self._read_json_or_error()
            if payload is not None:
                self._handle_controller_call(self.server.controller.spawn_manual(payload))
            return
        if path == "/api/stop":
            self._handle_controller_call(self.server.controller.stop_all())
            return

        prefix = "/api/machines/"
        suffix = "/break"
        if path.startswith(prefix) and path.endswith(suffix):
            machine_id = unquote(path[len(prefix) : -len(suffix)])
            self._handle_controller_call(self.server.controller.break_machine(machine_id))
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _handle_controller_call(self, coro: Any) -> None:
        try:
            self._write_json(HTTPStatus.OK, self._call(coro))
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except KeyError as exc:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": f"unknown machine {exc.args[0]!r}"})

    def _call(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self.server.loop)
        return future.result(timeout=30)

    def _path(self) -> str:
        return urlparse(self.path).path.rstrip("/") or "/"

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length == 0:
            return {}

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _read_json_or_error(self) -> dict[str, Any] | None:
        try:
            return self._read_json()
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return None

    def _write_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> None:
        relative = unquote(path.removeprefix("/static/"))
        candidate = (STATIC_DIR / relative).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        self._write_file(candidate)

    def _write_file(self, path: Path) -> None:
        if not path.is_file():
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return
