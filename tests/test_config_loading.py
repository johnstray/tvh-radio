import json
import pytest

from master import load_channel_configs


def test_load_single_channel_config(tmp_path, valid_channel_config):
    """A valid channel configuration should load successfully."""

    config_file = tmp_path / "test_radio.json"

    config_file.write_text(
        json.dumps(valid_channel_config),
        encoding="utf-8",
    )

    channels = load_channel_configs(tmp_path)

    assert len(channels) == 1

    loaded_file, loaded_config = channels[0]

    assert loaded_file == config_file
    assert loaded_config == valid_channel_config


def test_load_empty_channel_directory(tmp_path):
    """An empty channel directory should return no channels."""

    channels = load_channel_configs(tmp_path)

    assert channels == []


def test_load_multiple_channel_configs(tmp_path, valid_channel_config):
    """Multiple channel configurations should load in filename order."""

    for name in ["zebra", "alpha", "middle"]:
        config = valid_channel_config.copy()
        config["channel_name"] = name
        config["station_name"] = f"{name.title()} Radio"

        config_file = tmp_path / f"{name}.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

    channels = load_channel_configs(tmp_path)

    assert len(channels) == 3

    assert [path.name for path, _config in channels] == [
        "alpha.json",
        "middle.json",
        "zebra.json",
    ]

    assert [config["channel_name"] for _path, config in channels] == [
        "alpha",
        "middle",
        "zebra",
    ]


def test_load_malformed_channel_config(tmp_path):
    """Malformed JSON should report the offending configuration filename."""

    config_file = tmp_path / "broken.json"

    config_file.write_text(
        '{"channel_name": "broken",',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="broken.json"):
        load_channel_configs(tmp_path)


def test_load_channel_missing_required_setting(
    tmp_path, valid_channel_config
):
    """Invalid channel configurations should identify the offending file."""

    del valid_channel_config["icecast_url"]

    config_file = tmp_path / "missing_stream_url.json"
    config_file.write_text(
        json.dumps(valid_channel_config),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"missing_stream_url\.json.*icecast_url",
    ):
        load_channel_configs(tmp_path)


def test_load_mixed_valid_and_invalid_configs(
    tmp_path, valid_channel_config
):
    """Loading should fail when any channel configuration is invalid."""

    valid_file = tmp_path / "alpha.json"
    valid_file.write_text(
        json.dumps(valid_channel_config),
        encoding="utf-8",
    )

    invalid_config = valid_channel_config.copy()
    del invalid_config["station_name"]

    invalid_file = tmp_path / "beta.json"
    invalid_file.write_text(
        json.dumps(invalid_config),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"beta\.json.*station_name",
    ):
        load_channel_configs(tmp_path)


def test_load_channel_invalid_type_reports_filename(
    tmp_path, valid_channel_config
):
    """Configuration type errors should identify the offending file."""

    valid_channel_config["fallback_metadata"] = None

    config_file = tmp_path / "invalid_fallback.json"
    config_file.write_text(
        json.dumps(valid_channel_config),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"invalid_fallback\.json.*fallback_metadata",
    ):
        load_channel_configs(tmp_path)
