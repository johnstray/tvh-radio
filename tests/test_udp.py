import json

import pytest

import master


@pytest.fixture
def sample_channels():
    """Return two channels without assigned UDP ports."""

    return [
        (
            "channel1.json",
            {
                "channel_name": "channel1",
                "udp_host": "127.0.0.1",
            },
        ),
        (
            "channel2.json",
            {
                "channel_name": "channel2",
                "udp_host": "127.0.0.1",
            },
        ),
    ]


def test_duplicate_udp_ports(sample_channels, monkeypatch):
    """Two channels cannot use the same UDP port."""

    sample_channels[0][1]["udp_port"] = 5000
    sample_channels[1][1]["udp_port"] = 5000

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5100,
    }

    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: True,
    )

    with pytest.raises(ValueError, match="Duplicate UDP port 5000"):
        master.validate_udp_ports(sample_channels, udp_config)


def test_distinct_udp_ports(sample_channels, monkeypatch):
    """Different explicit UDP ports should be accepted."""

    sample_channels[0][1]["udp_port"] = 5000
    sample_channels[1][1]["udp_port"] = 5001

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5100,
    }

    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: True,
    )

    master.validate_udp_ports(sample_channels, udp_config)


def test_occupied_explicit_udp_port(sample_channels, monkeypatch):
    """Reject an explicit UDP port already occupied by another process."""

    sample_channels[0][1]["udp_port"] = 5000

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5100,
    }

    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: port != 5000,
    )

    with pytest.raises(ValueError, match="already in use"):
        master.validate_udp_ports(sample_channels, udp_config)


def test_skip_occupied_udp_port(sample_channels, monkeypatch):
    """Validation should find another port when one is occupied."""

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5002,
    }

    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: port != 5000,
    )

    master.validate_udp_ports(sample_channels, udp_config)

    assert "udp_port" not in sample_channels[0][1]
    assert "udp_port" not in sample_channels[1][1]


def test_udp_port_range_exhausted(sample_channels, monkeypatch):
    """Reject configurations with insufficient UDP ports."""

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5000,
    }

    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: True,
    )

    with pytest.raises(ValueError, match="No available UDP port"):
        master.validate_udp_ports(sample_channels, udp_config)

    assert "udp_port" not in sample_channels[0][1]
    assert "udp_port" not in sample_channels[1][1]


def test_all_udp_ports_occupied(sample_channels, monkeypatch):
    """Reject automatic allocation when all candidate ports are occupied."""

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5002,
    }

    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: False,
    )

    with pytest.raises(ValueError, match="No available UDP port"):
        master.validate_udp_ports(sample_channels, udp_config)

    assert "udp_port" not in sample_channels[0][1]
    assert "udp_port" not in sample_channels[1][1]


def test_assign_udp_ports(sample_channels, monkeypatch, tmp_path):
    """Automatically assigned UDP ports should be unique and persisted."""

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5002,
    }

    # Create temporary channel configuration files.
    channels = []

    for filename, config in sample_channels:
        config_file = tmp_path / filename
        config_file.write_text(json.dumps(config), encoding="utf-8")
        channels.append((config_file, config))

    # Simulate all ports being available.
    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: True,
    )

    master.assign_udp_ports(channels, udp_config)

    # Check the assignments in memory.
    assert channels[0][1]["udp_port"] == 5000
    assert channels[1][1]["udp_port"] == 5001

    # Check that the assignments were saved to disk.
    for config_file, config in channels:
        saved_config = json.loads(config_file.read_text(encoding="utf-8"))

        assert saved_config["udp_port"] == config["udp_port"]


def test_assign_udp_ports_skips_explicit_ports(
    sample_channels, monkeypatch, tmp_path
):
    """Automatic allocation must preserve explicitly assigned ports."""

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5002,
    }

    # Reserve port 5000 for the first channel.
    sample_channels[0][1]["udp_port"] = 5000

    # Create temporary channel configuration files.
    channels = []

    for filename, config in sample_channels:
        config_file = tmp_path / filename
        config_file.write_text(json.dumps(config), encoding="utf-8")
        channels.append((config_file, config))

    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: True,
    )

    master.assign_udp_ports(channels, udp_config)

    # Explicit assignment remains unchanged.
    assert channels[0][1]["udp_port"] == 5000

    # Automatic allocation skips the reserved port.
    assert channels[1][1]["udp_port"] == 5001

    # Verify both configurations on disk.
    for config_file, config in channels:
        saved_config = json.loads(config_file.read_text(encoding="utf-8"))

        assert saved_config["udp_port"] == config["udp_port"]


