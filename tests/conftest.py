import pytest


@pytest.fixture
def valid_channel_config():
    """Return a valid channel configuration for testing."""

    return {
        "channel_name": "test_radio",
        "station_name": "Test Radio",
        "station_logo": "https://example.com/logo.png",
        "fallback_station_logo": "https://example.com/fallback.png",
        "track_meta_url": "https://example.com/metadata",
        "icecast_url": "https://example.com/stream",
        "fallback_metadata": {
            "title": "Unknown Title",
            "artist": "Unknown Artist",
            "album": "Unknown Album",
            "image_path": "",
        },
        "stream": {
            "update_interval": 10,
            "metadata_empty_threshold": 3,
            "image_definition": 720,
            "request_timeout": 10,
            "station_logo_retry_interval": 300,
            "video_fps": 25,
            "video_bitrate": 1500,
            "audio_bitrate": 128,
        },
    }
