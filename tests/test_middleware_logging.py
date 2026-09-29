from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.main import app


def _post_chat(*, headers: dict[str, str] | None = None) -> httpx.Response:
    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/chat",
                headers=headers,
                json={
                    "user_id": "student@example.com",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "Contact 090 123 4567, CCCD 001203004567",
                },
            )

    return asyncio.run(send_request())


def test_generated_correlation_id_headers_and_enriched_scrubbed_log(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    response = _post_chat()

    assert response.status_code == 200
    assert re.fullmatch(r"req-[0-9a-f]{8}", response.headers["x-request-id"])
    assert float(response.headers["x-response-time-ms"]) >= 0

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    request_event = next(record for record in records if record["event"] == "request_received")
    assert request_event["correlation_id"] == response.headers["x-request-id"]
    assert request_event["user_id_hash"] != "student@example.com"
    assert request_event["session_id"] == "session-01"
    assert request_event["feature"] == "qa"
    assert request_event["model"]
    assert request_event["env"] == "dev"
    raw_log = log_path.read_text(encoding="utf-8")
    assert "090 123 4567" not in raw_log
    assert "001203004567" not in raw_log


def test_incoming_request_id_is_propagated(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    response = _post_chat(headers={"x-request-id": "req-upstream01"})

    assert response.headers["x-request-id"] == "req-upstream01"
    assert response.json()["correlation_id"] == "req-upstream01"
