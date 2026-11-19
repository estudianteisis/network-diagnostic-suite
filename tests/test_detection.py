from netdiag.detection import QualityDetector
from netdiag.models import Event


def sample(duration: float | None, ok: bool = True) -> Event:
    return Event("icmp", "1.1.1.1", ok, duration)


def test_detects_sustained_latency_burst_and_recovery():
    detector = QualityDetector(min_baseline=3, absolute_latency_ms=100, consecutive_samples=2)
    for value in (20, 21, 19):
        assert detector.observe("public:1.1.1.1", sample(value)) == []
    assert detector.observe("public:1.1.1.1", sample(180)) == []
    incident = detector.observe("public:1.1.1.1", sample(190))
    assert incident[0].detail["signal"] == "latency_burst"
    recovery = detector.observe("public:1.1.1.1", sample(22))
    assert recovery[0].detail["state"] == "recovered"


def test_one_spike_is_not_a_burst():
    detector = QualityDetector(min_baseline=1, consecutive_samples=2)
    detector.observe("gateway", sample(3))
    assert detector.observe("gateway", sample(400)) == []
    assert detector.observe("gateway", sample(4)) == []


def test_ignores_non_latency_probes():
    detector = QualityDetector()
    assert detector.observe("tls", sample(None, ok=False)) == []


def test_custom_targets_have_same_detection():
    detector = QualityDetector(min_baseline=1, absolute_latency_ms=100, consecutive_samples=2)
    detector.observe("custom:League LAN", sample(20))
    detector.observe("custom:League LAN", sample(200))
    incident = detector.observe("custom:League LAN", sample(220))
    assert incident[0].target == "custom:League LAN"
