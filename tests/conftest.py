import socket

import pytest


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """A test must never accidentally spend API tokens or send real data."""

    def fail(*args, **kwargs):
        raise AssertionError("Network access is forbidden in unit tests")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket.socket, "connect_ex", fail)
