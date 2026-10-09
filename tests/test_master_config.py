import pytest

from master import validate_master_config


@pytest.fixture
def valid_master_config():
    """Return a valid master configuration for testing."""

    return {
        "playlist": {
            "output": "playlist.m3u8",
            "starting_channel_number": 900,
        },
        "restart": {
            "limit": 3,
            "window": 60,
            "reset_time": 300,
            "backoff_time": 30,
        },
        "udp": {
            "host": "127.0.0.1",
            "port_start": 5000,
            "port_end": 5100,
        },
    }


def test_valid_master_configuration(valid_master_config):
    """A valid master configuration passes validation."""

    validate_master_config(valid_master_config)


@pytest.mark.parametrize(
    "section",
    [
        "playlist",
        "restart",
        "udp",
    ],
)
def test_missing_required_section(valid_master_config, section):
    """Master validation rejects missing required sections."""

    del valid_master_config[section]

    with pytest.raises(ValueError):
        validate_master_config(valid_master_config)


@pytest.mark.parametrize(
    "field",
    [
        "limit",
        "window",
        "reset_time",
        "backoff_time",
    ],
)
@pytest.mark.parametrize(
    "invalid_value, expected_exception",
    [
        (0, ValueError),
        (-1, ValueError),
        ("10", ValueError),
        (1.5, ValueError),
        (True, ValueError),
        (None, ValueError),
    ],
)
def test_invalid_restart_values(
    valid_master_config, field, invalid_value, expected_exception
):
    """Restart settings must be positive integers."""

    valid_master_config["restart"][field] = invalid_value

    with pytest.raises(expected_exception):
        validate_master_config(valid_master_config)


@pytest.mark.parametrize(
    "invalid_value, expected_exception",
    [
        ("", ValueError),
        (None, TypeError),
        (123, TypeError),
        (True, TypeError),
        ([], TypeError),
        ({}, TypeError),
    ],
)
def test_invalid_playlist_output(
    valid_master_config, invalid_value, expected_exception
):
    """Playlist output must be a non-empty string."""

    valid_master_config["playlist"]["output"] = invalid_value

    with pytest.raises(expected_exception):
        validate_master_config(valid_master_config)


@pytest.mark.parametrize(
    "invalid_value, expected_exception",
    [
        (0, ValueError),
        (-1, ValueError),
        ("900", TypeError),
        (900.5, TypeError),
        (True, TypeError),
        (None, TypeError),
    ],
)
def test_invalid_starting_channel_number(
    valid_master_config, invalid_value, expected_exception
):
    """Starting channel number must be a positive integer."""

    valid_master_config["playlist"]["starting_channel_number"] = invalid_value

    with pytest.raises(expected_exception):
        validate_master_config(valid_master_config)


@pytest.mark.parametrize(
    "port_start, port_end",
    [
        (1, 1),
        (65535, 65535),
        (1, 65535),
        (5000, 5100),
    ],
)
def test_valid_udp_port_ranges(
    valid_master_config, port_start, port_end
):
    """UDP port ranges within valid boundaries are accepted."""

    valid_master_config["udp"]["port_start"] = port_start
    valid_master_config["udp"]["port_end"] = port_end

    validate_master_config(valid_master_config)


@pytest.mark.parametrize(
    "field",
    [
        "port_start",
        "port_end",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        0,
        -1,
        65536,
        "5000",
        5000.5,
        True,
        None,
    ],
)
def test_invalid_udp_port_values(
    valid_master_config, field, invalid_value
):
    """UDP ports must be integers between 1 and 65535."""

    valid_master_config["udp"][field] = invalid_value

    with pytest.raises(
        (ValueError, TypeError),
        match=rf"\b{field}\b",
    ):
        validate_master_config(valid_master_config)


def test_reversed_udp_port_range(valid_master_config):
    """UDP port_start must not exceed port_end."""

    valid_master_config["udp"]["port_start"] = 6000
    valid_master_config["udp"]["port_end"] = 5000

    with pytest.raises(ValueError):
        validate_master_config(valid_master_config)


def test_udp_host_is_optional(valid_master_config):
    """UDP host may be omitted from the master configuration."""

    del valid_master_config["udp"]["host"]

    validate_master_config(valid_master_config)


@pytest.mark.parametrize(
    "invalid_value",
    [
        "",
        "   ",
        None,
        123,
        True,
        [],
        {},
    ],
)
def test_invalid_udp_host(valid_master_config, invalid_value):
    """UDP host must be a non-empty string when provided."""

    valid_master_config["udp"]["host"] = invalid_value

    with pytest.raises((ValueError, TypeError)):
        validate_master_config(valid_master_config)


@pytest.mark.parametrize(
    "section, field",
    [
        ("playlist", "output"),
        ("playlist", "starting_channel_number"),
        ("restart", "limit"),
        ("restart", "window"),
        ("restart", "reset_time"),
        ("restart", "backoff_time"),
        ("udp", "port_start"),
        ("udp", "port_end"),
    ],
)
def test_missing_required_setting(valid_master_config, section, field):
    """Required master configuration settings cannot be omitted."""

    del valid_master_config[section][field]

    with pytest.raises((ValueError, TypeError)):
        validate_master_config(valid_master_config)