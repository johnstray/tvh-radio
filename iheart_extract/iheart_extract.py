"""
Extract iHeartRadio station information for tvh-radio.

Usage:
    python iheart_extract.py URL
    python iheart_extract.py --json URL
    python iheart_extract.py --channel-json URL
"""

import argparse
import json
import re
import sys
import traceback
from html import unescape
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

__version__ = "0.1.0"

DEFAULT_FALLBACK_LOGO = "../images/station_logo.png"
DEFAULT_UDP_PORT = 1234
DEFAULT_CHANNEL_NUMBER = 0
DEFAULT_ALBUM = "iHeartRadio"
DEFAULT_FALLBACK_ALBUM_IMAGE = "../images/album_cover.png"
REQUEST_TIMEOUT = 15


class ExtractionError(Exception):
    """Raised when required station information cannot be extracted."""


def build_embed_url(url: str) -> str:
    """Return the supplied iHeart live URL with embed=true."""
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ExtractionError("The supplied URL does not appear to be valid.")

    query = parsed.query
    if query:
        if re.search(r"(^|&)embed=", query):
            query = re.sub(r"(^|&)embed=[^&]*", r"\1embed=true", query)
        else:
            query += "&embed=true"
    else:
        query = "embed=true"

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        query,
        parsed.fragment,
    ))


def fetch_initial_props(url: str) -> dict:
    """Fetch the embed page and parse the initial-props JSON."""
    embed_url = build_embed_url(url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        response = requests.get(
            embed_url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.Timeout:
        raise ExtractionError(
            "Unable to retrieve iHeart page: connection timed out."
        )

    except requests.ConnectionError:
        raise ExtractionError(
            "Unable to retrieve iHeart page: could not connect to the server."
        )

    except requests.HTTPError as exc:
        raise ExtractionError(
            f"Unable to retrieve iHeart page: HTTP {exc.response.status_code}."
        )

    except requests.RequestException:
        raise ExtractionError(
            "Unable to retrieve iHeart page: request failed."
        )

    soup = BeautifulSoup(response.text, "html.parser")
    script = soup.find("script", id="initial-props")

    if script is None:
        raise ExtractionError(
            "Could not find the <script id=\"initial-props\"> element."
        )

    raw_json = script.string or script.get_text()
    raw_json = unescape(raw_json).strip()

    if not raw_json:
        raise ExtractionError("The initial-props script is empty.")

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ExtractionError(
            f"Could not parse initial-props JSON: {exc}"
        ) from exc

    if not isinstance(data, dict) or not isinstance(
        data.get("initialProps"), dict
    ):
        raise ExtractionError(
            "The initial-props JSON does not contain an initialProps object."
        )

    return data["initialProps"]


def require_value(data: dict, path: str):
    """Retrieve a required nested value using dot notation."""
    value = data

    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ExtractionError(
                f"Required station information '{path}' was not found."
            )
        value = value[key]

    if value is None or value == "":
        raise ExtractionError(
            f"Required station information '{path}' is empty."
        )

    return value


def extract_station_data(initial_props: dict) -> dict:
    """Map iHeart initialProps into tvh-radio-relevant data."""
    station_name = require_value(initial_props, "name")
    station_id = require_value(initial_props, "liveId")
    logo = require_value(initial_props, "logo")
    stream_url = require_value(initial_props, "streams.shoutcast_stream")
    amp_url = require_value(initial_props, "ampUrl")

    metadata_url = (
        f"{str(amp_url).rstrip('/')}"
        f"/api/v3/live-meta/stream/{station_id}/currentTrackMeta"
    )

    provider = initial_props.get("provider") or station_name

    return {
        "station_name": station_name,
        "station_id": station_id,
        "station_logo": logo,
        "track_meta_url": metadata_url,
        "icecast_url": stream_url,
        "provider": provider,
    }


def make_channel_name(station_name: str) -> str:
    """Convert a station name into a simple channel identifier."""
    # Keep this deliberately conservative: normalise punctuation/whitespace
    # without trying to guess which words should be removed.
    value = station_name.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def make_channel_config(data: dict) -> dict:
    """Build a complete tvh-radio channel configuration template."""
    station_name = data["station_name"]

    return {
        "channel_name": make_channel_name(station_name),
        "station_name": station_name,
        "station_logo": data["station_logo"],
        "fallback_station_logo": DEFAULT_FALLBACK_LOGO,
        "track_meta_url": data["track_meta_url"],
        "icecast_url": data["icecast_url"],
        "udp_host": "",
        "udp_port": DEFAULT_UDP_PORT,
        "channel_number": DEFAULT_CHANNEL_NUMBER,
        "tvh_tags": [],
        "fallback_metadata": {
            "title": station_name,
            "artist": data["provider"],
            "album": DEFAULT_ALBUM,
            "image_path": DEFAULT_FALLBACK_ALBUM_IMAGE,
        },
    }


def print_basic(data: dict) -> None:
    """Print the default human-readable output."""
    print(f"station_name  : {data['station_name']}")
    print(f"station_logo  : {data['station_logo']}")
    print(f"track_meta_url: {data['track_meta_url']}")
    print(f"icecast_url   : {data['icecast_url']}")


def run(args) -> None:
    if args.json_output and args.channel_json:
        raise ExtractionError(
            "--json and --channel-json cannot be used together."
        )

    initial_props = fetch_initial_props(args.url)
    data = extract_station_data(initial_props)

    if args.channel_json:
        print(json.dumps(make_channel_config(data), indent=4))
    elif args.json_output:
        output = {
            "station_name": data["station_name"],
            "station_logo": data["station_logo"],
            "track_meta_url": data["track_meta_url"],
            "icecast_url": data["icecast_url"],
        }
        print(json.dumps(output, indent=4))
    else:
        print_basic(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract iHeartRadio station information for tvh-radio."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output the extracted data as JSON.",
    )
    parser.add_argument(
        "--channel-json",
        action="store_true",
        help="Output a complete tvh-radio channel configuration template.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show a Python traceback when an error occurs.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "url",
        help="iHeartRadio live station URL.",
    )

    args = parser.parse_args()

    try:
        run(args)

    except ExtractionError as exc:
        if args.debug:
            traceback.print_exc()
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    except Exception as exc:  # noqa: BLE001
        if args.debug:
            traceback.print_exc()
        else:
            print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
