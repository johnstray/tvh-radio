import pytest
import requests

from metadata import (
    MetadataFallbackState,
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


def test_fallback_state_empty_threshold():
    """Consecutive empty responses should activate fallback at the threshold."""

    state = MetadataFallbackState(empty_threshold=3)

    fallback_data = {
        "title": "Unknown Title",
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "imagePath": "",
    }

    assert state.process("empty", None, fallback_data) is None
    assert state.empty_count == 1
    assert state.fallback_active is False

    assert state.process("empty", None, fallback_data) is None
    assert state.empty_count == 2
    assert state.fallback_active is False

    assert state.process("empty", None, fallback_data) == fallback_data
    assert state.empty_count == 3
    assert state.fallback_active is True

    # Further empty responses should not trigger another fallback.
    assert state.process("empty", None, fallback_data) is None


def test_fallback_state_api_error():
    """API errors should activate fallback immediately."""

    state = MetadataFallbackState(empty_threshold=3)

    fallback_data = {
        "title": "Unknown Title",
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "imagePath": "",
    }

    result = state.process(
        "error",
        requests.ConnectionError("Connection refused"),
        fallback_data,
    )

    assert result == fallback_data
    assert state.empty_count == 0
    assert state.fallback_active is True
    assert state.error_active is True


def test_fallback_state_api_recovery():
    """Successful metadata should restore normal operation after an error."""

    state = MetadataFallbackState(empty_threshold=3)

    fallback_data = {
        "title": "Unknown Title",
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "imagePath": "",
    }

    track_data = {
        "title": "Test Song",
        "artist": "Test Artist",
        "album": "Test Album",
        "imagePath": "https://example.com/artwork.jpg",
    }

    # Simulate an API failure.
    state.process(
        "error",
        requests.ConnectionError("Connection refused"),
        fallback_data,
    )

    assert state.fallback_active is True
    assert state.error_active is True

    # Simulate the API recovering.
    result = state.process("success", track_data, fallback_data)

    assert result == track_data
    assert state.empty_count == 0
    assert state.fallback_active is False
    assert state.error_active is False


def test_fallback_state_success_resets_empty_count():
    """Successful metadata should reset consecutive empty responses."""

    state = MetadataFallbackState(empty_threshold=3)

    fallback_data = {"title": "Unknown Title"}
    track_data = {"title": "Test Song"}

    state.process("empty", None, fallback_data)
    state.process("empty", None, fallback_data)

    assert state.empty_count == 2

    result = state.process("success", track_data, fallback_data)

    assert result == track_data
    assert state.empty_count == 0
    assert state.fallback_active is False

    # A new HTTP 204 sequence starts from zero.
    result = state.process("empty", None, fallback_data)

    assert result is None
    assert state.empty_count == 1
    assert state.fallback_active is False


def test_fallback_state_repeated_errors():
    """Repeated API errors should keep fallback active."""

    state = MetadataFallbackState(empty_threshold=3)

    fallback_data = {"title": "Unknown Title"}

    for _ in range(3):
        result = state.process(
            "error",
            requests.ConnectionError("Connection refused"),
            fallback_data,
        )

        assert result == fallback_data
        assert state.empty_count == 0
        assert state.fallback_active is True
        assert state.error_active is True


def test_fallback_state_recovery_with_same_metadata():
    """Successful metadata clears fallback even if its content is unchanged."""

    state = MetadataFallbackState(empty_threshold=3)

    fallback_data = {
        "title": "Unknown Title",
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "imagePath": "",
    }

    state.process("error", requests.ConnectionError(), fallback_data)

    assert state.fallback_active is True

    # The API recovers but returns metadata identical to the fallback.
    result = state.process("success", fallback_data, fallback_data)

    assert result == fallback_data
    assert state.fallback_active is False
    assert state.error_active is False

    # A new sequence of empty responses must start from zero.
    assert state.process("empty", None, fallback_data) is None
    assert state.empty_count == 1


def test_fallback_state_error_followed_by_empty():
    """Empty responses should not reactivate an already active fallback."""

    state = MetadataFallbackState(empty_threshold=3)

    fallback_data = {"title": "Unknown Title"}

    state.process("error", requests.ConnectionError(), fallback_data)

    assert state.fallback_active is True

    for _ in range(4):
        result = state.process("empty", None, fallback_data)

        assert result is None
        assert state.fallback_active is True
        assert state.empty_count == 0
