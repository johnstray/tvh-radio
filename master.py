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


logger = logging.getLogger("tvh-radio.master")
processes = {}

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

def start_channel(config_file):
    """Start a streamer process for a channel."""
    return subprocess.Popen(
        [sys.executable, "streamer.py", str(config_file)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True
    )


def is_restart_loop(channel):
    """Return True if a channel is restarting too frequently."""
    if channel["last_restart"] is None:
        return False

    elapsed = time.monotonic() - channel["last_restart"]

    return (
        channel["restart_count"] >= RESTART_LIMIT
        and elapsed <= RESTART_WINDOW
    )


def restart_channel(config_file, channel_name, channel):
    """Restart a channel process."""
    channel["restart_count"] += 1
    channel["last_restart"] = time.monotonic()

    logger.warning(f"Restarting channel '{channel_name}'.")

    process = start_channel(config_file)

    logger.info(
        f"Channel '{channel_name}' restarted with PID {process.pid}."
    )

    output_thread = threading.Thread(
        target=read_channel_output,
        args=(process, channel_name),
        daemon=True,
    )
    output_thread.start()

    return process


def read_channel_output(process, channel_name):
    """Read and log output from a channel process."""
    for line in process.stdout:
        logger.info(f"[{channel_name}] {line.rstrip()}")


def start_channels(channels):
    """Start all configured channel processes."""
    processes = {}

    for config_file, channel in channels:
        channel_name = channel["channel_name"]

        logger.info(f"Starting channel: {channel_name}")

        process = start_channel(config_file)

        logger.info(
            f"Channel '{channel_name}' started with PID {process.pid}."
        )

        processes[channel_name] = {
            "config_file": config_file,
            "process": process,
            "stopping": False,
            "restart_count": 0,
            "last_restart": None
        }

        output_thread = threading.Thread(
            target=read_channel_output,
            args=(process, channel_name),
            daemon=True,
        )
        output_thread.start()

    return processes


def monitor_channels(processes):
    """Monitor all running channel processes."""
    while processes:
        exited_channels = []

        for channel_name, channel in processes.items():
            process = channel["process"]

            if (
                channel["last_restart"] is not None
                and time.monotonic() - channel["last_restart"] >= RESTART_RESET_TIME
            ):
                logger.info(
                    f"Channel '{channel_name}' has been healthy for "
                    f"{RESTART_RESET_TIME} seconds. Resetting restart history."
                )
                channel["restart_count"] = 0
                channel["last_restart"] = None

            if process.poll() is not None:
                exit_code = process.returncode

                if channel["stopping"]:
                    logger.info(
                        f"Channel '{channel_name}' stopped intentionally."
                    )
                    exited_channels.append(channel_name)
                    continue

                logger.warning(
                    f"Channel '{channel_name}' has exited "
                    f"with code {exit_code}."
                )

                if exit_code != 0:
                    if is_restart_loop(channel):
                        logger.error(
                            f"Channel '{channel_name}' is restarting too frequently. "
                            f"Not restarting it again."
                        )
                        exited_channels.append(channel_name)
                        continue

                    config_file = channel["config_file"]
                    new_process = restart_channel(
                        config_file,
                        channel_name,
                        channel
                    )

                    channel["process"] = new_process
                    continue

                exited_channels.append(channel_name)

        for channel_name in exited_channels:
            del processes[channel_name]

        time.sleep(1)


def shutdown_channels(processes):
    """Request a graceful shutdown of all running channels."""
    for channel_name, channel in processes.items():
        process = channel["process"]

        logger.info(f"Stopping channel '{channel_name}'.")

        channel["stopping"] = True
        process.terminate()


# ------------------------------------------------------------------------------
# Main Execution
# ------------------------------------------------------------------------------

def handle_shutdown_signal(signum, frame):
    """Handle a termination signal received by the master."""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name}. Shutting down master.")

    shutdown_channels(processes)


if __name__ == "__main__":
    configure_logging()

    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    logger.info("tvh-radio master starting.")

    channels = load_channel_configs("config")
    processes.update(start_channels(channels))

    monitor_channels(processes)