def test_assign_udp_ports_skips_occupied_ports(
    sample_channels, monkeypatch, tmp_path
):
    """Automatic allocation must skip ports already in use."""

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5002,
    }

    # Create temporary channel configuration files.
    channels = []

    for filename, config in sample_channels:
        config_file = tmp_path / filename
        config_file.write_text(json.dumps(config), encoding="utf-8")
        channels.append((config_file, config))

    # Simulate port 5000 being occupied.
    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: port != 5000,
    )

    master.assign_udp_ports(channels, udp_config)

    # Allocation should skip port 5000.
    assert channels[0][1]["udp_port"] == 5001
    assert channels[1][1]["udp_port"] == 5002

    # Verify the assignments were persisted.
    for config_file, config in channels:
        saved_config = json.loads(config_file.read_text(encoding="utf-8"))

        assert saved_config["udp_port"] == config["udp_port"]


def test_assign_udp_ports_exhausted(sample_channels, monkeypatch, tmp_path):
    """Failed allocation must not persist partial assignments."""

    udp_config = {
        "host": "127.0.0.1",
        "port_start": 5000,
        "port_end": 5000,
    }

    channels = []

    for filename, config in sample_channels:
        config_file = tmp_path / filename
        config_file.write_text(json.dumps(config), encoding="utf-8")
        channels.append((config_file, config))

    monkeypatch.setattr(
        master,
        "is_udp_port_available",
        lambda host, port: True,
    )

    with pytest.raises(ValueError, match="No available UDP ports"):
        master.assign_udp_ports(channels, udp_config)

    # No channel configuration should have been saved.
    for config_file, _config in channels:
        saved_config = json.loads(config_file.read_text(encoding="utf-8"))

        assert "udp_port" not in saved_config


def test_assign_udp_hosts(sample_channels, tmp_path):
    """Default UDP hosts should be assigned and persisted."""

    udp_config = {
        "host": "192.168.1.100",
        "port_start": 5000,
        "port_end": 5100,
    }

    channels = []

    for filename, config in sample_channels:
        config.pop("udp_host", None)

        config_file = tmp_path / filename
        config_file.write_text(json.dumps(config), encoding="utf-8")
        channels.append((config_file, config))

    master.assign_udp_hosts(channels, udp_config)

    for config_file, config in channels:
        assert config["udp_host"] == "192.168.1.100"

        saved_config = json.loads(config_file.read_text(encoding="utf-8"))

        assert saved_config["udp_host"] == "192.168.1.100"


def test_assign_udp_hosts_preserves_explicit_host(sample_channels, tmp_path):
    """Explicit channel UDP hosts must not be overwritten."""

    udp_config = {
        "host": "192.168.1.100",
        "port_start": 5000,
        "port_end": 5100,
    }

    sample_channels[0][1]["udp_host"] = "192.168.1.200"
    sample_channels[1][1].pop("udp_host", None)

    channels = []

    for filename, config in sample_channels:
        config_file = tmp_path / filename
        config_file.write_text(json.dumps(config), encoding="utf-8")
        channels.append((config_file, config))

    master.assign_udp_hosts(channels, udp_config)

    assert channels[0][1]["udp_host"] == "192.168.1.200"
    assert channels[1][1]["udp_host"] == "192.168.1.100"

    for config_file, config in channels:
        saved_config = json.loads(config_file.read_text(encoding="utf-8"))

        assert saved_config["udp_host"] == config["udp_host"]


def test_assign_udp_hosts_builtin_default(sample_channels, tmp_path):
    """Use localhost when the master configuration omits udp.host."""

    udp_config = {
        "port_start": 5000,
        "port_end": 5100,
    }

    channels = []

    for filename, config in sample_channels:
        config.pop("udp_host", None)

        config_file = tmp_path / filename
        config_file.write_text(json.dumps(config), encoding="utf-8")
        channels.append((config_file, config))

    master.assign_udp_hosts(channels, udp_config)

    for config_file, config in channels:
        assert config["udp_host"] == "127.0.0.1"

        saved_config = json.loads(config_file.read_text(encoding="utf-8"))

        assert saved_config["udp_host"] == "127.0.0.1"
