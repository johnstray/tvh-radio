import pytest

import master


def test_restart_loop_without_failures():
    """A channel with no failure history is not in a restart loop."""

    channel = {"failure_times": []}
    restart_config = {"limit": 3, "window": 60}

    assert master.is_restart_loop(channel, restart_config) is False


@pytest.mark.parametrize(
    "failure_times, expected_remaining, expected",
    [
        ([], [], False),
        ([990], [990], False),
        ([980, 990], [980, 990], False),
        ([970, 980, 990], [970, 980, 990], True),
        ([940, 970, 990], [940, 970, 990], True),
        ([939, 970, 990], [970, 990], False),
        ([900, 920, 990], [990], False),
    ],
)
def test_restart_loop_detection(
    monkeypatch, failure_times, expected_remaining, expected
):
    """Only failures inside the rolling window count towards backoff."""

    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    channel = {"failure_times": failure_times.copy()}
    restart_config = {"limit": 3, "window": 60}

    assert master.is_restart_loop(channel, restart_config) is expected
    assert channel["failure_times"] == expected_remaining


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
        "failure_times": [],
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

    channel_a["failure_times"].append(1000)
    channel_a["state"] = "backoff"

    assert channel_b["failure_times"] == []
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

    assert channel["failure_times"] == []
    assert channel["last_restart"] == 1000
    assert channel["process"].pid == 12345
    assert started_channels == [channel]


def test_restart_channel_preserves_failure_history(monkeypatch, tmp_path):
    """Repeated restarts preserve and increment the restart counter."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    channel["failure_times"] = [400, 500]
    channel["last_restart"] = 500

    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    class FakeProcess:
        pid = 12345

    def fake_start_channel(channel_state):
        channel_state["process"] = FakeProcess()

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    master.restart_channel(channel)

    assert channel["failure_times"] == [400, 500]
    assert channel["last_restart"] == 1000


def test_monitor_removes_channel_after_successful_exit(monkeypatch, tmp_path):
    """A channel exiting with code zero is removed without restarting."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        returncode = 0

        def poll(self):
            return self.returncode

    channel["process"] = FakeProcess()
    processes = {"test-channel": channel}

    monkeypatch.setattr(master, "shutdown_requested", False)

    def stop_after_first_iteration(seconds):
        master.shutdown_requested = True

    monkeypatch.setattr(master.time, "sleep", stop_after_first_iteration)

    master.monitor_channels(
        processes,
        {
            "limit": 3,
            "window": 60,
            "reset_time": 300,
            "backoff_time": 30,
        },
    )

    assert processes == {}


def test_monitor_restarts_failed_channel(monkeypatch, tmp_path):
    """A channel that exits with an error is automatically restarted."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        def __init__(self, pid, returncode=None):
            self.pid = pid
            self.returncode = returncode

        def poll(self):
            return self.returncode

    failed_process = FakeProcess(pid=1001, returncode=1)
    replacement_process = FakeProcess(pid=1002)

    channel["process"] = failed_process
    processes = {"test-channel": channel}

    monkeypatch.setattr(master, "shutdown_requested", False)
    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    started_channels = []

    def fake_start_channel(channel_state):
        started_channels.append(channel_state)
        channel_state["process"] = replacement_process

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    def stop_after_first_iteration(seconds):
        master.shutdown_requested = True

    monkeypatch.setattr(master.time, "sleep", stop_after_first_iteration)

    restart_config = {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 30,
    }

    master.monitor_channels(processes, restart_config)

    assert started_channels == [channel]
    assert channel["process"] is replacement_process
    assert channel["failure_times"] == [1000]
    assert channel["last_restart"] == 1000
    assert channel["state"] == "running"
    assert channel["next_restart"] is None
    assert processes["test-channel"] is channel


def test_monitor_enters_backoff_after_repeated_failures(monkeypatch, tmp_path):
    """Repeated failures trigger backoff instead of another immediate restart."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        returncode = 1

        def poll(self):
            return self.returncode

    channel["process"] = FakeProcess()

    # Simulate three recent restarts.
    channel["failure_times"] = [990, 995]
    channel["last_restart"] = 995

    processes = {"test-channel": channel}

    monkeypatch.setattr(master, "shutdown_requested", False)
    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    started_channels = []

    def fake_start_channel(channel_state):
        started_channels.append(channel_state)

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    def stop_after_first_iteration(seconds):
        master.shutdown_requested = True

    monkeypatch.setattr(master.time, "sleep", stop_after_first_iteration)

    restart_config = {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 30,
    }

    master.monitor_channels(processes, restart_config)

    assert started_channels == []
    assert channel["state"] == "backoff"
    assert channel["next_restart"] == 1030
    assert channel["failure_times"] == [990, 995, 1000]
    assert channel["last_restart"] == 995
    assert processes["test-channel"] is channel


