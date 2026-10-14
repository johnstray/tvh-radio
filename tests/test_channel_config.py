import pytest

from master import validate_channel_config


def test_valid_channel_configuration(valid_channel_config):
    """A valid channel configuration should be accepted."""

    validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "field",
    [
        "channel_name",
        "station_name",
        "station_logo",
        "fallback_station_logo",
        "track_meta_url",
        "icecast_url",
        "fallback_metadata",
        "stream",
    ],
)
def test_missing_required_channel_setting(valid_channel_config, field):
    """Missing required channel settings should be rejected."""

    del valid_channel_config[field]

    with pytest.raises((ValueError, TypeError)):
        validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "channel_number",
    [
        1,
        900,
        9999,
    ],
)
def test_valid_channel_numbers(valid_channel_config, channel_number):
    """Explicit positive channel numbers should be accepted."""

    valid_channel_config["channel_number"] = channel_number

    validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "invalid_value",
    [
        0,
        -1,
        "900",
        900.5,
        True,
        None,
    ],
)
def test_invalid_channel_numbers(valid_channel_config, invalid_value):
    """Explicit channel numbers must be positive integers."""

    valid_channel_config["channel_number"] = invalid_value

    with pytest.raises((ValueError, TypeError)):
        validate_channel_config(valid_channel_config)


def test_channel_number_is_optional(valid_channel_config):
    """The master may allocate a channel number automatically."""

    assert "channel_number" not in valid_channel_config

    validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "udp_port",
    [
        1,
        1234,
        5000,
        65535,
    ],
)
def test_valid_udp_ports(valid_channel_config, udp_port):
    """Explicit UDP ports within the valid range should be accepted."""

    valid_channel_config["udp_port"] = udp_port

    validate_channel_config(valid_channel_config)


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
def test_invalid_udp_ports(valid_channel_config, invalid_value):
    """Explicit UDP ports must be integers between 1 and 65535."""

    valid_channel_config["udp_port"] = invalid_value

    with pytest.raises((ValueError, TypeError), match="udp_port"):
        validate_channel_config(valid_channel_config)


def test_udp_port_is_optional(valid_channel_config):
    """The master may allocate a UDP port automatically."""

    assert "udp_port" not in valid_channel_config

    validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "field",
    [
        "update_interval",
        "metadata_empty_threshold",
        "image_definition",
        "request_timeout",
        "station_logo_retry_interval",
        "video_fps",
        "video_bitrate",
        "audio_bitrate",
    ],
)
def test_valid_stream_settings(valid_channel_config, field):
    """Positive integer stream settings should be accepted."""

    valid_channel_config["stream"][field] = 1

    validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "field",
    [
        "update_interval",
        "metadata_empty_threshold",
        "image_definition",
        "request_timeout",
        "station_logo_retry_interval",
        "video_fps",
        "video_bitrate",
        "audio_bitrate",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        0,
        -1,
        "10",
        10.5,
        True,
        None,
    ],
)
def test_invalid_stream_settings(valid_channel_config, field, invalid_value):
    """Stream settings must be positive integers."""

    valid_channel_config["stream"][field] = invalid_value

    with pytest.raises((ValueError, TypeError), match=field):
        validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "field",
    [
        "update_interval",
        "metadata_empty_threshold",
        "image_definition",
        "request_timeout",
        "station_logo_retry_interval",
        "video_fps",
        "video_bitrate",
        "audio_bitrate",
    ],
)
def test_missing_stream_settings(valid_channel_config, field):
    """All required stream settings must be present."""

    del valid_channel_config["stream"][field]

    with pytest.raises((ValueError, TypeError), match=field):
        validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "artist",
        "album",
        "image_path",
    ],
)
def test_missing_fallback_metadata_settings(valid_channel_config, field):
    """All fallback metadata fields must be present."""

    del valid_channel_config["fallback_metadata"][field]

    with pytest.raises((ValueError, TypeError), match=field):
        validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "field",
    [
        "stream",
        "fallback_metadata",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        None,
        "",
        123,
        True,
        [],
    ],
)
def test_invalid_nested_config_types(
    valid_channel_config, field, invalid_value
):
    """Nested configuration sections must be dictionaries."""

    valid_channel_config[field] = invalid_value

    with pytest.raises((ValueError, TypeError)):
        validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "tags",
    [
        [],
        ["Music"],
        ["Music", "Radio", "Pop"],
    ],
)
def test_valid_tvh_tags(valid_channel_config, tags):
    """TVHeadend tags must be a list of strings."""

    valid_channel_config["tvh_tags"] = tags

    validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "invalid_tags",
    [
        None,
        "Music",
        123,
        True,
        {},
        [123],
        ["Music", None],
        ["Radio", True],
    ],
)
def test_invalid_tvh_tags(valid_channel_config, invalid_tags):
    """Reject non-list tags and lists containing non-string values."""

    valid_channel_config["tvh_tags"] = invalid_tags

    with pytest.raises(ValueError, match="tvh_tags"):
        validate_channel_config(valid_channel_config)


def test_tvh_tags_is_optional(valid_channel_config):
    """Channels do not require TVHeadend tags."""

    assert "tvh_tags" not in valid_channel_config

    validate_channel_config(valid_channel_config)


def test_empty_fallback_metadata(valid_channel_config):
    """Fallback metadata must contain its required fields."""

    valid_channel_config["fallback_metadata"] = {}

    with pytest.raises(ValueError, match="title"):
        validate_channel_config(valid_channel_config)


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "artist",
        "album",
        "image_path",
    ],
)
def test_empty_fallback_metadata_values(valid_channel_config, field):
    """Empty fallback metadata values are currently accepted."""

    valid_channel_config["fallback_metadata"][field] = ""

    validate_channel_config(valid_channel_config)
