from datetime import UTC, datetime, timedelta

from netdiag.analysis import classify_window, compare_summaries, metric, summarize


def event(kind, target, ok, when, probe, duration=20):
    return {
        "kind": kind,
        "target": target,
        "ok": ok,
        "timestamp_utc": when.isoformat().replace("+00:00", "Z"),
        "duration_ms": duration,
        "detail": {"probe": probe},
    }


def test_metric_failure_and_jitter():
    values = [
        {"ok": True, "duration_ms": 10},
        {"ok": True, "duration_ms": 20},
        {"ok": False, "duration_ms": 1000},
    ]
    result = metric(values)
    assert result["failure_rate"] == 0.3333
    assert result["latency_ms"]["jitter_mean_abs"] == 10


def test_gateway_failure_classifies_local():
    now = datetime.now(UTC)
    events = [event("icmp", "192.168.1.1", False, now, "gateway") for _ in range(3)]
    result = classify_window(events)
    assert result["classification"] == "local_network_or_router"


def test_two_public_failures_classify_upstream():
    now = datetime.now(UTC)
    events = [
        event("icmp", "1.1.1.1", False, now, "public:1.1.1.1"),
        event("icmp", "8.8.8.8", False, now, "public:8.8.8.8"),
        event("icmp", "192.168.1.1", True, now, "gateway"),
    ]
    assert classify_window(events)["classification"] == "common_upstream_or_access"


def test_healthy_window_does_not_blame_game():
    now = datetime.now(UTC)
    events = [event("icmp", "1.1.1.1", True, now, "public:1.1.1.1")]
    assert classify_window(events)["classification"] == "no_measured_network_fault"


def test_summary_assesses_marker_window():
    now = datetime.now(UTC)
    events = [event("icmp", "192.168.1.1", False, now, "gateway")]
    events.append(
        {
            "kind": "marker",
            "target": "reconnecting",
            "ok": True,
            "timestamp_utc": (now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            "duration_ms": None,
            "detail": {"note": "visible"},
        }
    )
    result = summarize(events)
    assert result["markers"][0]["assessment"]["classification"] == "local_network_or_router"


def test_summary_includes_automatic_incidents():
    now = datetime.now(UTC)
    events = [event("icmp", "1.1.1.1", True, now, "public:1.1.1.1")]
    events.append(
        {
            "kind": "quality_incident",
            "target": "public:1.1.1.1",
            "ok": False,
            "timestamp_utc": now.isoformat().replace("+00:00", "Z"),
            "duration_ms": 250,
            "detail": {"state": "started", "signal": "latency_burst", "baseline_ms": 25},
        }
    )
    result = summarize(events)
    assert result["overview"]["automatic_incidents"] == 1
    assert "degradaciones" in result["overview"]["health"]


def test_compare_matches_close_markers(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"markers":[{"timestamp_utc":"2026-01-01T00:00:00Z"}]}')
    right.write_text('{"markers":[{"timestamp_utc":"2026-01-01T00:00:03Z"}]}')
    result = compare_summaries([left, right], 5)
    assert result["coincident_markers"][0]["delta_seconds"] == 3
