#!/usr/bin/env python3
"""小型的下游回声服务，用来演示 Automation 的真实 dispatch（不是 mock）。

    .venv/bin/python scripts/echo_downstream.py --port 18080
    POST http://127.0.0.1:18080/hooks/smart-edit  {"...": "..."}
    -> 200 {"accepted": true, "echo": {...}, "received_at": "..."}

它只绑定 127.0.0.1，并且只回显收到的 JSON；没有鉴权、没有持久化，仅用于本地/演示验证。
服务端要允许它：`SMART_EDIT_AUTOMATION_ALLOWED_HOSTS=127.0.0.1` + `..._ALLOW_HTTP=1`。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class EchoHandler(BaseHTTPRequestHandler):
    server_version = "smart-edit-echo/1.0"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path.rstrip("/") in ("/health", ""):
            self._json(200, {"status": "ok"})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            self._json(400, {"error": "invalid_json"})
            return
        receipt = {
            "accepted": True,
            "path": self.path,
            "authorization": (
                "present" if self.headers.get("Authorization") else "absent"
            ),
            "api_key": "present" if self.headers.get("X-Api-Key") else "absent",
            "echo": payload,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        print(
            f"{datetime.now().strftime('%H:%M:%S')} POST {self.path} "
            f"values={list((payload.get('values') or {}).keys())}",
            flush=True,
        )
        self._json(200, receipt)

    def log_message(self, fmt, *args):  # keep the terminal readable
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), EchoHandler)
    print(f"echo downstream listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())