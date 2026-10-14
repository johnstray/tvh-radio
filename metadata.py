"""Helpers for processing radio track metadata."""

import requests


def get_track_identity(data):
    """Return a unique identifier for the track based on its metadata."""
    return (
        f"{data.get('title', '')}-"
        f"{data.get('artist', '')}-"
        f"{data.get('album', '')}-"
        f"{data.get('imagePath', '')}"
    )


def get_track_metadata(url, timeout):
    """Retrieve the current track metadata from the station API."""
    try:
        response = requests.get(url, timeout=timeout)

        if response.status_code == 204:
            return None, "empty"

        response.raise_for_status()

        return response.json(), "success"

    except requests.RequestException as error:
        return error, "error"

    except ValueError as error:
        return error, "error"


def build_fallback_metadata(fallback_config):
    """Convert configured fallback metadata into track metadata format."""
    return {
        "title": fallback_config["title"],
        "artist": fallback_config["artist"],
        "album": fallback_config["album"],
        "imagePath": fallback_config["image_path"],
    }


def fallback_threshold_reached(empty_count, threshold):
    """Return True when consecutive empty responses reach the threshold."""
    return empty_count >= threshold
