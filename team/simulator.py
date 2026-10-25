#!/usr/bin/env python3
"""Digital pit simulator: runs both worlds (dispatcher / fixed assignment) and publishes the twins to MQTT.

Each twin is updated with a Ditto-protocol `modify` command on telemetry/<name>, as a field gateway would.
The control topic control/pit carries what-if scenarios and stand settings from the console:
    {"cmd": "scenario", "name": "rain", "on": true}   {"cmd": "view", "view": "baseline"}   {"cmd": "speed", "value": 20}
"""
import argparse
import json
import logging
import os
import queue
import signal
import sys
import time

import paho.mqtt.client as mqtt

from pit.sim import SCENARIOS, Mine
from pit.twins import NS, snapshot

log = logging.getLogger("pit")
SLOW = ("face-", "road-", "rompad", "wastedump")        # twins republished every few ticks unless they change


def modify(name, features):
    return {"topic": f"{NS}/{name}/things/twin/commands/modify", "path": "/features",
            "value": {f: {"properties": p} for f, p in features.items()}}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mqtt-host", default=os.environ.get("MQTT_HOST", "localhost"))
    p.add_argument("--mqtt-port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    p.add_argument("--interval", type=float, default=float(os.environ.get("SIM_INTERVAL", "2")), help="real seconds per publish")
    p.add_argument("--speedup", type=float, default=float(os.environ.get("SIM_SPEEDUP", "20")), help="simulated s per real s")
    p.add_argument("--preroll", type=float, default=float(os.environ.get("SIM_PREROLL", "10800")), help="simulated s before the first publish")
    p.add_argument("--seed", type=int, default=int(os.environ.get("SIM_SEED", "7")))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--steps", type=int, default=0, help="stop after N publishes (0 = forever)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    mine = Mine(args.seed)
    mine.run(args.preroll)
    speedup = args.speedup
    commands = queue.Queue()
    events = []                                    # scenario log shown on the stand

    client = None
    if not args.dry_run:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"openegiz-pit-sim-{os.getpid()}")

        def on_connect(c, *_):
            c.subscribe("control/pit", qos=1)

        def on_message(_c, _u, msg):
            try:
                commands.put(json.loads(msg.payload))
            except ValueError:
                log.warning("bad control message %r", msg.payload[:80])

        client.on_connect, client.on_message = on_connect, on_message
        for _ in range(60):
            try:
                client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
                break
            except OSError as exc:
                log.warning("MQTT %s:%s not reachable (%s), retrying", args.mqtt_host, args.mqtt_port, exc)
                time.sleep(2)
        else:
            return 1
        client.loop_start()
        log.info("publishing to mqtt://%s:%s every %.1fs at %.0fx", args.mqtt_host, args.mqtt_port, args.interval, speedup)

    stop = False

    def on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    last = {}
    tick = 0
    while not stop:
        while not commands.empty():
            c = commands.get()
            cmd = c.get("cmd")
            if cmd == "scenario" and c.get("name") in SCENARIOS:
                on = bool(c.get("on"))
                mine.scenario(c["name"], on)
                events.append(f"{mine.shown.clock()} {'ВКЛ' if on else 'ОТМЕНА'}: {SCENARIOS[c['name']]}")
                log.info("scenario %s -> %s", c["name"], on)
            elif cmd == "view":
                mine.set_view(c.get("view"))
            elif cmd == "speed":
                speedup = min(120.0, max(1.0, float(c.get("value", speedup))))
        steps = max(1, int(args.interval * speedup / 2.0))
        for _ in range(steps):
            mine.step(2.0)
        snap = snapshot(mine, {"scenario_log": "\n".join(events[-6:])}, speedup)
        for name, feats in snap.items():
            body = json.dumps(modify(name, feats), ensure_ascii=False)
            if name.startswith(SLOW) and tick % 4 and last.get(name) == body:
                continue
            last[name] = body
            if client:
                client.publish(f"telemetry/{name}", body, qos=0)
            elif tick == 0 and name in ("truck-01", "dispatcher-01"):
                print(body)
        tick += 1
        if tick % 30 == 0:
            kd, kb = mine.worlds["dispatcher"].kpi(3600), mine.worlds["baseline"].kpi(3600)
            log.info("%s | ore/h disp %.0f vs base %.0f | idle%% disp %.1f vs base %.1f",
                     mine.shown.clock(), kd["ore_rate"], kb["ore_rate"], kd["idle_pct"], kb["idle_pct"])
        if args.steps and tick >= args.steps:
            break
        time.sleep(args.interval)
    if client:
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
