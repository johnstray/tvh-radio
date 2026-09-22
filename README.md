# tvh-radio

Turn almost any internet radio stream into a TVHeadend-compatible channel with generated video showing station and now-playing information.

`tvh-radio` uses GStreamer to combine a radio stream with dynamically generated video, producing an MPEG-TS stream that can be consumed by TVHeadend.

> **Status:** This project is under active development and is not yet considered a public release.

## How it works

Each configured radio station runs as its own streamer process.

```text
Radio stream
     │
     ├── Audio ──────────────┐
     │                       │
     └── Track metadata      │
              │              │
              ▼              │
       Pillow-generated      │
          JPEG video         │
              │              │
              ▼              ▼
          GStreamer
              │
       H.264 + AAC
              │
          MPEG-TS
              │
             UDP
              │
         TVHeadend
```

The master process manages the individual streamer processes:

```text
systemd
   │
   ▼
master.py
   ├── streamer.py → channel 1
   ├── streamer.py → channel 2
   ├── streamer.py → channel 3
   └── ...
```

The master process is responsible for:

- discovering channel configurations
- assigning UDP ports
- starting streamer processes
- monitoring streamer processes
- restarting failed streamers
- generating the TVHeadend M3U8 playlist
- gracefully shutting down channels

Each streamer is responsible for:

- retrieving track metadata
- generating the now-playing image
- streaming the source audio
- encoding video and audio with GStreamer
- producing the MPEG-TS UDP stream
- recovering from temporary audio or metadata failures

## Requirements

`tvh-radio` is intended for Linux systems.

### System dependencies

The following are required from the operating system:

- Python 3
- GStreamer 1.x
- GStreamer plugins required by the configured pipeline
- PyGObject / GObject Introspection
- GStreamer Python bindings

The exact package names vary between Linux distributions.

For example, on a Fedora-based system, the GStreamer and PyGObject packages should be installed using the system package manager rather than pip.

### Python dependencies

Python dependencies are listed in:

```text
requirements.txt
```

## Installation

Clone the repository:

```bash
git clone https://github.com/johnstray/tvh-radio.git
cd tvh-radio
```

### Create a virtual environment

Create the virtual environment with access to the system-installed PyGObject and GStreamer bindings:

```bash
python3 -m venv .venv --system-site-packages
```

Activate it:

```bash
source .venv/bin/activate
```

Install the Python dependencies:

```bash
python -m pip install -r requirements.txt
```

The virtual environment is intentionally not stored in Git.

### Verify the environment

Check Python:

```bash
python --version
```

Check PyGObject:

```bash
python -c "import gi; print('PyGObject:', gi.__version__)"
```

Check GStreamer:

```bash
python -c "from gi.repository import Gst; Gst.init(None); print('GStreamer:', Gst.version_string())"
```

Check Pillow:

```bash
python -c "import PIL; print('Pillow:', PIL.__version__)"
```

All of these should complete successfully before continuing.

## Configuration

The master process uses:

```text
config.json
```

Channel configurations are stored in:

```text
channels/
```

Each JSON file represents one radio channel.

The master configuration controls items such as:

- playlist output
- starting TVHeadend channel number
- streamer restart behaviour
- UDP port allocation range

Example:

```json
{
    "playlist": {
        "output": "playlist.m3u8",
        "starting_channel_number": 908
    },
    "restart": {
        "limit": 3,
        "window": 60,
        "reset_time": 300,
        "backoff_time": 300
    },
    "udp": {
        "port_start": 1234,
        "port_end": 1333
    }
}
```

UDP ports can be assigned explicitly in a channel configuration, or automatically allocated from the configured UDP port range.

Automatically allocated ports are written back to the channel configuration so that the assignment persists between restarts.

## Running manually

For development and testing, activate the virtual environment and run:

```bash
python master.py
```

The master process will discover the channel configurations and start one streamer process for each channel.

To stop the application, press:

```text
Ctrl+C
```

The master will request a graceful shutdown of all streamer processes.

## iHeartRadio channel extractor

The `iheart_extract/` directory contains a tool for extracting station information from iHeartRadio station pages.

See:

```text
iheart_extract/README.md
```

for usage instructions.

The extractor can output a complete channel configuration template using:

```bash
python iheart_extract/iheart_extract.py --channel-json <URL>
```

## systemd

For a long-running installation, `tvh-radio` can be managed by systemd.

An example service file is provided in:

```text
systemd/tvh-radio.service
```

The example assumes the application is installed under:

```text
/opt/tvh-radio
```

and that the Python virtual environment is:

```text
/opt/tvh-radio/.venv
```

Before installing the service, adjust the `User` and `Group` settings to match the account that should run `tvh-radio`.

Install the service:

```bash
sudo cp systemd/tvh-radio.service /etc/systemd/system/
```

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Start the service:

```bash
sudo systemctl start tvh-radio
```

Check its status:

```bash
systemctl status tvh-radio
```

Enable automatic startup at boot:

```bash
sudo systemctl enable tvh-radio
```

Or enable and start it in one command:

```bash
sudo systemctl enable --now tvh-radio
```

### Viewing logs

When running under systemd, application and streamer output is available through journald:

```bash
journalctl -u tvh-radio
```

Follow the log in real time:

```bash
journalctl -u tvh-radio -f
```

The master process forwards streamer output into the service log.

### Process recovery

systemd manages the master process, while the master manages the individual streamer processes.

If the master unexpectedly exits, systemd restarts it and cleans up the existing service processes before starting the replacement.

If an individual streamer exits unexpectedly, the master can restart that streamer independently.

This separation prevents a failed channel from unnecessarily taking down the other channels.

## Development and testing

The project is being developed incrementally with manual testing after significant changes.

The main end-to-end path is:

```text
Pillow metadata
    ↓
GStreamer
    ↓
H.264 + AAC
    ↓
MPEG-TS
    ↓
UDP
    ↓
TVHeadend
    ↓
TVHeadend service
    ↓
tvhproxy
    ↓
Plex Live TV
```

### Regression test checklist

At minimum, an end-to-end test should confirm:

- video appears
- audio works
- metadata artwork updates
- no sustained GStreamer errors occur
- the stream survives normal operation
- audio reconnects after a temporary source failure
- graceful shutdown works
- failed streamer processes restart
- the master can recover after an unexpected failure
- the generated playlist contains the expected channels

## Project status

`tvh-radio` is still under active development.

The current architecture is focused on providing a reliable foundation for running multiple radio channels through TVHeadend. Future development will expand the master process, configuration management, monitoring, demand-based channel startup, and other operational features.

## License

See [LICENSE.md](LICENSE.md).
