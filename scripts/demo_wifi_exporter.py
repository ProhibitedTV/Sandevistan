#!/usr/bin/env python3
"""Serve demo Wi-Fi measurements over HTTP for the fusion CLI."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class DemoWiFiHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path not in {"/", "/wifi"}:
            self.send_error(404, "Not Found")
            return

        now = time.time()
        payload = [
            {
                "timestamp": now,
                "rssi": -48.0,
                "csi": [0.12, 0.18, 0.05, 0.09],
            }
        ]
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D401
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve demo Wi-Fi telemetry JSON.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), DemoWiFiHandler)
    print(f"Demo Wi-Fi exporter listening on http://{args.host}:{args.port}/wifi")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
