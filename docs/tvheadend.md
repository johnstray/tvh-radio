# TVHeadend Integration

This guide explains how to configure TVHeadend to use streams provided by `tvh-radio`.

`tvh-radio` outputs each configured radio channel as an MPEG-TS stream over UDP and can also generate an M3U playlist containing the channel information required by TVHeadend.

There are two ways to configure the streams in TVHeadend:

1. Configure each UDP stream manually using an IPTV network.
2. Use the generated playlist with an IPTV Automatic Network.

The second method is useful when you have multiple channels or expect the channel list to change over time.

## How `tvh-radio` integrates with TVHeadend

The basic flow is:

```text
Internet radio stream
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
 TVHeadend services/channels
```

For each channel, `tvh-radio` produces an MPEG-TS stream at the configured UDP address and port.

For example:

```text
udp://127.0.0.1:1234
```

The generated playlist contains the information TVHeadend can use to discover the channels, including channel number, channel name, logo and TVHeadend tags.

## Prerequisites

Before configuring TVHeadend, make sure:

- `tvh-radio` is installed and configured.
- The channel configuration has been validated with:

```bash
python master.py --validate
```

- The `tvh-radio` master process is running.
- At least one channel is configured.
- TVHeadend can access the UDP address and port used by the channel.
- If using the automatic playlist method, TVHeadend can access the generated playlist.

The TVHeadend user interface and exact option names can vary between versions. Where appropriate, use the equivalent option in your installed version.

## Method 1 — Individual IPTV Network

This method configures each `tvh-radio` UDP stream individually.

It can be useful when you only have a small number of channels or want explicit control over each mux.

### 1. Create an IPTV network

In TVHeadend, create a new network using the IPTV network type.

Configure the network according to your TVHeadend installation.

### 2. Add a mux for each channel

Create an IPTV mux for each `tvh-radio` channel.

Use the channel's UDP address as the stream URL, for example:

```text
udp://127.0.0.1:1234
```

Use the UDP host and port from the channel configuration.

For example:

```json
{
    "udp_host": "127.0.0.1",
    "udp_port": 1234
}
```

Repeat this for each channel.

### 3. Discover the service

After the mux has been created, allow TVHeadend to scan/discover the service carried by the MPEG-TS stream.

The discovered service should appear in TVHeadend's service list.

### 4. Map the service to a channel

Map the discovered service to a TVHeadend channel.

Set the channel name, number and other channel properties as appropriate for your setup.

## Method 2 — IPTV Automatic Network

The IPTV Automatic Network method allows TVHeadend to build its IPTV muxes from the generated playlist.

This is generally more convenient when using several `tvh-radio` channels.

### 1. Generate the playlist

`tvh-radio` generates the playlist configured in the master configuration.

For example:

```json
{
    "playlist": {
        "output": "playlist.m3u8",
        "starting_channel_number": 908
    }
}
```

The resulting file is:

```text
playlist.m3u8
```

### 2. Make the playlist accessible to TVHeadend

TVHeadend needs access to the generated playlist.

Depending on your setup and TVHeadend version, this may be a local file path/URL or an HTTP URL.

Use the playlist source format supported by your installed TVHeadend version.

The important requirement is that the TVHeadend process can read the generated playlist.

### 3. Create an IPTV Automatic Network

In TVHeadend, create a network using the IPTV Automatic Network type.

Configure the network's playlist source to point to the generated `playlist.m3u8`.

Save the network configuration.

### 4. Scan the playlist

Allow TVHeadend to scan/update the IPTV Automatic Network.

TVHeadend should read the playlist and create IPTV muxes from its entries.

Each `tvh-radio` channel represented in the playlist should produce a corresponding mux/service for TVHeadend to discover.

### 5. Map discovered services

Once TVHeadend has discovered the services, use the Services section to map them to TVHeadend channels.

Review the resulting channel names and numbers and adjust any TVHeadend-specific settings required by your installation.

## Channel numbers, names, logos and tags

