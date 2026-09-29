from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.dashboard import render_dashboard


def test_dashboard_renders_six_runtime_panels(tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    records = [
        {"ts": now, "event": "request_received", "service": "api"},
        {
            "ts": now,
            "event": "response_sent",
            "service": "api",
            "latency_ms": 200,
            "ttft_ms": 50,
            "cost_usd": 0.001,
            "tokens_in": 20,
            "tokens_out": 80,
            "quality_score": 0.9,
            "tool_success": True,
        },
    ]
    log_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    html = render_dashboard(log_path=log_path)

    for panel_id in ("latency", "traffic", "errors", "cost", "tokens", "quality"):
        assert f'id="panel-{panel_id}"' in html
    assert "last 60 minutes" in html
    assert "Threshold / SLO" in html
    assert "Retrieval success" in html
    assert "100.0%" in html
