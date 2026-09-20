import json
import logging
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


RESTART_LIMIT = 3  # count
RESTART_WINDOW = 60  # seconds
RESTART_RESET_TIME = 300  # seconds
RESTART_BACKOFF_TIME = 300  # seconds


logger = logging.getLogger("tvh-radio.master")
processes = {}
shutdown_requested = False

def configure_logging():
    """Configure logging for the master process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ------------------------------------------------------------------------------
# Channel Configuration Management
# ------------------------------------------------------------------------------

def find_channel_configs(config_directory):
    """Find all JSON channel configuration files."""
    config_path = Path(config_directory)

    return sorted(config_path.glob("*.json"))


def load_channel_config(config_file):
    """Load a channel configuration from a JSON file."""
    with open(config_file, "r", encoding="utf-8") as file:
        return json.load(file)


def validate_channel_config(config):
    """Validate the required fields in a channel configuration."""
    required_keys = [
        "channel_name",
        "station_name",
        "station_logo",
        "fallback_station_logo",
        "track_meta_url",
        "icecast_url",
        "udp_host",
        "udp_port",
        "fallback_metadata",
    ]

    for key in required_keys:
        if key not in config:
            raise ValueError(
                f"Missing required configuration value: {key}"
            )

    fallback_keys = [
        "title",
        "artist",
        "album",
        "image_path",
    ]

    for key in fallback_keys:
        if key not in config["fallback_metadata"]:
            raise ValueError(
                f"Missing required fallback metadata value: {key}"
            )


def load_channel_configs(config_directory):
    """Find, load, and validate all channel configurations."""
    config_files = find_channel_configs(config_directory)
    channels = []

    for config_file in config_files:
        config = load_channel_config(config_file)
        validate_channel_config(config)
        channels.append((config_file, config))

    return channels


# ------------------------------------------------------------------------------
# Streamer Process Management
# ------------------------------------------------------------------------------

def start_channel(channel):
    """Start a streamer process for a channel."""
    process = subprocess.Popen(
        [sys.executable, "streamer.py", str(channel["config_file"])],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    channel["process"] = process

    output_thread = threading.Thread(
        target=read_channel_output,
        args=(channel,),
        daemon=True,
    )
    output_thread.start()


def is_restart_loop(channel):
    """Return True if a channel is restarting too frequently."""
    if channel["last_restart"] is None:
        return False

    elapsed = time.monotonic() - channel["last_restart"]

    return (
        channel["restart_count"] >= RESTART_LIMIT
        and elapsed <= RESTART_WINDOW
    )


def is_backoff_expired(channel):
    """Return True if a channel's backoff period has expired."""
    if channel["state"] != "backoff":
        return False

    if channel["next_restart"] is None:
        return False

    return time.monotonic() >= channel["next_restart"]


def restart_channel(channel):
    """Restart a channel process."""
    channel["restart_count"] += 1
    channel["last_restart"] = time.monotonic()

    logger.warning(f"Restarting channel '{channel['channel_name']}'.")

    process = start_channel(channel)

    logger.info(
        f"Channel '{channel['channel_name']}' restarted with PID {process.pid}."
    )


def read_channel_output(channel):
    """Read and log output from a channel process."""
    for line in channel["process"].stdout:
        logger.info(f"[{channel['channel_name']}] {line.rstrip()}")


def create_channel_state(config_file, config):
    """Create the runtime state for a channel."""
    return {
        "channel_name": config["channel_name"],
        "config": config,
        "config_file": config_file,
        "process": None,
        "stopping": False,
        "restart_count": 0,
        "last_restart": None,
        "state": "running",
        "next_restart": None
    }


def start_channels(channels):
    """Start all configured channel processes."""
    processes = {}

    for config_file, channel in channels:
        channel_state = create_channel_state(config_file, channel)
        channel_name = channel_state["channel_name"]

        logger.info(f"Starting channel: {channel_name}")

        process = start_channel(channel_state)

        logger.info(
            f"Channel '{channel_name}' started with PID {channel_state['process']}."
        )

        processes[channel_name] = channel_state

    return processes


def monitor_channels(processes):
    """Monitor all running channel processes."""
    while not shutdown_requested:
        channels_to_remove = []

        for channel in processes.values():
            process = channel["process"]

            if channel["state"] == "backoff":
                if is_backoff_expired(channel):
                    logger.info(
                        f"Backoff expired for channel '{channel['channel_name']}'. "
                        "Attempting restart."
                    )

                    channel["restart_count"] = 0
                    channel["last_restart"] = None
                    channel["next_restart"] = None

                    restart_channel(channel)

                    channel["state"] = "running"

                continue

            if (
                channel["last_restart"] is not None
                and time.monotonic() - channel["last_restart"] >= RESTART_RESET_TIME
            ):
                logger.info(
                    f"Channel '{channel['channel_name']}' has been healthy for "
                    f"{RESTART_RESET_TIME} seconds. Resetting restart history."
                )
                channel["restart_count"] = 0
                channel["last_restart"] = None

            if process.poll() is not None:
                exit_code = process.returncode

                if channel["stopping"]:
                    logger.info(
                        f"Channel '{channel['channel_name']}' stopped intentionally."
                    )
                    channels_to_remove.append(channel["channel_name"])
                    continue

                logger.warning(
                    f"Channel '{channel['channel_name']}' has exited "
                    f"with code {exit_code}."
                )

                if exit_code != 0:
                    if is_restart_loop(channel):
                        channel["state"] = "backoff"
                        channel["next_restart"] = (
                            time.monotonic() + RESTART_BACKOFF_TIME
                        )

                        logger.error(
                            f"Channel '{channel['channel_name']}' is restarting too frequently. "
                            f"Entering backoff for {RESTART_BACKOFF_TIME} seconds."
                        )
                        continue

                    restart_channel(channel)
                    continue

                channels_to_remove.append(channel["channel_name"])

        for channel_name in channels_to_remove:
            del processes[channel_name]

        time.sleep(1)


def shutdown_channels(processes):
    """Request a graceful shutdown of all running channels."""
    for channel in processes.values():

        logger.info(f"Stopping channel '{channel['channel_name']}'.")

        channel["stopping"] = True
        channel["process"].terminate()


# ------------------------------------------------------------------------------
# Main Execution
# ------------------------------------------------------------------------------

def handle_shutdown_signal(signum, frame):
    """Handle a termination signal received by the master."""
    global shutdown_requested

    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name}. Shutting down master.")

    shutdown_requested = True
    shutdown_channels(processes)


if __name__ == "__main__":
    configure_logging()

    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    logger.info("tvh-radio master starting.")

    channels = load_channel_configs("config")
    processes.update(start_channels(channels))

    monitor_channels(processes)
