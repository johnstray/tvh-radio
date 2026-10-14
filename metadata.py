"""Helpers for processing radio track metadata."""


def get_track_identity(data):
    """Return a unique identifier for the track based on its metadata."""
    return (
        f"{data.get('title', '')}-"
        f"{data.get('artist', '')}-"
        f"{data.get('album', '')}-"
        f"{data.get('imagePath', '')}"
    )
