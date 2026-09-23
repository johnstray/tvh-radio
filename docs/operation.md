# Operating tvh-radio

This guide covers the day-to-day operation of an installed `tvh-radio` system.

It focuses on starting, stopping and monitoring the service, managing channels, understanding automatic recovery, and applying configuration changes.

For initial installation, see [Installation](installation.md).

For configuration details, see [Configuration](configuration.md) and [Channels](channels.md).

For TVHeadend setup, see [TVHeadend Integration](tvheadend.md).

## How tvh-radio operates

`tvh-radio` uses a master process to manage the individual channel streamers.

```text
tvh-radio master
    ├── streamer: channel 1
    ├── streamer: channel 2
    ├── streamer: channel 3
    └── ...
```

The master process is responsible for:

- Loading and validating channel configuration.
- Starting the configured streamers.
- Monitoring streamer processes.
- Restarting streamers when they fail.
- Applying the configured restart limits and backoff behaviour.
- Shutting down streamers cleanly when the master stops.
- Maintaining the generated M3U playlist.

Each streamer is responsible for one radio channel. It handles the radio stream, metadata, artwork, generated video and MPEG-TS output for that channel.

## Starting and stopping tvh-radio

### Running manually

For testing or development, the master process can be started directly:

```bash
python master.py
```

The master will load the configuration, start the configured channel streamers and monitor them.

Stop a manually started instance with:

```text
Ctrl+C
```

The master will initiate a graceful shutdown of its channel streamers.

### Running with systemd

For normal operation, `tvh-radio` should be run as a systemd service.

Start the service with:

```bash
sudo systemctl start tvh-radio
```

Stop it with:

```bash
sudo systemctl stop tvh-radio
```

Restart it with:

```bash
sudo systemctl restart tvh-radio
```

Enable automatic startup when the system boots:

```bash
sudo systemctl enable tvh-radio
```

## Checking service status

Use:

```bash
sudo systemctl status tvh-radio
```

This shows whether the master process is running and provides recent service output.

For a service that should be running continuously, the expected state is:

```text
active (running)
```

If the service is not running, check the systemd logs before restarting it repeatedly.

## Viewing logs

When running under systemd, the service logs can be viewed with:

```bash
journalctl -u tvh-radio
```

To follow the logs as they are produced:

```bash
journalctl -u tvh-radio -f
```

To view recent entries:

```bash
journalctl -u tvh-radio --since "1 hour ago"
```

The logs include messages from the master and its channel streamers.

Useful events to look for include:

- Channel startup.
- Channel shutdown.
- Streamer failures and restarts.
- Restart backoff.
- Metadata requests.
- Metadata changes.
- Artwork handling.
- Audio recovery.
- Configuration errors.
- Master shutdown.

## Understanding channel processes

The master process starts one streamer process for each configured channel.

This means a running system normally consists of:

```text
master.py
    ├── streamer.py
    ├── streamer.py
    ├── streamer.py
    └── ...
```

The exact process names shown by tools such as `ps` or `htop` may vary.

Python may also show threads underneath a process. These are not additional streamer processes.

The important distinction is that the master owns the channel processes and is responsible for monitoring and restarting them.

## Automatic streamer recovery

If a streamer process exits unexpectedly, the master can restart it.

The restart behaviour is controlled by the `restart` section of the master configuration:

```json
{
    "restart": {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 300
    }
}
```

These settings control how repeated failures are handled:

- `limit` — number of failures allowed within the restart window before backoff is entered.
- `window` — period, in seconds, in which failures are considered part of the same restart loop.
- `reset_time` — how long a channel must remain healthy before its restart history is reset.
- `backoff_time` — how long the master waits before attempting another restart after a restart loop is detected.

When a channel enters backoff, other channels continue operating.

## Graceful shutdown

When the master process receives a normal shutdown request, it asks its channel streamers to shut down cleanly.

This allows the streamers to:

