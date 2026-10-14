import pytest
import requests

from metadata import (
    build_fallback_metadata,
    fallback_threshold_reached,
    get_track_identity,
    get_track_metadata,
)


def test_track_identity():
    """Track identity should include all four metadata fields."""

    data = {
        "title": "Test Song",
        "artist": "Test Artist",
        "album": "Test Album",
        "imagePath": "https://example.com/artwork.jpg",
    }

    identity = get_track_identity(data)

    assert identity == (
        "Test Song-Test Artist-Test Album-"
        "https://example.com/artwork.jpg"
    )


@pytest.mark.parametrize(
    "data, expected",
    [
        ({}, "---"),
        (
            {"title": "Test Song"},
            "Test Song---",
        ),
    ],
)
def test_track_identity_missing_fields(data, expected):
    """Missing metadata fields should default to empty strings."""

    assert get_track_identity(data) == expected


def test_get_track_metadata_success(monkeypatch):
    """A successful API response should return parsed metadata."""

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "title": "Test Song",
                "artist": "Test Artist",
            }

    def fake_get(url, timeout):
        assert url == "https://example.com/metadata"
        assert timeout == 10
        return FakeResponse()

    monkeypatch.setattr("metadata.requests.get", fake_get)

    data, result = get_track_metadata(
        "https://example.com/metadata",
        10,
    )

    assert result == "success"
    assert data == {
        "title": "Test Song",
        "artist": "Test Artist",
    }


def test_get_track_metadata_empty_response(monkeypatch):
    """HTTP 204 should be treated as empty metadata, not an error."""

    class FakeResponse:
        status_code = 204

        def raise_for_status(self):
            raise AssertionError("raise_for_status should not be called")

        def json(self):
            raise AssertionError("json should not be called")

    def fake_get(url, timeout):
        return FakeResponse()

    monkeypatch.setattr("metadata.requests.get", fake_get)

    data, result = get_track_metadata(
        "https://example.com/metadata",
        10,
    )

    assert data is None
    assert result == "empty"


def test_get_track_metadata_http_error(monkeypatch):
    """HTTP errors should return an error result."""

    class FakeResponse:
        status_code = 500

        def raise_for_status(self):
            raise requests.HTTPError("500 Server Error")

        def json(self):
            raise AssertionError("JSON should not be parsed after an HTTP error")

    monkeypatch.setattr(
        "metadata.requests.get",
        lambda url, timeout: FakeResponse(),
    )

    data, result = get_track_metadata(
        "https://example.com/metadata",
        10,
    )

    assert result == "error"
    assert isinstance(data, requests.HTTPError)


@pytest.mark.parametrize(
    "exception",
    [
        requests.ConnectionError("Connection refused"),
        requests.Timeout("Request timed out"),
    ],
)
def test_get_track_metadata_request_error(monkeypatch, exception):
    """Network failures should return an error result."""

    def fake_get(url, timeout):
        raise exception

    monkeypatch.setattr("metadata.requests.get", fake_get)

    data, result = get_track_metadata(
        "https://example.com/metadata",
        10,
    )

    assert result == "error"
    assert data is exception


def test_get_track_metadata_invalid_json(monkeypatch):
    """Invalid JSON should return an error rather than raise an exception."""

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("Invalid JSON response")

    monkeypatch.setattr(
        "metadata.requests.get",
        lambda url, timeout: FakeResponse(),
    )

    data, result = get_track_metadata(
        "https://example.com/metadata",
        10,
    )

    assert result == "error"
    assert isinstance(data, ValueError)
    assert str(data) == "Invalid JSON response"


def test_build_fallback_metadata():
    """Fallback configuration should map to the expected track format."""

    fallback_config = {
        "title": "Unknown Title",
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "image_path": "/images/fallback.png",
    }

    result = build_fallback_metadata(fallback_config)

    assert result == {
        "title": "Unknown Title",
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "imagePath": "/images/fallback.png",
    }


@pytest.mark.parametrize(
    "empty_count, expected",
    [
        (0, False),
        (1, False),
        (2, False),
        (3, True),
        (4, True),
    ],
)
def test_fallback_threshold(empty_count, expected):
    """Fallback activates when the empty-response threshold is reached."""

    assert fallback_threshold_reached(empty_count, 3) is expected
