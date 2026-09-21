# iHeart Extractor

Small Python utility for extracting iHeartRadio station information used by the
`tvh-radio` project.

## Requirements

- Python 3.9+
- `requests`
- `beautifulsoup4`

Install dependencies with:

```bash
python3 -m pip install requests beautifulsoup4
```

## Usage

Basic output:

```bash
python3 iheart_extract.py "https://www.iheart.com/live/woolworths-radio-9195/"
```

JSON output:

```bash
python3 iheart_extract.py --json \
    "https://www.iheart.com/live/woolworths-radio-9195/"
```

Complete `tvh-radio` channel template:

```bash
python3 iheart_extract.py --channel-json \
    "https://www.iheart.com/live/woolworths-radio-9195/"
```

The `--channel-json` output is intended to be redirected into a new channel
configuration file and then manually completed with project-specific values
such as the UDP host/port, channel number and TVHeadend tags.

## Current extraction model

The tool requests the iHeart live page with `embed=true`, locates the
`<script id="initial-props">` element, and parses its JSON.

The current mappings are:

- `station_name` <- `initialProps.name`
- `station_logo` <- `initialProps.logo`
- `icecast_url` <- `initialProps.streams.shoutcast_stream`
- `track_meta_url` <- `initialProps.ampUrl` + station `liveId`

The metadata URL currently follows:

```text
{ampUrl}/api/v3/live-meta/stream/{liveId}/currentTrackMeta
```

This is based on the stations examined so far and should be treated as an
assumption until tested against a broader range of iHeart stations.

## Notes

The generated channel template intentionally leaves these values as defaults
for manual completion:

- `fallback_station_logo`: `../images/station_logo.png`
- `udp_host`: empty string
- `udp_port`: `1234`
- `channel_number`: `0`
- `tvh_tags`: empty array
- `fallback_metadata.image_path`: `../images/album_cover.png`

The fallback metadata uses the iHeart station name as its title and the iHeart
provider as its artist value.
