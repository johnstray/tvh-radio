# Configuration

`tvh-radio` uses one master configuration file and one JSON configuration file per channel.

The master configuration controls the overall application, while each channel configuration describes an individual radio station.

## Master configuration

The master configuration is:

    config.json

It contains three sections:

- `playlist`
- `restart`
- `udp`

### `playlist`

| Field | Description |
| --- | --- |
| `output` | Path of the generated M3U8 playlist. |
| `starting_channel_number` | TVHeadend channel number used when a channel does not specify one explicitly. |

### `restart`

| Field | Description |
| --- | --- |
| `limit` | Number of restarts permitted within the restart window before backoff is entered. |
| `window` | Restart window in seconds. |
| `reset_time` | Time in seconds after which restart history is reset following healthy operation. |
| `backoff_time` | Time in seconds to wait before retrying a channel that is restarting too frequently. |

### `udp`

| Field | Description |
| --- | --- |
| `port_start` | First UDP port available for automatic channel allocation. |
| `port_end` | Last UDP port available for automatic channel allocation. |

Channel configurations may explicitly specify a UDP port.

When `udp_port` is omitted, the master allocates a port from the configured range and persists the assignment to the channel configuration.

## Configuration validation

The complete configuration can be checked without starting any streamer processes:

    python master.py --validate

Validation checks both the master configuration and all channel configurations.

It also checks:

- required configuration fields
- stream settings
- channel number assignments
- duplicate UDP ports
- availability of UDP ports for channels without an assigned port

The validation command does not persist automatically allocated UDP ports.

## Example configuration

A complete example channel configuration is available at:

    examples/channels/example.json

See `docs/channels.md` for details about the individual channel configuration fields.
