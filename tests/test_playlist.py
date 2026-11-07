import pytest

from master import (
    generate_playlist,
    remove_playlist,
    validate_channel_numbers,
    write_playlist,
)


def test_duplicate_channel_numbers():
    """Two channels cannot explicitly use the same channel number."""

    channels = [
        ("channel1.json", {
            "channel_name": "channel1",
            "channel_number": 900,
        }),
        ("channel2.json", {
            "channel_name": "channel2",
            "channel_number": 900,
        }),
    ]

    with pytest.raises(ValueError, match="Duplicate channel number 900"):
        validate_channel_numbers(channels)


def test_unique_channel_numbers():
    """Distinct explicitly configured channel numbers are accepted."""

    channels = [
        ("channel1.json", {
            "channel_name": "channel1",
            "channel_number": 900,
        }),
        ("channel2.json", {
            "channel_name": "channel2",
            "channel_number": 901,
        }),
    ]

    validate_channel_numbers(channels)


def test_missing_channel_numbers_are_allowed():
    """Channels without explicit numbers can be numbered automatically."""

    channels = [
        ("channel1.json", {
            "channel_name": "channel1",
            "channel_number": 900,
        }),
        ("channel2.json", {
            "channel_name": "channel2",
        }),
        ("channel3.json", {
            "channel_name": "channel3",
        }),
    ]

    validate_channel_numbers(channels)


def test_generate_playlist_single_channel():
    """Generate a valid M3U8 playlist containing one channel."""

    channels = [
        (
            "channel1.json",
            {
                "channel_name": "channel1",
                "station_name": "Test Radio",
                "station_logo": "https://example.com/logo.png",
                "channel_number": 900,
                "udp_host": "127.0.0.1",
                "udp_port": 5000,
            },
        ),
    ]

    master_config = {
        "playlist": {
            "starting_channel_number": 900,
        },
    }

    playlist = generate_playlist(channels, master_config)

    expected = (
        "#EXTM3U\n"
        '#EXTINF:-1 tvg-name="Test Radio" '
        'tvg-id="channel1" '
        'tvg-logo="https://example.com/logo.png" '
        'tvg-chnum="900",Test Radio\n'
        "udp://127.0.0.1:5000\n"
    )

    assert playlist == expected


def test_generate_playlist_automatic_channel_numbers():
    """Channels without explicit numbers receive consecutive numbers."""

    channels = [
        (
            f"channel{i}.json",
            {
                "channel_name": f"channel{i}",
                "station_name": f"Test Radio {i}",
                "station_logo": "https://example.com/logo.png",
                "udp_host": "127.0.0.1",
                "udp_port": 5000 + i,
            },
        )
        for i in range(1, 4)
    ]

    master_config = {
        "playlist": {
            "starting_channel_number": 900,
        },
    }

    playlist = generate_playlist(channels, master_config)

    assert 'tvg-chnum="900"' in playlist
    assert 'tvg-chnum="901"' in playlist
    assert 'tvg-chnum="902"' in playlist


def test_generate_playlist_skips_explicit_channel_numbers():
    """Automatic numbering must skip explicitly reserved channel numbers."""

    channels = [
        (
            "automatic1.json",
            {
                "channel_name": "automatic1",
                "station_name": "Automatic Radio 1",
                "station_logo": "https://example.com/logo.png",
                "udp_host": "127.0.0.1",
                "udp_port": 5000,
            },
        ),
        (
            "explicit.json",
            {
                "channel_name": "explicit",
                "station_name": "Explicit Radio",
                "station_logo": "https://example.com/logo.png",
                "channel_number": 901,
                "udp_host": "127.0.0.1",
                "udp_port": 5001,
            },
        ),
        (
            "automatic2.json",
            {
                "channel_name": "automatic2",
                "station_name": "Automatic Radio 2",
                "station_logo": "https://example.com/logo.png",
                "udp_host": "127.0.0.1",
                "udp_port": 5002,
            },
        ),
    ]

    master_config = {
        "playlist": {
            "starting_channel_number": 900,
        },
    }

    playlist = generate_playlist(channels, master_config)

    assert 'tvg-chnum="900"' in playlist
    assert 'tvg-chnum="901"' in playlist
    assert 'tvg-chnum="902"' in playlist

    # Confirm the correct number belongs to each channel.
    lines = playlist.splitlines()

    assert 'tvg-id="automatic1"' in lines[1]
    assert 'tvg-chnum="900"' in lines[1]

    assert 'tvg-id="explicit"' in lines[3]
    assert 'tvg-chnum="901"' in lines[3]

    assert 'tvg-id="automatic2"' in lines[5]
    assert 'tvg-chnum="902"' in lines[5]


def test_generate_playlist_with_tvh_tags():
    """Multiple TVHeadend tags should be included in the playlist."""

    channels = [
        (
            "channel1.json",
            {
                "channel_name": "channel1",
                "station_name": "Test Radio",
                "station_logo": "https://example.com/logo.png",
                "channel_number": 900,
                "udp_host": "127.0.0.1",
                "udp_port": 5000,
                "tvh_tags": ["Radio", "Music", "Pop"],
            },
        ),
    ]

    master_config = {
        "playlist": {
            "starting_channel_number": 900,
        },
    }

    playlist = generate_playlist(channels, master_config)

    assert 'tvh-tags="Radio|Music|Pop"' in playlist


@pytest.mark.parametrize(
    "tags",
    [
        None,
        [],
    ],
)
def test_generate_playlist_without_tvh_tags(tags):
    """Channels without tags should omit the tvh-tags attribute."""

    channel = {
        "channel_name": "channel1",
        "station_name": "Test Radio",
        "station_logo": "https://example.com/logo.png",
        "channel_number": 900,
        "udp_host": "127.0.0.1",
        "udp_port": 5000,
    }

    if tags is not None:
        channel["tvh_tags"] = tags

    channels = [("channel1.json", channel)]

    master_config = {
        "playlist": {
            "starting_channel_number": 900,
        },
    }

    playlist = generate_playlist(channels, master_config)

    assert "tvh-tags=" not in playlist


def test_write_playlist(tmp_path):
    """Generated playlists should be written to the configured file."""

    output_file = tmp_path / "playlist.m3u8"

    master_config = {
        "playlist": {
            "output": str(output_file),
        },
    }

    playlist = (
        "#EXTM3U\n"
        '#EXTINF:-1 tvg-name="Test Radio",Test Radio\n'
        "udp://127.0.0.1:5000\n"
    )

    write_playlist(playlist, master_config)

    assert output_file.is_file()
    assert output_file.read_text(encoding="utf-8") == playlist


def test_remove_playlist(tmp_path):
    """The generated playlist should be removed during cleanup."""

    output_file = tmp_path / "playlist.m3u8"
    output_file.write_text("#EXTM3U\n", encoding="utf-8")

    master_config = {
        "playlist": {
            "output": str(output_file),
        },
    }

    remove_playlist(master_config)

    assert not output_file.exists()


def test_remove_missing_playlist(tmp_path):
    """Removing a nonexistent playlist should not raise an error."""

    output_file = tmp_path / "missing.m3u8"

    master_config = {
        "playlist": {
            "output": str(output_file),
        },
    }

    assert not output_file.exists()

    remove_playlist(master_config)

    assert not output_file.exists()
