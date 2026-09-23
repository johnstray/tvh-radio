# Troubleshooting tvh-radio

This guide provides a practical approach to diagnosing problems with `tvh-radio`.

The most useful first step is to determine which part of the system is failing:

```text
Radio source / metadata
        |
        v
    tvh-radio
        |
        v
 MPEG-TS over UDP
        |
        v
   TVHeadend
        |
        v
   Client/player
```

Work through the layers from left to right rather than changing several things at once.

For normal operation and service management, see [Operation](operation.md).

For TVHeadend configuration, see [TVHeadend Integration](tvheadend.md).

## Start with the logs

When running under systemd, check the service status:

```bash
sudo systemctl status tvh-radio
```

Then inspect recent logs:

```bash
journalctl -u tvh-radio --since "1 hour ago"
```

To follow the logs live:

```bash
journalctl -u tvh-radio -f
```

The logs from the master and individual streamers can help identify whether the problem is related to configuration, metadata, artwork, audio, GStreamer, or process recovery.

## Configuration problems

### Validate before starting

Run:

```bash
python master.py --validate
```

This checks the master and channel configuration without starting streamer processes.

If validation reports an error, fix the configuration before starting or restarting the service.

### A required channel setting is missing

Validation errors identify the affected channel configuration where possible.

Check the channel against [Channels](channels.md) and make sure all required fields are present.

### A stream setting is invalid

The `stream` settings are expected to be positive integers.

Check values such as:

- `update_interval`
- `metadata_empty_threshold`
- `image_definition`
- `request_timeout`
- `station_logo_retry_interval`
- `video_fps`
- `video_bitrate`
- `audio_bitrate`

Run validation again after correcting the value.

### Duplicate UDP ports

Each channel needs its own UDP output port.

If validation reports a duplicate UDP port, assign a different explicit port or allow the master to allocate one automatically.

## The master process will not start

First validate the configuration:

```bash
python master.py --validate
```

If validation succeeds, check the service logs:

```bash
journalctl -u tvh-radio --since "10 minutes ago"
```

If running manually, start the master directly:

```bash
python master.py
```

This can make configuration or startup errors easier to see.

Also confirm that the Python environment and required GStreamer/PyGObject dependencies are installed as described in [Installation](installation.md).

## A channel does not start

If the master is running but a channel is not producing a stream:

1. Check the master log for the channel.
2. Check whether the streamer was started.
3. Look for configuration, GStreamer, metadata or network errors.
4. Check whether the channel has entered restart backoff.
5. Test the UDP stream independently if the streamer is running.

The master is designed to restart a failed streamer according to the configured restart policy.

## A channel repeatedly restarts

Check the logs for the restart sequence.

The master tracks repeated failures and eventually places a channel into backoff when the configured restart limit is reached.

The relevant settings are:

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

Check:

- How often the streamer is failing.
- Whether the failure occurs immediately after startup.
- Whether the failure is caused by configuration.
- Whether the radio source is unavailable.
- Whether GStreamer reports an error.
- Whether the problem affects one channel or multiple channels.

Do not repeatedly restart the whole service without investigating the underlying channel failure.

## Testing the UDP stream with mpv

Testing the UDP output independently of TVHeadend is one of the most useful diagnostic steps.

For example:

```bash
mpv udp://127.0.0.1:1234
```

Replace the address and port with the channel's configured UDP endpoint.

If `mpv` plays the stream correctly, `tvh-radio` is producing a usable MPEG-TS stream and the problem is likely further downstream.

If `mpv` cannot play the stream, continue investigating the streamer and its logs.

This test is particularly useful for separating `tvh-radio` problems from TVHeadend configuration problems.

## Video problems

### No video

Check the streamer logs for GStreamer errors.

Also test the UDP stream with `mpv`.

If the streamer is running but the MPEG-TS stream does not contain usable video, the problem may be in the image source, GStreamer pipeline or video encoder.

### Video stops updating

The video image is generated from metadata and artwork.

A metadata change causes the now-playing image to be regenerated. During temporary metadata gaps, the existing image can be retained rather than immediately replacing it.

If the metadata API remains unavailable for the configured threshold, fallback metadata is used.

Check the logs for metadata errors and fallback behaviour.

### GStreamer reports `not-negotiated`

A `not-negotiated` error generally indicates that elements in the GStreamer pipeline could not agree on the required media format.

Check the GStreamer-related log message for the element named in the error.

If the problem occurs during image processing, check the generated image format, dimensions and the video pipeline's expected input format.

If the problem persists, reproduce the issue with a direct GStreamer test where possible so the pipeline error can be isolated from the rest of the application.

## Audio problems

### No audio

First test the UDP stream with `mpv`.

If video works but audio does not, check the streamer logs for Icecast or GStreamer errors.

Also verify the configured `icecast_url`.

### Audio temporarily stops

`tvh-radio` includes audio source recovery.

A temporary Icecast failure should not necessarily stop the video stream. The streamer can attempt to recover the audio source while continuing to produce the video side of the stream.

Check the logs to determine whether the audio source was lost and subsequently recovered.

### Audio does not recover

Check:

