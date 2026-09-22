# Installation

`tvh-radio` is intended for Linux systems and requires Python 3, GStreamer 1.x, the GStreamer plugins used by the configured pipeline, and the Python GStreamer/PyGObject bindings.

## Clone the repository

Clone the repository and change into the project directory:

    git clone https://github.com/johnstray/tvh-radio.git
    cd tvh-radio

## System dependencies

Install Python 3, GStreamer, the required GStreamer plugins, and PyGObject/GObject Introspection using the package manager for your Linux distribution.

The exact package names vary between distributions.

The required GStreamer elements include those used to:

- read JPEG image data
- encode H.264 video
- encode AAC audio
- create MPEG-TS output
- send MPEG-TS over UDP

The exact packages required depend on the Linux distribution.

## Python virtual environment

Create a virtual environment with access to the system-installed PyGObject and GStreamer bindings:

    python3 -m venv .venv --system-site-packages
    source .venv/bin/activate

Install the Python dependencies:

    python -m pip install -r requirements.txt

The `--system-site-packages` option is intentional. PyGObject and the GStreamer Python bindings are expected to come from the operating system rather than from `pip`.

## Verify the environment

Check the installed Python version:

    python --version

Check PyGObject:

    python -c "import gi; print('PyGObject:', gi.__version__)"

Check GStreamer:

    python -c "from gi.repository import Gst; Gst.init(None); print('GStreamer:', Gst.version_string())"

Check Pillow:

    python -c "import PIL; print('Pillow:', PIL.__version__)"

All commands should complete successfully.

## Validate the configuration

Before starting the master process, validate the complete configuration:

    python master.py --validate

A successful validation confirms that the master and channel configurations can be loaded and that the configured channel numbers and UDP allocation can be resolved.

Configuration validation does not start streamer processes or modify channel configuration files.

## Run manually

For development and testing, start the master process directly:

    python master.py

Press `Ctrl+C` to request a graceful shutdown.

## systemd

A systemd service template is provided at:

    systemd/tvh-radio.service

Review the following settings before installing it:

- `User`
- `Group`
- `WorkingDirectory`
- `ExecStart`

The service is designed to run the master process, which manages the individual channel streamer processes.

See the project README for the current systemd installation procedure.
