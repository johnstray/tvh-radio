import argparse
import json
import logging
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


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
# Master Configuration Management
# ------------------------------------------------------------------------------

def load_master_config(config_file):
    """Load the master configuration from a JSON file."""
    with open(config_file, "r", encoding="utf-8") as file:
        return json.load(file)


def validate_master_config(config):
    """Validate the required master configuration values."""
    if "playlist" not in config:
        raise ValueError(
            "Missing required configuration section: playlist"
        )

    playlist_config = config["playlist"]

    if not isinstance(playlist_config, dict):
        raise TypeError(
            "playlist configuration must be an object"
        )

    required_keys = [
        "output",
        "starting_channel_number",
    ]

    for key in required_keys:
        if key not in playlist_config:
            raise ValueError(
                f"Missing required playlist configuration value: {key}"
            )

    if not isinstance(playlist_config["output"], str):
        raise TypeError(
            "playlist output must be a string"
        )

    if not playlist_config["output"].strip():
        raise ValueError(
            "playlist output must not be empty"
        )

    if (
        not isinstance(playlist_config["starting_channel_number"], int)
        or isinstance(playlist_config["starting_channel_number"], bool)
    ):
        raise TypeError(
            "starting_channel_number must be an integer"
        )

    if playlist_config["starting_channel_number"] < 1:
        raise ValueError(
            "starting_channel_number must be greater than 0"
        )

    if "restart" not in config:
        raise ValueError(
            "Missing required configuration section: restart"
        )

    restart_config = config["restart"]

    required_restart_keys = [
        "limit",
        "window",
        "reset_time",
        "backoff_time",
    ]

    for key in required_restart_keys:
        if key not in restart_config:
            raise ValueError(
                f"Missing required restart configuration value: {key}"
            )

    for key in required_restart_keys:
        value = restart_config[key]

        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(
                f"restart {key} must be an integer"
            )

        if value < 1:
            raise ValueError(
                f"restart {key} must be greater than 0"
            )

    udp_config = config.get("udp")

    if not isinstance(udp_config, dict):
        raise ValueError("Master config 'udp' section is required")

    for key in ("port_start", "port_end"):
        value = udp_config.get(key)

        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= 65535
        ):
            raise ValueError(
                f"Master config 'udp.{key}' must be an integer between 1 and 65535"
            )

    if udp_config["port_start"] > udp_config["port_end"]:
        raise ValueError(
            "Master config 'udp.port_start' must not be greater than 'udp.port_end'"
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

    if not isinstance(config["fallback_metadata"], dict):
        raise TypeError(
            "fallback_metadata configuration must be an object"
        )

    for key in fallback_keys:
        if key not in config["fallback_metadata"]:
            raise ValueError(f"Missing required fallback metadata value: {key}")

    if "channel_number" in config:
        if (
            not isinstance(config["channel_number"], int)
            or isinstance(config["channel_number"], bool)
        ):
            raise TypeError("channel_number must be an integer")

        if config["channel_number"] < 1:
            raise ValueError("channel_number must be greater than 0")

    if (
        "udp_port" in config
        and (
            not isinstance(config["udp_port"], int)
            or isinstance(config["udp_port"], bool)
            or not 1 <= config["udp_port"] <= 65535
        )
    ):
        raise TypeError(
            "udp_port must be an integer between 1 and 65535"
        )

    if "tvh_tags" in config:
        if not isinstance(config["tvh_tags"], list):
            raise ValueError("tvh_tags must be a list")

        if not all(isinstance(tag, str) for tag in config["tvh_tags"]):
            raise ValueError("tvh_tags must contain only strings")

    if "stream" not in config:
        raise ValueError(
            "Missing required configuration section: stream"
        )

    stream_config = config["stream"]

    if not isinstance(stream_config, dict):
        raise TypeError(
            "stream configuration must be an object"
        )

    stream_keys = [
        "update_interval",
        "metadata_empty_threshold",
        "image_definition",
        "request_timeout",
        "station_logo_retry_interval",
        "video_fps",
        "video_bitrate",
        "audio_bitrate",
    ]

    for key in stream_keys:
        if key not in stream_config:
            raise ValueError(
                f"Missing required stream configuration value: {key}"
            )

        value = stream_config[key]

        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(
                f"stream {key} must be an integer"
            )

        if value < 1:
            raise ValueError(
                f"stream {key} must be greater than 0"
            )


def load_channel_configs(config_directory):
    """Find, load, and validate all channel configurations."""
    config_files = find_channel_configs(config_directory)
    channels = []

    for config_file in config_files:
        try:
            config = load_channel_config(config_file)
            validate_channel_config(config)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(
                f"{config_file}: {error}"
            ) from error

        channels.append((config_file, config))

    return channels


def validate_channel_numbers(channels):
    """Validate that configured channel numbers are unique."""
    channel_numbers = {}

    for config_file, channel in channels:
        if "channel_number" not in channel:
            continue

        channel_number = channel["channel_number"]

        if channel_number in channel_numbers:
            previous_channel = channel_numbers[channel_number]

            raise ValueError(
                f"Duplicate channel number {channel_number} "
                f"configured for '{previous_channel}' and "
                f"'{channel['channel_name']}'"
            )

        channel_numbers[channel_number] = channel["channel_name"]


def validate_udp_ports(channels, udp_config):
    """Validate UDP port assignments without modifying configuration files."""

    used_ports = set()

    for config_file, config in channels:
        if "udp_port" in config:
            port = config["udp_port"]

            if port in used_ports:
                raise ValueError(
                    f"Duplicate UDP port {port} assigned to multiple channels"
                )

            used_ports.add(port)

    port_start = udp_config["port_start"]
    port_end = udp_config["port_end"]

    available_ports = [
        port
        for port in range(port_start, port_end + 1)
        if port not in used_ports
    ]

    missing_ports = sum(
        1
        for config_file, config in channels
        if "udp_port" not in config
    )

    if missing_ports > len(available_ports):
        raise ValueError(
            f"No available UDP ports for {missing_ports} channel(s) "
            f"in configured range {port_start}-{port_end}"
        )


def validate_configuration(master_config_file, channel_config_directory):
    """Load and validate the complete configuration without starting channels."""

    master_config = load_master_config(master_config_file)
    validate_master_config(master_config)

    channels = load_channel_configs(channel_config_directory)
    validate_channel_numbers(channels)
    validate_udp_ports(channels, master_config["udp"])

    return master_config, channels


def assign_udp_ports(channels, udp_config):
    """Assign and persist UDP ports for channels without an explicit port."""

    used_ports = set()
    assigned_ports = []

    # Reserve explicitly assigned ports first.
    for config_file, config in channels:
        if "udp_port" in config:
            port = config["udp_port"]

            if port in used_ports:
                raise ValueError(
                    f"Duplicate UDP port {port} assigned to multiple channels"
                )

            used_ports.add(port)

    port_start = udp_config["port_start"]
    port_end = udp_config["port_end"]

    next_port = port_start

    for config_file, config in channels:
        if "udp_port" in config:
            continue

        while next_port <= port_end and next_port in used_ports:
            next_port += 1

        if next_port > port_end:
            raise ValueError(
                f"No available UDP ports in configured range "
                f"{port_start}-{port_end}"
            )

        config["udp_port"] = next_port
        used_ports.add(next_port)

        assigned_ports.append((config_file, config))

        next_port += 1

    for config_file, config in assigned_ports:
        save_channel_config(config_file, config)


def save_channel_config(config_file, config):
    """Write a channel configuration atomically."""

    temp_file = config_file.with_suffix(".json.tmp")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(config, file, indent=4)
        file.write("\n")

    temp_file.replace(config_file)


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


def is_restart_loop(channel, restart_config):
    """Return True if a channel is restarting too frequently."""
    if channel["last_restart"] is None:
        return False

    elapsed = time.monotonic() - channel["last_restart"]

    return (
        channel["restart_count"] >= restart_config["limit"]
        and elapsed <= restart_config["window"]
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

    start_channel(channel)

    logger.info(
        f"Channel '{channel['channel_name']}' restarted with PID "
        f"{channel['process'].pid}."
    )


def read_channel_output(channel):
    """Read and log output from a channel process."""
    for line in channel["process"].stdout:
        print(line, end="", flush=True)


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

        start_channel(channel_state)

        logger.info(
            f"Channel '{channel_name}' started with PID {channel_state['process'].pid}."
        )

        processes[channel_name] = channel_state

    return processes


def monitor_channels(processes, restart_config):
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
                and time.monotonic() - channel["last_restart"] >= restart_config["reset_time"]
            ):
                logger.info(
                    f"Channel '{channel['channel_name']}' has been healthy for "
                    f"{restart_config["reset_time"]} seconds. Resetting restart history."
                )
                channel["restart_count"] = 0
                channel["last_restart"] = None

            if process.poll() is not None:
                exit_code = process.returncode

                if channel["stopping"]:
                    logger.info(
                        f"Channel '{channel['channel_name']}' stopped intentionally."
                    )

                    if not shutdown_requested:
                        channels_to_remove.append(channel["channel_name"])

                    continue

                logger.warning(
                    f"Channel '{channel['channel_name']}' has exited "
                    f"with code {exit_code}."
                )

                if exit_code != 0:
                    if is_restart_loop(channel, restart_config):
                        channel["state"] = "backoff"
                        channel["next_restart"] = (
                            time.monotonic() + restart_config["backoff_time"]
                        )

                        logger.error(
                            f"Channel '{channel['channel_name']}' is restarting too frequently. "
                            f"Entering backoff for {restart_config["backoff_time"]} seconds."
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


def wait_for_channels(processes):
    """Wait for all channel processes to exit."""
    for channel in processes.values():
        process = channel["process"]

        logger.info(
            f"Waiting for channel '{channel['channel_name']}' to stop."
        )

        process.wait()

        logger.info(
            f"Channel '{channel['channel_name']}' stopped."
        )


# ------------------------------------------------------------------------------
# Playlist Generation
# ------------------------------------------------------------------------------

def generate_playlist(channels, master_config):
    """Generate an M3U8 playlist from the configured channels."""
    playlist_config = master_config["playlist"]
    next_channel_number = playlist_config["starting_channel_number"]

    explicit_channel_numbers = {
        channel["channel_number"]
        for config_file, channel in channels
        if "channel_number" in channel
    }

    playlist_lines = [
        "#EXTM3U"
    ]

    for config_file, channel in channels:
        if "channel_number" in channel:
            channel_number = channel["channel_number"]
        else:
            while next_channel_number in explicit_channel_numbers:
                next_channel_number += 1

            channel_number = next_channel_number
            next_channel_number += 1

        tvh_tags = channel.get("tvh_tags", [])
        tvh_tags_value = ",".join(tvh_tags)

        if tvh_tags_value:
            tvh_tags_attribute = f' tvh-tags="{tvh_tags_value}"'
        else:
            tvh_tags_attribute = ""

        playlist_lines.append(
            f'#EXTINF:-1 tvg-name="{channel["station_name"]}" '
            f'tvg-id="{channel["channel_name"]}" '
            f'tvg-logo="{channel["station_logo"]}" '
            f'tvg-chno="{channel_number}"'
            f'{tvh_tags_attribute},'
            f'{channel["station_name"]}'
        )

        playlist_lines.append(
            f'udp://{channel["udp_host"]}:{channel["udp_port"]}'
        )

    return "\n".join(playlist_lines) + "\n"


def write_playlist(playlist, master_config):
    """Write the generated playlist to the configured output file."""
    output_file = master_config["playlist"]["output"]

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(playlist)


def remove_playlist(master_config):
    """Remove the generated playlist file."""
    output_file = master_config["playlist"]["output"]

    try:
        Path(output_file).unlink()
    except FileNotFoundError:
        pass


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


def parse_arguments():
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="TVHeadend Radio master process"
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate configuration without starting channels",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    configure_logging()

    if args.validate:
        logger.info("Validating configuration...")

        try:
            master_config, channels = validate_configuration(
                "config.json",
                "channels",
            )

        except (OSError, json.JSONDecodeError, ValueError) as error:
            logger.error(f"Configuration error: {error}")
            sys.exit(1)

        logger.info("Master configuration: OK")
        logger.info(f"Channel configurations: {len(channels)} found")
        logger.info("UDP configuration: OK")
        logger.info("Configuration is valid.")

        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    logger.info("tvh-radio master starting.")

    try:
        master_config = load_master_config("config.json")
        validate_master_config(master_config)

        channels = load_channel_configs("channels")
        validate_channel_numbers(channels)

        assign_udp_ports(channels, master_config["udp"],)

    except (OSError, json.JSONDecodeError, ValueError) as error:
        logger.error(f"Configuration error: {error}")
        sys.exit(1)

    playlist = generate_playlist(channels, master_config)
    write_playlist(playlist, master_config)

    processes.update(start_channels(channels))
    monitor_channels(processes, master_config["restart"])

    wait_for_channels(processes)
    remove_playlist(master_config)