def test_monitor_restarts_channel_after_backoff(monkeypatch, tmp_path):
    """A channel restarts once its backoff period has expired."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        def __init__(self, pid, returncode=None):
            self.pid = pid
            self.returncode = returncode

        def poll(self):
            return self.returncode

    failed_process = FakeProcess(pid=1001, returncode=1)
    replacement_process = FakeProcess(pid=1002)

    channel["process"] = failed_process
    channel["state"] = "backoff"
    channel["failure_times"] = [940, 945, 950]
    channel["last_restart"] = 950
    channel["next_restart"] = 1000

    processes = {"test-channel": channel}

    monkeypatch.setattr(master, "shutdown_requested", False)
    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    started_channels = []

    def fake_start_channel(channel_state):
        started_channels.append(channel_state)
        channel_state["process"] = replacement_process

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    def stop_after_first_iteration(seconds):
        master.shutdown_requested = True

    monkeypatch.setattr(master.time, "sleep", stop_after_first_iteration)

    restart_config = {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 30,
    }

    master.monitor_channels(processes, restart_config)

    assert started_channels == [channel]
    assert channel["process"] is replacement_process
    assert channel["state"] == "running"
    assert channel["failure_times"] == []
    assert channel["last_restart"] == 1000
    assert channel["next_restart"] is None
    assert processes["test-channel"] is channel


def test_monitor_waits_until_backoff_expires(monkeypatch, tmp_path):
    """A channel in backoff must not restart before its deadline."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        returncode = 1

        def poll(self):
            return self.returncode

    failed_process = FakeProcess()

    channel["process"] = failed_process
    channel["state"] = "backoff"
    channel["failure_times"] = [940, 945, 950]
    channel["last_restart"] = 950
    channel["next_restart"] = 1030

    processes = {"test-channel": channel}

    monkeypatch.setattr(master, "shutdown_requested", False)
    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    started_channels = []

    def fake_start_channel(channel_state):
        started_channels.append(channel_state)

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    def stop_after_first_iteration(seconds):
        master.shutdown_requested = True

    monkeypatch.setattr(master.time, "sleep", stop_after_first_iteration)

    restart_config = {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 30,
    }

    master.monitor_channels(processes, restart_config)

    assert started_channels == []
    assert channel["process"] is failed_process
    assert channel["state"] == "backoff"
    assert channel["failure_times"] == [940, 945, 950]
    assert channel["last_restart"] == 950
    assert channel["next_restart"] == 1030
    assert processes["test-channel"] is channel


