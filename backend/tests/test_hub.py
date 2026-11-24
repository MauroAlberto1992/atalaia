from minicop import hub as hub_module
from minicop.hub import Hub


def test_publish_reaches_all_clients():
    hub = Hub()
    a, b = hub.subscribe(), hub.subscribe()
    hub.publish("x")
    assert a.get_nowait() == "x" and b.get_nowait() == "x"


def test_slow_client_is_dropped(monkeypatch):
    monkeypatch.setattr(hub_module, "CLIENT_QUEUE_SIZE", 2)
    hub = Hub()
    slow = hub.subscribe()
    for i in range(3):  # third publish overflows
        hub.publish(i)
    assert len(hub) == 0
    assert slow.get_nowait() is None  # close sentinel