The generated playlist includes channel metadata that TVHeadend can use when importing the channels.

The relevant information includes:

- `tvg-chno` — channel number
- `tvg-name` — channel name
- `tvg-logo` — station logo URL
- `tvh-tags` — TVHeadend tags

This allows the playlist to carry much of the channel information needed by TVHeadend.

For example, a playlist entry may contain information equivalent to:

```text
tvg-chno="909"
tvg-name="Woolworths Radio"
tvg-logo="https://example.com/logo.png"
tvh-tags="Radio,Music,iHeartRadio"
```

The exact way TVHeadend displays or applies imported metadata can vary by version and configuration, so review the resulting muxes, services and channels after discovery.

## Updating the playlist

If the channel configuration changes, `tvh-radio` can regenerate the playlist with the updated channel information.

For example, changes may include:

- adding a channel
- removing a channel
- changing a channel number
- changing a station logo
- changing TVHeadend tags
- changing the UDP endpoint

After changing the configuration, validate it:

```bash
python master.py --validate
```

Then restart or reload the `tvh-radio` master process as appropriate for the change.

If using an IPTV Automatic Network, update/rescan the network in TVHeadend so it reads the current playlist.

Review the resulting muxes, services and channels after an update, particularly if channels have been added or removed.

## Troubleshooting and diagnostics

When diagnosing a problem, it is useful to determine whether the issue is with `tvh-radio`, the UDP stream, or TVHeadend.

### Test a UDP stream with mpv

`mpv` can be used to test an individual MPEG-TS stream without involving TVHeadend.

For example:

```bash
mpv udp://127.0.0.1:1234
```

Replace the address and port with the values for the channel you are testing.

If the stream plays correctly in `mpv`, the `tvh-radio` streamer is producing usable MPEG-TS output and the problem can be investigated further in the TVHeadend configuration.

If `mpv` cannot play the stream, check the `tvh-radio` process and its logs first.

### Check the tvh-radio logs

When running under systemd, view the service logs with:

```bash
journalctl -u tvh-radio
```

For live logs:

```bash
journalctl -u tvh-radio -f
```

Look for messages relating to:

- channel startup
- metadata requests
- artwork
- GStreamer
- audio recovery
- streamer restarts
- configuration errors

### Check the UDP endpoint

Confirm that the channel is configured with the expected UDP host and port.

For example:

```json
{
    "udp_host": "127.0.0.1",
    "udp_port": 1234
}
```

Also check that another process is not already using the same UDP port.

### Check TVHeadend mux and service discovery

If the UDP stream works with `mpv` but TVHeadend does not discover a service:

1. Check that the mux uses the correct UDP address.
2. Check the TVHeadend network type.
3. Check the mux status.
4. Check whether TVHeadend has discovered a service.
5. Check the Services section for the discovered service.
6. Map the service to a channel if necessary.

### Check the automatic playlist

If using IPTV Automatic Network:

1. Confirm that `playlist.m3u8` exists.
2. Confirm that it contains the expected channels.
3. Confirm that TVHeadend can access the playlist.
4. Confirm that the playlist source configured in TVHeadend is correct.
5. Rescan/update the IPTV Automatic Network.
6. Check the resulting muxes and services.

### Check channel metadata

If the stream works but the channel name, number, logo or tags are not what you expect, inspect the generated playlist and verify the relevant values.

In particular, check:

```text
tvg-chno
tvg-name
tvg-logo
tvh-tags
```

This helps determine whether the problem originates in the playlist or in TVHeadend's handling of the imported metadata.

## Official TVHeadend documentation

The following official TVHeadend documentation provides additional information:

- [TVHeadend documentation — Concepts](https://docs.tvheadend.org/documentation/setup/concepts)
- [TVHeadend documentation — First configuration](https://github.com/tvheadend/tvheadend/blob/master/docs/markdown/firstconfig.md)
- [TVHeadend documentation — MPEG-TS / IPTV network](https://github.com/tvheadend/tvheadend/blob/master/docs/class/mpegts_network.md)
