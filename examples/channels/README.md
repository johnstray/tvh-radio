# Channel configuration examples

These files are templates for creating `tvh-radio` channel configurations.

They use placeholder `example.com` URLs and are **not intended to work as-is**. Copy an example into the project's `channels/` directory and replace the placeholder station information with values for the radio service you want to configure.

## Examples

### `example.json`

A general-purpose starting point.

It demonstrates:

- An explicit channel number.
- Automatic UDP port allocation.
- The normal set of channel and stream settings.

This is the best starting point when you want to understand the complete channel configuration.

### `explicit.json`

Demonstrates fully explicit allocation.

It includes both:

```json
"channel_number": 1001,
"udp_port": 1234
```

Use this approach when you want predictable channel numbers and UDP endpoints.

Make sure the selected channel number and UDP port do not conflict with other channels.

### `automatic.json`

Demonstrates automatic allocation.

It deliberately omits both `channel_number` and `udp_port`.

The master process will allocate these values when the channel is started normally.

This can be useful when managing multiple channels without manually assigning every channel number and UDP port.

## Using an example

1. Copy the desired JSON file into the project's `channels/` directory.
2. Give the copied file a unique name ending in `.json`.
3. Change `channel_name` and `station_name`.
4. Replace the station logo, metadata API and audio stream URLs.
5. Review the fallback metadata and tags.
6. Choose whether channel number and UDP port should be explicit or automatic.
7. Validate the configuration:

```bash
python master.py --validate
```

The validation command checks the configuration without starting streamer processes or modifying the channel files.

See:

- [Configuration](../../docs/configuration.md)
- [Channels](../../docs/channels.md)
