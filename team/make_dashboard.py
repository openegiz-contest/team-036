#!/usr/bin/env python3
"""Generate dashboard.json (Grafana, InfluxDB datasource of the platform) for the digital pit."""
import json

DS = {"type": "influxdb", "uid": "opentwins-influxdb"}
NS = "org.openegiz.pit"


def q(thing, field, extra=""):
    return (f'from(bucket: "default")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
            f'  |> filter(fn: (r) => r.thingId == "{NS}:{thing}" and r._field == "value_{field}_properties_value")\n'
            f'  |> keep(columns: ["_time", "_value"]){extra}')


def multi(regex, field, label_fn="r.thingId"):
    return (f'from(bucket: "default")\n  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
            f'  |> filter(fn: (r) => r.thingId =~ /^{regex}/ and r._field == "value_{field}_properties_value")\n'
            f'  |> map(fn: (r) => ({{_time: r._time, _value: r._value, twin: {label_fn}}}))\n'
            f'  |> group(columns: ["twin"])\n  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)')


def stat(i, title, x, y, w, h, thing, field, unit, color, dec=1):
    return {"id": i, "type": "stat", "title": title, "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "fieldConfig": {"defaults": {"unit": unit, "decimals": dec, "color": {"mode": "fixed", "fixedColor": color}}, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "value",
                        "graphMode": "area", "textMode": "value"},
            "targets": [{"refId": "A", "datasource": DS, "query": q(thing, field)}]}


def ts(i, title, x, y, w, h, targets, unit="none"):
    return {"id": i, "type": "timeseries", "title": title, "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 8, "showPoints": "never"}}, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
            "targets": [{"refId": chr(65 + k), "datasource": DS, "query": t, "alias": a} for k, (a, t) in enumerate(targets)]}


def named(thing, field, name):
    return (name, q(thing, field, f'\n  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)\n  |> set(key: "_field", value: "{name}")'))


panels = [
    stat(1, "Простой в очередях, с диспетчером, %", 0, 0, 6, 4, "dispatcher-01", "idle_pct_dispatch", "percent", "#3ecf8e"),
    stat(2, "Простой в очередях, без диспетчера, %", 6, 0, 6, 4, "dispatcher-01", "idle_pct_baseline", "percent", "#f5c542"),
    stat(3, "Сэкономлено простоя, маш-ч", 12, 0, 6, 4, "dispatcher-01", "idle_saved_h", "none", "#3ecf8e", 2),
    stat(4, "Добавлено руды диспетчером, т", 18, 0, 6, 4, "dispatcher-01", "ore_gain_t", "masst", "#5aa9e6", 0),
    ts(5, "Простой самосвалов в очередях, % парка (за час)", 0, 4, 12, 8,
       [named("dispatcher-01", "idle_pct_dispatch", "с диспетчером"), named("dispatcher-01", "idle_pct_baseline", "без диспетчера")], "percent"),
    ts(6, "Руда на ДК-1 и ROM, т/ч (за час)", 12, 4, 12, 8,
       [named("dispatcher-01", "ore_rate_dispatch", "с диспетчером"), named("dispatcher-01", "ore_rate_baseline", "без диспетчера")]),
    ts(7, "Очередь у экскаваторов, самосвалов", 0, 12, 8, 8, [(f"Э-{i}", multi(f"{NS}:shovel-0{i}$", "queue_len")) for i in (1, 2, 3)]),
    ts(8, "Дробилка: уровень бункера, %", 8, 12, 8, 8, [named("crusher-01", "bin_pct", "бункер ДК-1")], "percent"),
    ts(9, "Дробилка без руды, % (за час)", 16, 12, 8, 8,
       [named("dispatcher-01", "crusher_starved_dispatch", "с диспетчером"), named("dispatcher-01", "crusher_starved_baseline", "без диспетчера")], "percent"),
    ts(10, "Накопленный простой самосвалов, с", 0, 20, 12, 8, [("самосвалы", multi(f"{NS}:truck-", "idle_s"))], "s"),
    ts(11, "Топливо самосвалов, %", 12, 20, 12, 8, [("самосвалы", multi(f"{NS}:truck-", "fuel"))], "percent"),
]
dash = {"uid": "openegiz-digital-pit", "title": "Цифровой карьер: диспетчеризация", "tags": ["openegiz", "pit", "dispatch"],
        "timezone": "browser", "schemaVersion": 39, "version": 1, "refresh": "10s", "time": {"from": "now-30m", "to": "now"},
        "description": "KPI диспетчеризации самосвалов; 3D-стенд: http://localhost:8099", "panels": panels}
json.dump(dash, open(__file__.replace("make_dashboard.py", "dashboard.json"), "w"), ensure_ascii=False, indent=1)
print("dashboard.json:", len(panels), "panels")
