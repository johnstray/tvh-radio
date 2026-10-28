import pytest

import master


def test_restart_loop_without_previous_restart():
    """A channel with no restart history is not in a restart loop."""

    channel = {
        "restart_count": 0,
        "last_restart": None,
    }

    restart_config = {
        "limit": 3,
        "window": 60,
    }

    assert master.is_restart_loop(channel, restart_config) is False


@pytest.mark.parametrize(
    "restart_count, elapsed, expected",
    [
        (1, 10, False),
        (2, 10, False),
        (3, 10, True),
        (4, 10, True),
        (3, 60, True),
        (3, 61, False),
        (4, 120, False),
    ],
)
def test_restart_loop_detection(
    monkeypatch, restart_count, elapsed, expected
):
    """Restart-loop detection respects the restart limit and time window."""

    current_time = 1000

    monkeypatch.setattr(
        master.time,
        "monotonic",
        lambda: current_time,
    )

    channel = {
        "restart_count": restart_count,
        "last_restart": current_time - elapsed,
    }

    restart_config = {
        "limit": 3,
        "window": 60,
    }

    assert master.is_restart_loop(channel, restart_config) is expected


@pytest.mark.parametrize(
    "current_time, expected",
    [
        (999, False),
        (1000, True),
        (1001, True),
    ],
)
def test_backoff_expiration(monkeypatch, current_time, expected):
    """Backoff expires when the restart deadline is reached."""

    monkeypatch.setattr(
        master.time,
        "monotonic",
        lambda: current_time,
    )

    channel = {
        "state": "backoff",
        "next_restart": 1000,
    }

    assert master.is_backoff_expired(channel) is expected


@pytest.mark.parametrize(
    "state",
    [
        "running",
        "stopped",
    ],
)
def test_backoff_expiration_requires_backoff_state(monkeypatch, state):
    """Channels outside backoff must not report an expired backoff."""

    monkeypatch.setattr(
        master.time,
        "monotonic",
        lambda: 2000,
    )

    channel = {
        "state": state,
        "next_restart": 1000,
    }

    assert master.is_backoff_expired(channel) is False


def test_backoff_expiration_without_deadline():
    """Backoff cannot expire without a scheduled restart time."""

    channel = {
        "state": "backoff",
        "next_restart": None,
    }

    assert master.is_backoff_expired(channel) is False


def test_create_channel_state(tmp_path):
    """New channels begin with a clean runtime state."""

    config_file = tmp_path / "test-channel.json"
    config = {
        "channel_name": "test-channel",
    }

    channel = master.create_channel_state(config_file, config)

    assert channel == {
        "channel_name": "test-channel",
        "config": config,
        "config_file": config_file,
        "process": None,
        "stopping": False,
        "restart_count": 0,
        "last_restart": None,
        "state": "running",
        "next_restart": None,
    }


def test_create_channel_states_are_independent(tmp_path):
    """Changes to one channel's state must not affect another."""

    channel_a = master.create_channel_state(
        tmp_path / "channel-a.json",
        {"channel_name": "channel-a"},
    )

    channel_b = master.create_channel_state(
        tmp_path / "channel-b.json",
        {"channel_name": "channel-b"},
    )

    channel_a["restart_count"] = 5
    channel_a["state"] = "backoff"

    assert channel_b["restart_count"] == 0
    assert channel_b["state"] == "running"


def test_restart_channel_updates_state(monkeypatch, tmp_path):
    """Restarting a channel updates its history and starts a new process."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    started_channels = []

    class FakeProcess:
        pid = 12345

    def fake_start_channel(channel_state):
        started_channels.append(channel_state)
        channel_state["process"] = FakeProcess()

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    master.restart_channel(channel)

    assert channel["restart_count"] == 1
    assert channel["last_restart"] == 1000
    assert channel["process"].pid == 12345
    assert started_channels == [channel]


def test_restart_channel_increments_existing_count(monkeypatch, tmp_path):
    """Repeated restarts preserve and increment the restart counter."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    channel["restart_count"] = 2
    channel["last_restart"] = 500

    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    class FakeProcess:
        pid = 12345

    def fake_start_channel(channel_state):
        channel_state["process"] = FakeProcess()

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    master.restart_channel(channel)

    assert channel["restart_count"] == 3
    assert channel["last_restart"] == 1000
