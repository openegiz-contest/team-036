#!/usr/bin/env python3
"""Console of the digital pit: serves the 3D stand and talks to the platform.

* GET  /ditto/api/2/...   read-only proxy to Eclipse Ditto (adds the Basic credentials, which never reach the browser);
                          the stand gets all twin data from the platform through it.
* POST /api/control       what-if scenarios and stand settings -> MQTT control/pit (the simulator subscribes).
* GET  /                  the stand (static/index.html, three.js is vendored: no CDN needed).
"""
import base64
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pit.sim import SCENARIOS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:8080").rstrip("/")
AUTH = "Basic " + base64.b64encode(
    f"{os.environ.get('DITTO_USER', 'ditto')}:{os.environ.get('DITTO_PASSWORD', '')}".encode()).decode()
PORT = int(os.environ.get("PORT", "8099"))
ALLOWED = ("/api/2/search/things", "/api/2/things")

mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"openegiz-pit-console-{os.getpid()}")
mq_ok = threading.Event()
mq.on_connect = lambda *a: mq_ok.set()
mq.on_disconnect = lambda *a: mq_ok.clear()


def mqtt_connect():
    host, port = os.environ.get("MQTT_HOST", "localhost"), int(os.environ.get("MQTT_PORT", "1883"))
    while True:
        try:
            mq.connect(host, port, keepalive=30)
            mq.loop_start()
            return
        except OSError:
            time.sleep(2)


def valid_control(c):
    if not isinstance(c, dict):
        return False
    cmd = c.get("cmd")
    if cmd == "scenario":
        return c.get("name") in SCENARIOS and isinstance(c.get("on"), bool)
    if cmd == "view":
        return c.get("view") in ("dispatcher", "baseline")
    if cmd == "speed":
        return isinstance(c.get("value"), (int, float)) and 1 <= c["value"] <= 120
    return False


class Handler(BaseHTTPRequestHandler):
    server_version = "pit-console"

    def log_message(self, fmt, *args):
        if os.environ.get("ACCESS_LOG"):
            super().log_message(fmt, *args)

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/healthz":
            return self._send(200, "ok", "text/plain")
        if url.path.startswith("/ditto/"):
            sub = url.path[len("/ditto"):]
            if not sub.startswith(ALLOWED):
                return self._send(403, '{"error":"forbidden"}')
            req = urllib.request.Request(DITTO_URL + sub + (f"?{url.query}" if url.query else ""),
                                         headers={"Authorization": AUTH, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return self._send(r.status, r.read())
            except urllib.error.HTTPError as e:
                return self._send(e.code, e.read() or b"{}")
            except (urllib.error.URLError, TimeoutError) as e:
                return self._send(502, json.dumps({"error": str(e)}))
        path = "/index.html" if url.path in ("/", "") else url.path
        full = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            return self._send(404, '{"error":"not found"}')
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path != "/api/control":
            return self._send(404, '{"error":"not found"}')
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)))
        except ValueError:
            return self._send(400, '{"error":"bad json"}')
        if not valid_control(body):
            return self._send(400, '{"error":"unknown command"}')
        if not mq_ok.is_set():
            return self._send(503, '{"error":"mqtt not connected"}')
        mq.publish("control/pit", json.dumps(body), qos=1)
        self._send(200, '{"ok":true}')


def main():
    threading.Thread(target=mqtt_connect, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"pit console on :{PORT}, Ditto {DITTO_URL}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
