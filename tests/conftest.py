"""Shared fixture: a local mock Solti API (ThreadingHTTPServer on 127.0.0.1)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from solti import SoltiClient


class RecordedRequest:
    def __init__(self, method: str, path: str, query: dict[str, list[str]],
                 headers: dict[str, str], body: Any) -> None:
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body


class MockAPI:
    """Routes requests to a responder callable; records every request."""

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self._responder: Callable[[RecordedRequest], tuple[int, dict[str, str], Any]] | None = None
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/1"

    def respond_with(
        self, responder: Callable[[RecordedRequest], tuple[int, dict[str, str], Any]]
    ) -> None:
        self._responder = responder

    def calls(self, method: str | None = None, path: str | None = None) -> list[RecordedRequest]:
        with self._lock:
            snapshot = list(self.requests)
        return [
            r
            for r in snapshot
            if (method is None or r.method == method) and (path is None or r.path == path)
        ]

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        api = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                split = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", "replace")
                request = RecordedRequest(
                    method=self.command,
                    path=split.path,
                    query=parse_qs(split.query),
                    headers={k: v for k, v in self.headers.items()},
                    body=body,
                )
                with api._lock:
                    api.requests.append(request)
                responder = api._responder
                if responder is None:
                    status, headers, payload = 404, {}, {"message": "no responder configured"}
                else:
                    status, headers, payload = responder(request)
                data = json.dumps(payload).encode("utf-8") if payload is not None else b""
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if data:
                    self.wfile.write(data)

            do_GET = do_POST = do_PATCH = do_DELETE = _handle

            def log_message(self, format: str, *args: Any) -> None:  # silence test output
                pass

        return Handler


@pytest.fixture()
def mock_api():
    api = MockAPI()
    yield api
    api.stop()


@pytest.fixture()
def client(mock_api: MockAPI) -> SoltiClient:
    return SoltiClient(api_key="test-key", api_url=mock_api.base_url, project_id="proj-123")


def json_response(status: int = 200, payload: Any = None,
                  headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], Any]:
    return status, headers or {}, payload
