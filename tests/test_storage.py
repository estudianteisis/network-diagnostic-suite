from netdiag.models import Event
from netdiag.storage import EventStore, read_events


def test_event_store_round_trip(tmp_path):
    store = EventStore(tmp_path)
    store.append(Event("marker", "reconnecting", True, detail={"note": "two seconds"}))
    events = read_events(tmp_path)
    assert events[0]["target"] == "reconnecting"
    assert events[0]["timestamp_utc"].endswith("Z")
