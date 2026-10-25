#!/usr/bin/env python3
"""Create or update the twins of the digital pit in Ditto (idempotent PUTs)."""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

from pit.twins import definitions

DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:8080").rstrip("/")
DITTO_USER = os.environ.get("DITTO_USER", "ditto")
DITTO_PASSWORD = os.environ["DITTO_PASSWORD"]
AUTH = "Basic " + base64.b64encode(f"{DITTO_USER}:{DITTO_PASSWORD}".encode()).decode()


def put(thing_id, body):
    req = urllib.request.Request(f"{DITTO_URL}/api/2/things/{thing_id}", data=json.dumps(body).encode(), method="PUT",
                                 headers={"Authorization": AUTH, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def main():
    twins = definitions()
    for thing_id, body in twins.items():          # pit-01 first: children reference it
        for attempt in range(30):
            try:
                st = put(thing_id, body)
                print(f"{'created' if st == 201 else 'updated'}  {thing_id}")
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 29:
                    print(f"FAILED   {thing_id}: {exc}", file=sys.stderr)
                    return 1
                time.sleep(3)
    print(f"{len(twins)} twins ready in {DITTO_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
