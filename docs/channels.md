# Channel configuration

Each JSON file in the `channels/` directory represents one radio channel.

A complete example configuration is available at:

    examples/channels/example.json

## Core fields

| Field | Required | Description |
| --- | --- | --- |
| `channel_name` | Yes | Unique identifier used for the channel and playlist `tvg-id`. |
| `station_name` | Yes | Human-readable station name. |
| `station_logo` | Yes | URL or path for the primary station logo. |
| `fallback_station_logo` | Yes | Logo used when the primary station logo cannot be retrieved. |
| `track_meta_url` | Yes | Metadata endpoint used to retrieve current track information. |
| `icecast_url` | Yes | Audio stream URL. |
| `udp_host` | Yes | Destination host for the MPEG-TS UDP stream. |
| `udp_port` | No | Destination UDP port. If omitted, the master allocates one from the configured range. |
| `channel_number` | No | TVHeadend channel number. If omitted, the master assigns one using `starting_channel_number`. |
| `tvh_tags` | No | List of TVHeadend tags to include in the generated playlist. |
| `fallback_metadata` | Yes | Metadata used when the metadata source is unavailable. |
| `stream` | Yes | Stream and image-generation settings. |

## Fallback metadata

The `fallback_metadata` object contains the information displayed when current station metadata is unavailable.

| Field | Required | Description |
| --- | --- | --- |
| `title` | Yes | Fallback track title. |
| `artist` | Yes | Fallback artist. |
| `album` | Yes | Fallback album. |
| `image_path` | Yes | Local artwork used for fallback metadata. |

## Stream settings

The `stream` object controls metadata polling, image generation, and the GStreamer output.

| Field | Description |
| --- | --- |
| `update_interval` | Seconds between metadata checks. |
| `metadata_empty_threshold` | Number of consecutive HTTP 204 metadata responses before fallback metadata is displayed. |
| `image_definition` | Vertical image definition used to generate the video frame. |
| `request_timeout` | HTTP request timeout in seconds. |
| `station_logo_retry_interval` | Seconds between attempts to recover the primary station logo after fallback is being used. |
| `video_fps` | Video frame rate. |
| `video_bitrate` | H.264 video bitrate. |
| `audio_bitrate` | AAC audio bitrate. |

All stream settings must be positive integers.

## Channel numbering

A channel can specify its TVHeadend channel number explicitly:

    "channel_number": 1000

If `channel_number` is omitted, the master process assigns a channel number using the `starting_channel_number` configured in `config.json`.

Channel numbers must be unique.

## UDP port allocation

A channel can specify its UDP port explicitly:

    "udp_port": 1234

If `udp_port` is omitted, the master process allocates a port from the configured UDP range.

UDP ports must not be assigned to more than one channel.

Automatically allocated UDP ports are persisted to the channel configuration during normal master startup.

## TVHeadend tags

The optional `tvh_tags` field contains a list of strings used as TVHeadend tags in the generated playlist.

For example:

    "tvh_tags": [
        "Radio",
        "Music"
    ]

## Adapting an example

Copy the example configuration into the channel directory:

    cp examples/channels/example.json channels/my-station.json

Then change the station-specific values.

If you want automatic channel numbering, remove `channel_number`.

If you want automatic UDP port allocation, remove `udp_port`.

After editing the configuration, validate it before starting the master:

    python master.py --validate

If validation succeeds, the channel can be started with the rest of the configured channels.

## Relative paths

Local paths such as fallback artwork are resolved relative to the channel configuration file.

For example, a channel configuration stored in:

    channels/my-station.json

can use:

    ../images/album_cover.png

to refer to:

    images/album_cover.png

in the repository.