- Stop the GStreamer pipeline.
- Close network resources.
- Exit cleanly.
- Allow the master to wait for its child processes.

When using systemd, a normal service stop or system shutdown should therefore allow the master and its streamers to shut down cleanly.

## Applying configuration changes

Before applying configuration changes, validate the configuration:

```bash
python master.py --validate
```

A successful validation checks the configuration without starting streamer processes or modifying the configuration files.

After changing configuration, restart the service:

```bash
sudo systemctl restart tvh-radio
```

Then check the status and logs:

```bash
sudo systemctl status tvh-radio
journalctl -u tvh-radio -f
```

## Adding a channel

To add a channel:

1. Create a new JSON file in `channels/`.
2. Configure the channel according to [Channels](channels.md).
3. Choose whether to assign an explicit channel number and UDP port or allow them to be allocated automatically.
4. Validate the configuration:

```bash
python master.py --validate
```

5. Restart `tvh-radio`:

```bash
sudo systemctl restart tvh-radio
```

6. Check the logs to confirm that the new streamer starts successfully.
7. If using the generated playlist, update or rescan the corresponding IPTV Automatic Network in TVHeadend.

## Removing a channel

To remove a channel:

1. Remove the channel's JSON configuration from `channels/`.
2. Validate the remaining configuration:

```bash
python master.py --validate
```

3. Restart `tvh-radio`:

```bash
sudo systemctl restart tvh-radio
```

4. If using the generated playlist, update or rescan the corresponding IPTV Automatic Network in TVHeadend.

If the channel was previously configured in TVHeadend, remove or disable the corresponding TVHeadend mux, service or channel as appropriate for your setup.

## Updating the generated playlist

The master generates the playlist configured in the master configuration.

For example:

```json
{
    "playlist": {
        "output": "playlist.m3u8",
        "starting_channel_number": 908
    }
}
```

Changes to the channel configuration may therefore change the generated playlist.

After making channel changes:

```bash
python master.py --validate
sudo systemctl restart tvh-radio
```

If TVHeadend is using the playlist through an IPTV Automatic Network, update or rescan that network so TVHeadend reads the current playlist.

## Routine operational checks

Useful checks for a long-running installation include:

### Check the service

```bash
sudo systemctl status tvh-radio
```

### Check recent logs

```bash
journalctl -u tvh-radio --since "1 hour ago"
```

### Follow logs

```bash
journalctl -u tvh-radio -f
```

### Validate configuration

```bash
python master.py --validate
```

### Check the generated playlist

```bash
cat playlist.m3u8
```

The actual playlist location depends on the `playlist.output` setting.

### Check system resources

Tools such as `top` and `htop` can be used to check CPU and memory usage.

## Restarting the whole service

A normal service restart is:

```bash
sudo systemctl restart tvh-radio
```

After restarting, check:

```bash
sudo systemctl status tvh-radio
```

and, if necessary:

```bash
journalctl -u tvh-radio -f
```

A restart affects the master and all managed channel streamers.

If only one channel is having problems, investigate that channel's logs and configuration before restarting the entire service.

## Useful commands

| Purpose | Command |
|---|---|
| Validate configuration | `python master.py --validate` |
| Start service | `sudo systemctl start tvh-radio` |
| Stop service | `sudo systemctl stop tvh-radio` |
| Restart service | `sudo systemctl restart tvh-radio` |
| Enable at boot | `sudo systemctl enable tvh-radio` |
| Check service status | `sudo systemctl status tvh-radio` |
| View service logs | `journalctl -u tvh-radio` |
| Follow service logs | `journalctl -u tvh-radio -f` |
| View recent logs | `journalctl -u tvh-radio --since "1 hour ago"` |
| View processes | `ps --forest -C python` |
| Monitor resources | `htop` |

## Related documentation

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Channels](channels.md)
- [TVHeadend Integration](tvheadend.md)
- [Troubleshooting](troubleshooting.md)
