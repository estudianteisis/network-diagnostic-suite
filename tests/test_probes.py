from netdiag.probes import parse_ping_output


def test_parse_english_ping():
    assert parse_ping_output("Reply from 1.1.1.1: bytes=32 time=14ms TTL=57", 20) == (True, 14.0)


def test_parse_spanish_ping():
    assert parse_ping_output("Respuesta desde 1.1.1.1: bytes=32 tiempo=22ms TTL=57", 30) == (
        True,
        22.0,
    )


def test_parse_sub_millisecond_ping_uses_elapsed():
    ok, latency = parse_ping_output("Reply: time<1ms TTL=128", 0.7)
    assert ok is True
    assert latency == 0.7


def test_parse_timeout():
    assert parse_ping_output("Request timed out.", 1500) == (False, None)
