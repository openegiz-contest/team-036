#!/usr/bin/env python3
"""Local stand-in for Eclipse Ditto, for developing the UI without Docker.

Keeps the twins of the digital pit in memory, applies the Ditto-protocol `modify` commands that arrive on MQTT
telemetry/#, and serves /api/2/search/things the way Ditto does ({"items": [...]}).  NOT used by `make`.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pit.twins import definitions  # noqa: E402

THINGS = {}
for tid, body in definitions().items():
    THINGS[tid] = {"thingId": tid, "policyId": body["policyId"], "attributes": body["attributes"], "features": body["features"]}
LOCK = threading.Lock()


def on_message(_c, _u, msg):
    try:
        cmd = json.loads(msg.payload)
        ns, name = cmd["topic"].split("/")[:2]
        tid = f"{ns}:{name}"
        with LOCK:
            feats = THINGS[tid]["features"]
            for f, v in cmd["value"].items():
                feats[f] = v
    except Exception as exc:  # noqa: BLE001
        print("bad message", exc, file=sys.stderr)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlsplit(self.path)
        if not u.path.startswith("/api/2/search/things"):
            self.send_response(404)
            self.end_headers()
            return
        fields = parse_qs(u.query).get("fields", [""])[0].split(",") if "fields" in parse_qs(u.query) else None
        with LOCK:
            items = []
            for t in THINGS.values():
                items.append({k: v for k, v in t.items() if (not fields or k in fields)})
            body = json.dumps({"items": items}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    c.on_message = on_message
    c.connect("localhost", 1883)
    c.subscribe("telemetry/#")
    c.loop_start()
    ThreadingHTTPServer(("127.0.0.1", 18080), H).serve_forever()