1. Whether the Icecast URL is still reachable.
2. Whether the radio provider is currently serving the stream.
3. Whether the streamer is reporting repeated audio recovery attempts.
4. Whether the channel eventually exits and is restarted by the master.

If the source itself is unavailable, `tvh-radio` cannot restore audio until the source becomes available again.

## Metadata problems

### Metadata API is unavailable

If the metadata endpoint cannot be reached, the streamer uses its configured fallback behaviour.

Check the `track_meta_url` and the service logs.

A metadata API failure does not necessarily mean the audio stream is unavailable.

### Metadata API returns HTTP 204

An HTTP 204 response means the metadata endpoint returned no content.

`tvh-radio` treats temporary empty responses differently from a normal metadata update.

The streamer tracks consecutive empty responses and uses the configured `metadata_empty_threshold` to decide when fallback metadata should be used.

Check the logs if you need to determine how many consecutive empty responses have occurred.

### Metadata response is invalid

If the response cannot be parsed or does not contain the expected information, check the logs for the metadata error.

The streamer should fall back rather than allowing a malformed metadata response to bring down the channel.

### Individual metadata fields are missing

If a metadata response is missing individual fields such as title, artist, album or artwork, the streamer uses the available information and its configured fallback behaviour.

Check the generated image and logs to determine which metadata was available.

## Artwork problems

### Album artwork is unavailable

If album artwork cannot be downloaded or is unavailable, the configured fallback artwork is used.

The default example is:

```text
../images/album_cover.png
```

Check the `fallback_metadata.image_path` setting in the channel configuration.

### Station logo is unavailable

The station logo has a separate fallback sequence:

```text
Primary station logo
        |
        v
Configured fallback station logo
        |
        v
Generic station logo
```

The generic fallback is:

```text
images/station_logo.png
```

The streamer also retries the primary station logo according to `station_logo_retry_interval`.

This means a temporary failure to download the station logo does not need to interrupt the channel.

## TVHeadend cannot find the channel

If the stream works in `mpv` but TVHeadend cannot discover it, investigate the TVHeadend side.

Check:

1. The UDP address and port.
2. The IPTV network configuration.
3. The mux configuration.
4. Whether the mux is active.
5. Whether a service has been discovered.
6. Whether the service has been mapped to a channel.

For IPTV Automatic Network configurations, also check that TVHeadend can access the generated playlist and that the playlist contains the expected entry.

See [TVHeadend Integration](tvheadend.md) for the setup procedure.

## TVHeadend has the channel but metadata is wrong

Check the generated playlist:

```bash
cat playlist.m3u8
```

Look for:

```text
tvg-chno
tvg-name
tvg-logo
tvh-tags
```

If the values in the playlist are correct but TVHeadend displays something different, investigate the TVHeadend service/channel configuration.

## The playlist is missing a channel

First validate and restart `tvh-radio`:

```bash
python master.py --validate
sudo systemctl restart tvh-radio
```

Then inspect the generated playlist:

```bash
cat playlist.m3u8
```

If the channel is missing from the playlist, check its channel configuration and the master logs.

If the channel is present in the playlist but missing from TVHeadend, update/rescan the IPTV Automatic Network.

## CPU or memory usage is unexpectedly high

Check the running processes with:

```bash
htop
```

or:

```bash
ps --forest -C python
```

Remember that Python threads may appear underneath a process in process-monitoring tools.

If resource usage is unexpectedly high, check:

- How many channels are running.
- Whether one channel is repeatedly restarting.
- Whether a GStreamer pipeline is reporting errors.
- Whether an external service is repeatedly failing and causing repeated work.

## One channel fails while others continue working

This is normally handled independently by the master.

Check the affected channel's log messages and configuration first.

The failure of one streamer should not require the other channels to be restarted.

If the channel has entered restart backoff, its restart state can be identified in the master logs.

## Multiple channels fail at the same time

When several channels fail together, investigate shared dependencies before treating the failures as independent channel problems.

Check:

- The `tvh-radio` master process.
- System resource usage.
- Network connectivity.
- GStreamer/system dependencies.
- External radio or metadata services.
- The system clock and general system health.

If all streamers fail at approximately the same time, a common dependency is more likely to be relevant than an individual channel configuration.

## After changing configuration

Always validate first:

```bash
python master.py --validate
```

Then restart the service:

```bash
sudo systemctl restart tvh-radio
```

Watch the logs during startup:

```bash
journalctl -u tvh-radio -f
```

If the change affects channels exposed through TVHeadend, check the relevant muxes, services and channels afterwards.

## Useful diagnostic sequence

When a channel is not working, use this order:

1. Check whether `tvh-radio` is running.
2. Check the master and streamer logs.
3. Validate the configuration.
4. Check whether the affected streamer is running or repeatedly restarting.
5. Test the UDP stream directly with `mpv`.
6. If the UDP stream works, investigate TVHeadend.
7. If the UDP stream does not work, continue investigating the streamer.
8. Check external radio, metadata and artwork services when relevant.

This helps isolate the problem without changing several parts of the system at once.

## Related documentation

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Channels](channels.md)
- [Operation](operation.md)
- [TVHeadend Integration](tvheadend.md)
