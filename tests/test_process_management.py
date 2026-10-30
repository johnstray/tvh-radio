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


def test_shutdown_channels_terminates_all_processes(tmp_path):
    """Shutdown marks every channel as stopping and requests termination."""

    class FakeProcess:
        def __init__(self):
            self.terminate_calls = 0

        def terminate(self):
            self.terminate_calls += 1

    processes = {}

    for name in ("channel-a", "channel-b"):
        channel = master.create_channel_state(
            tmp_path / f"{name}.json",
            {"channel_name": name},
        )
        channel["process"] = FakeProcess()
        processes[name] = channel

    master.shutdown_channels(processes)

    for channel in processes.values():
        assert channel["stopping"] is True
        assert channel["process"].terminate_calls == 1


def test_wait_for_channels_waits_for_all_processes(tmp_path):
    """The master waits for each channel process to finish."""

    wait_order = []

    class FakeProcess:
        def __init__(self, name):
            self.name = name

        def wait(self):
            wait_order.append(self.name)
            return 0

    processes = {}

    for name in ("channel-a", "channel-b"):
        channel = master.create_channel_state(
            tmp_path / f"{name}.json",
            {"channel_name": name},
        )
        channel["process"] = FakeProcess(name)
        processes[name] = channel

    master.wait_for_channels(processes)

    assert wait_order == ["channel-a", "channel-b"]


def test_start_channel_creates_subprocess(monkeypatch, tmp_path):
    """A channel starts a streamer with the expected subprocess settings."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    popen_calls = []

    class FakeProcess:
        pid = 12345

    fake_process = FakeProcess()

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return fake_process

    monkeypatch.setattr(master.subprocess, "Popen", fake_popen)

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            pass

    monkeypatch.setattr(master.threading, "Thread", FakeThread)

    master.start_channel(channel)

    assert channel["process"] is fake_process
    assert len(popen_calls) == 1

    args, kwargs = popen_calls[0]

    assert args == (
        [
            master.sys.executable,
            "streamer.py",
            str(channel["config_file"]),
        ],
    )

    assert kwargs == {
        "stdout": master.subprocess.PIPE,
        "stderr": master.subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "start_new_session": True,
    }


def test_start_channel_creates_output_thread(monkeypatch, tmp_path):
    """Starting a streamer creates a daemon thread to forward its output."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    class FakeProcess:
        pid = 12345

    monkeypatch.setattr(
        master.subprocess,
        "Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    created_threads = []

    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False
            created_threads.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(master.threading, "Thread", FakeThread)

    master.start_channel(channel)

    assert len(created_threads) == 1

    output_thread = created_threads[0]

    assert output_thread.kwargs["target"] is master.read_channel_output
    assert output_thread.kwargs["args"] == (channel,)
    assert output_thread.kwargs["daemon"] is True
    assert output_thread.started is True


def test_read_channel_output(capsys):
    """Streamer output is forwarded to the master's standard output."""

    from io import StringIO

    class FakeProcess:
        stdout = StringIO(
            "Streamer started\n"
            "Metadata updated\n"
            "Streamer stopped\n"
        )

    channel = {
        "process": FakeProcess(),
    }

    master.read_channel_output(channel)

    captured = capsys.readouterr()

    assert captured.out == (
        "Streamer started\n"
        "Metadata updated\n"
        "Streamer stopped\n"
    )
    assert captured.err == ""


def test_start_channels_starts_all_configured_channels(monkeypatch, tmp_path):
    """Every configured channel is started and registered with the master."""

    channels = [
        (
            tmp_path / "channel-a.json",
            {"channel_name": "channel-a"},
        ),
        (
            tmp_path / "channel-b.json",
            {"channel_name": "channel-b"},
        ),
    ]

    started_channels = []

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

    def fake_start_channel(channel):
        started_channels.append(channel["channel_name"])
        channel["process"] = FakeProcess(1000 + len(started_channels))

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    processes = master.start_channels(channels)

    assert started_channels == ["channel-a", "channel-b"]
    assert set(processes) == {"channel-a", "channel-b"}

    assert processes["channel-a"]["process"].pid == 1001
    assert processes["channel-b"]["process"].pid == 1002

    for config_file, config in channels:
        channel = processes[config["channel_name"]]

        assert channel["config_file"] == config_file
        assert channel["config"] is config
        assert channel["stopping"] is False
        assert channel["state"] == "running"
        assert channel["failure_times"] == []


def test_start_channel_propagates_launch_failure(monkeypatch, tmp_path):
    """A failed subprocess launch reports the error to its caller."""

    channel = master.create_channel_state(
        tmp_path / "test-channel.json",
        {"channel_name": "test-channel"},
    )

    def fake_popen(*args, **kwargs):
        raise OSError("Unable to launch streamer")

    monkeypatch.setattr(master.subprocess, "Popen", fake_popen)

    with pytest.raises(OSError, match="Unable to launch streamer"):
        master.start_channel(channel)

    assert channel["process"] is None


def test_start_channels_stops_after_launch_failure(monkeypatch, tmp_path):
    """A launch failure prevents subsequent channels from starting."""

    channels = [
        (
            tmp_path / f"channel-{name}.json",
            {"channel_name": f"channel-{name}"},
        )
        for name in ("a", "b", "c")
    ]

    attempted = []

    class FakeProcess:
        pid = 12345

    def fake_start_channel(channel):
        attempted.append(channel["channel_name"])

        if channel["channel_name"] == "channel-b":
            raise OSError("Unable to launch channel-b")

        channel["process"] = FakeProcess()

    monkeypatch.setattr(master, "start_channel", fake_start_channel)

    with pytest.raises(OSError, match="Unable to launch channel-b"):
        master.start_channels(channels)

    assert attempted == ["channel-a", "channel-b"]
