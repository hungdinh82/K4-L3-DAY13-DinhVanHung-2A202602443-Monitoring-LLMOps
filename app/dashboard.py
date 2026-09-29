from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from .metrics import percentile


def _load_records(log_path: Path, window_minutes: int) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            timestamp = datetime.fromisoformat(str(record["ts"]).replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if timestamp >= cutoff:
            record["_timestamp"] = timestamp
            records.append(record)
    return records


def _minute_counts(records: list[dict[str, Any]], event: str) -> list[int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for record in records:
        if record.get("event") == event:
            counts[record["_timestamp"].strftime("%H:%M")] += 1
    return [counts[key] for key in sorted(counts)]


def _sparkline(values: list[float], *, threshold: float | None = None) -> str:
    width, height, padding = 420, 104, 8
    values = values or [0.0]
    ceiling = max(values + ([threshold] if threshold is not None else [0.0]) + [1.0])

    def y(value: float) -> float:
        return height - padding - (value / ceiling) * (height - 2 * padding)

    step = (width - 2 * padding) / max(1, len(values) - 1)
    points = " ".join(f"{padding + index * step:.1f},{y(value):.1f}" for index, value in enumerate(values))
    threshold_line = ""
    if threshold is not None:
        line_y = y(threshold)
        threshold_line = (
            f'<line x1="{padding}" y1="{line_y:.1f}" x2="{width-padding}" '
            f'y2="{line_y:.1f}" class="threshold-line" />'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="metric trend">'
        f'{threshold_line}<polyline points="{points}" class="sparkline" /></svg>'
    )


def _metric(label: str, value: str) -> str:
    return f'<div class="metric"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'


def render_dashboard(
    *,
    log_path: Path = Path("data/logs.jsonl"),
    config_path: Path = Path("config/dashboard.yaml"),
) -> str:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))["dashboard"]
    window_minutes = int(config["time_range_minutes"])
    records = _load_records(log_path, window_minutes)
    responses = [record for record in records if record.get("event") == "response_sent"]
    received = [record for record in records if record.get("event") == "request_received"]
    failures = [record for record in records if record.get("event") == "request_failed"]

    latencies = [float(record["latency_ms"]) for record in responses if record.get("latency_ms") is not None]
    ttfts = [float(record["ttft_ms"]) for record in responses if record.get("ttft_ms") is not None]
    costs = [float(record["cost_usd"]) for record in responses if record.get("cost_usd") is not None]
    tokens_in = [int(record["tokens_in"]) for record in responses if record.get("tokens_in") is not None]
    tokens_out = [int(record["tokens_out"]) for record in responses if record.get("tokens_out") is not None]
    qualities = [float(record["quality_score"]) for record in responses if record.get("quality_score") is not None]
    retrieval_events = [record for record in records if record.get("tool_success") is not None]
    retrieval_success = (
        100 * sum(record.get("tool_success") is True for record in retrieval_events) / len(retrieval_events)
        if retrieval_events
        else 0.0
    )
    error_rate = 100 * len(failures) / len(received) if received else 0.0
    error_breakdown = Counter(record.get("error_type", "unknown") for record in failures)

    panels_by_id = {panel["id"]: panel for panel in config["panels"]}

    def panel(panel_id: str, metrics: str, values: list[float], threshold: float | None = None) -> str:
        spec = panels_by_id[panel_id]
        threshold_spec = spec["threshold"]
        threshold_text = (
            f'{threshold_spec["aggregation"]} {threshold_spec["operator"]} '
            f'{threshold_spec["value"]} {spec["unit"]}'
        )
        return (
            f'<section class="panel" id="panel-{escape(panel_id)}">'
            f'<header><div><p class="eyebrow">{escape(panel_id)}</p>'
            f'<h2>{escape(spec["title"])}</h2></div>'
            f'<span class="unit">{escape(str(spec["unit"]))}</span></header>'
            f'<div class="metrics">{metrics}</div>{_sparkline(values, threshold=threshold)}'
            f'<footer><span>Threshold / SLO</span><strong>{escape(threshold_text)}</strong></footer>'
            f'</section>'
        )

    latency_metrics = "".join(
        [
            _metric("P50", f"{percentile([int(value) for value in latencies], 50):.0f} ms"),
            _metric("P95", f"{percentile([int(value) for value in latencies], 95):.0f} ms"),
            _metric("P99", f"{percentile([int(value) for value in latencies], 99):.0f} ms"),
            _metric("TTFT P95", f"{percentile([int(value) for value in ttfts], 95):.0f} ms"),
        ]
    )
    traffic_series = [float(value) for value in _minute_counts(records, "request_received")]
    traffic_metrics = _metric("Requests", str(len(received))) + _metric(
        "Peak / minute", str(max(traffic_series, default=0))
    )
    error_metrics = "".join(
        [
            _metric("Error rate", f"{error_rate:.1f}%"),
            _metric("Retrieval success", f"{retrieval_success:.1f}%"),
            _metric("Breakdown", ", ".join(f"{key}:{value}" for key, value in error_breakdown.items()) or "none"),
        ]
    )
    cost_metrics = _metric("Total", f"${sum(costs):.4f}") + _metric(
        "Average / request", f"${mean(costs):.4f}" if costs else "$0.0000"
    )
    token_metrics = _metric("Input", str(sum(tokens_in))) + _metric("Output", str(sum(tokens_out)))
    quality_metrics = _metric("Average", f"{mean(qualities):.2f}" if qualities else "0.00") + _metric(
        "Samples", str(len(qualities))
    )

    panels = "".join(
        [
            panel("latency", latency_metrics, latencies, float(panels_by_id["latency"]["threshold"]["value"])),
            panel("traffic", traffic_metrics, traffic_series, float(panels_by_id["traffic"]["threshold"]["value"])),
            panel("errors", error_metrics, [error_rate], float(panels_by_id["errors"]["threshold"]["value"])),
            panel("cost", cost_metrics, costs, float(panels_by_id["cost"]["threshold"]["value"])),
            panel("tokens", token_metrics, [float(a + b) for a, b in zip(tokens_in, tokens_out)], float(panels_by_id["tokens"]["threshold"]["value"])),
            panel("quality", quality_metrics, qualities, float(panels_by_id["quality"]["threshold"]["value"])),
        ]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta http-equiv="refresh" content="{int(config['refresh_seconds'])}">
<title>{escape(config['title'])}</title>
<style>
:root {{ color-scheme: dark; --bg:#0a0d12; --panel:#121822; --line:#263244; --text:#f3f7fb; --muted:#91a0b5; --accent:#68e0c5; --warn:#ffb454; }}
* {{ box-sizing:border-box }} body {{ margin:0; font:14px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace; background:radial-gradient(circle at top,#162133 0,var(--bg) 42%); color:var(--text) }}
main {{ max-width:1320px; margin:auto; padding:34px }} .topbar {{ display:flex; justify-content:space-between; gap:24px; align-items:end; margin-bottom:24px }}
h1 {{ font:700 30px/1.1 system-ui,sans-serif; margin:5px 0 }} .subtitle,.eyebrow {{ color:var(--muted); margin:0; text-transform:uppercase; letter-spacing:.1em; font-size:11px }}
.status {{ padding:10px 14px; border:1px solid var(--line); border-radius:999px; color:var(--accent) }} .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px }}
.panel {{ background:linear-gradient(145deg,rgba(22,30,43,.98),rgba(14,19,28,.98)); border:1px solid var(--line); border-radius:16px; padding:20px; min-height:300px; box-shadow:0 16px 35px rgba(0,0,0,.22) }}
.panel header,.panel footer {{ display:flex; justify-content:space-between; gap:18px; align-items:start }} h2 {{ font:650 18px/1.2 system-ui,sans-serif; margin:4px 0 0 }} .unit {{ color:var(--muted); border:1px solid var(--line); padding:5px 8px; border-radius:7px }}
.metrics {{ display:flex; flex-wrap:wrap; gap:20px; margin:24px 0 12px }} .metric {{ min-width:110px }} .metric span {{ display:block; color:var(--muted); font-size:11px }} .metric strong {{ display:block; margin-top:4px; font-size:18px }}
svg {{ width:100%; height:104px; overflow:visible }} .sparkline {{ fill:none; stroke:var(--accent); stroke-width:3; stroke-linecap:round; stroke-linejoin:round }} .threshold-line {{ stroke:var(--warn); stroke-width:1.5; stroke-dasharray:6 5 }}
.panel footer {{ border-top:1px solid var(--line); padding-top:13px; color:var(--muted) }} .panel footer strong {{ color:var(--warn); font-size:12px; text-align:right }}
@media(max-width:850px) {{ .grid {{ grid-template-columns:1fr }} .topbar {{ align-items:start; flex-direction:column }} main {{ padding:20px }} }}
</style></head><body><main><div class="topbar"><div><p class="eyebrow">Monitoring / LLMOps</p><h1>{escape(config['title'])}</h1>
<p class="subtitle">Source: data/logs.jsonl · last {window_minutes} minutes · refresh {config['refresh_seconds']}s</p></div>
<div class="status">{len(records)} records · {len(responses)} completed</div></div><div class="grid">{panels}</div></main></body></html>"""
