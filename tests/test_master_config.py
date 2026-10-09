import pytest

from master import validate_master_config


def test_missing_playlist_configuration():
    """Master validation rejects a missing playlist section."""

    with pytest.raises(ValueError, match="Missing required configuration section: playlist"):
        validate_master_config({})