# Example channel configurations

The files in this directory are examples only. They are not intended to be used unchanged.

To add a channel:

1. Copy an example into the `channels/` directory.
2. Give it a unique filename ending in `.json`.
3. Replace the example station, metadata, and stream URLs with values for the station you want to use.
4. Set `channel_number` if you want to choose the TVHeadend channel number explicitly. Omit it to use automatic numbering.
5. Set `udp_port` if you want to choose the UDP port explicitly. Omit it to allow the master process to allocate one from the configured UDP range.
6. Check the configuration before starting the service:

    python master.py --validate

The validation command does not start any streamer processes or modify channel configuration files.

See `docs/configuration.md` and `docs/channels.md` for details about the available settings.