@pytest.mark.parametrize("exit_code", [0, 1])
def test_monitor_removes_intentionally_stopped_channel(
    monkeypatch, tmp_path, exit_code
):
    """Intentionally stopped channels are removed without restarting."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        def __init__(self, returncode):
            self.returncode = returncode

        def poll(self):
            return self.returncode

    channel["process"] = FakeProcess(exit_code)
    channel["stopping"] = True

    processes = {"test-channel": channel}

    monkeypatch.setattr(master, "shutdown_requested", False)

    started_channels = []

    def fake_start_channel(channel_state):
        started_channels.append(channel_state)

    monkeypatch.setattr(
        master,
        "start_channel",
        fake_start_channel,
    )

    def stop_after_first_iteration(seconds):
        master.shutdown_requested = True

    monkeypatch.setattr(
        master.time,
        "sleep",
        stop_after_first_iteration,
    )

    restart_config = {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 30,
    }

    master.monitor_channels(processes, restart_config)

    assert started_channels == []
    assert processes == {}


@pytest.mark.parametrize(
    "elapsed, expected_failures",
    [
        (299, [690, 695]),
        (300, []),
        (301, []),
    ],
)
def test_monitor_resets_restart_history_after_healthy_period(
    monkeypatch, tmp_path, elapsed, expected_failures
):
    """A running process clears failure history after the reset interval."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        def poll(self):
            return None

    channel["process"] = FakeProcess()
    channel["failure_times"] = [690, 695]
    channel["last_restart"] = 1000 - elapsed

    processes = {"test-channel": channel}

    monkeypatch.setattr(master, "shutdown_requested", False)
    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    def stop_after_first_iteration(seconds):
        master.shutdown_requested = True

    monkeypatch.setattr(master.time, "sleep", stop_after_first_iteration)

    restart_config = {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 30,
    }

    master.monitor_channels(processes, restart_config)

    assert channel["failure_times"] == expected_failures
    assert channel["last_restart"] == 1000 - elapsed
    assert channel["state"] == "running"
    assert processes["test-channel"] is channel


def test_monitor_prunes_old_failures_when_process_exits(
    monkeypatch, tmp_path
):
    """An exited channel beyond the reset interval starts fresh restart history."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        def __init__(self, pid, returncode=None):
            self.pid = pid
            self.returncode = returncode

        def poll(self):
            return self.returncode

    channel["process"] = FakeProcess(pid=1001, returncode=1)
    channel["failure_times"] = [690, 695]
    channel["last_restart"] = 700

    processes = {"test-channel": channel}

    monkeypatch.setattr(master, "shutdown_requested", False)
    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    replacement_process = FakeProcess(pid=1002)
    started_channels = []

    def fake_start_channel(channel_state):
        started_channels.append(channel_state)
        channel_state["process"] = replacement_process

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    def stop_after_first_iteration(seconds):
        master.shutdown_requested = True

    monkeypatch.setattr(
        master.time,
        "sleep",
        stop_after_first_iteration,
    )

    restart_config = {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 30,
    }

    master.monitor_channels(processes, restart_config)

    assert started_channels == [channel]
    assert channel["process"] is replacement_process
    assert channel["failure_times"] == [1000]
    assert channel["last_restart"] == 1000
    assert channel["state"] == "running"
    assert processes["test-channel"] is channel


def test_monitor_ignores_failures_outside_rolling_window(
    monkeypatch, tmp_path
):
    """Old failures do not cause a new crash to trigger backoff."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        def __init__(self, pid, returncode=None):
            self.pid = pid
            self.returncode = returncode

        def poll(self):
            return self.returncode

    channel["process"] = FakeProcess(1001, returncode=1)
    channel["failure_times"] = [900, 950]
    channel["last_restart"] = 950

    processes = {"test-channel": channel}

    monkeypatch.setattr(master, "shutdown_requested", False)
    monkeypatch.setattr(master.time, "monotonic", lambda: 1000)

    replacement_process = FakeProcess(1002)

    def fake_start_channel(channel_state):
        channel_state["process"] = replacement_process

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    def stop_after_first_iteration(seconds):
        master.shutdown_requested = True

    monkeypatch.setattr(master.time, "sleep", stop_after_first_iteration)

    restart_config = {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 30,
    }

    master.monitor_channels(processes, restart_config)

    assert channel["failure_times"] == [950, 1000]
    assert channel["process"] is replacement_process
    assert channel["state"] == "running"
    assert channel["next_restart"] is None
