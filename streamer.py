import json
import logging
import signal
import sys
import threading
import time
from io import BytesIO
from pathlib import Path

import gi
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")

from gi.repository import GLib, Gst, GstApp


# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------

UPDATE_INTERVAL = 5
METADATA_EMPTY_THRESHOLD = 3  # number of consecutive empty metadata responses before using fallback
IMAGE_DEFINITION = 720
REQUEST_TIMEOUT = 10  # seconds
STATION_LOGO_RETRY_INTERVAL = 300  # seconds

VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 25
VIDEO_BITRATE = 2500
AUDIO_BITRATE = 128000
ICECAST_URL = "http://arn-instore.streamguys1.com/wwr_007"
UDP_HOST = "127.0.0.1"
UDP_PORT = 1234

logger = logging.getLogger("tvh-radio")

def configure_logging():
    """Configure application logging for console/systemd output."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_config(config_file):
    try:
        with open(config_file, "r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError:
        raise RuntimeError(f"Configuration file not found: {config_file}")
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid JSON in configuration file: {error}")

    required_keys = [
        "channel_name",
        "station_name",
        "station_logo",
        "fallback_station_logo",
        "track_meta_url",
        "icecast_url",
        "udp_host",
        "udp_port",
        "fallback_metadata"
    ]

    for key in required_keys:
        if key not in config:
            raise RuntimeError(
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
            raise RuntimeError(
                f"Missing required fallback metadata value: {key}"
            )

    return config

# Base definitions for image dimensions based on a 16:9 aspect ratio.
BASE_DEFINITION = 720
ART_SIZE_BASE = 150
FONT_SIZE_TITLE_BASE = 36
FONT_SIZE_SUB_BASE = 20
SCALE = IMAGE_DEFINITION / BASE_DEFINITION


# ------------------------------------------------------------------------------
# FONTS
# ------------------------------------------------------------------------------

FONT_SIZE_TITLE = int(FONT_SIZE_TITLE_BASE * SCALE)
FONT_SIZE_SUB = int(FONT_SIZE_SUB_BASE * SCALE)

try:
    FONT_TITLE = ImageFont.truetype(
        "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf",
        FONT_SIZE_TITLE,
    )
    FONT_SUB = ImageFont.truetype(
        "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf",
        FONT_SIZE_SUB,
    )
except IOError:
    FONT_TITLE = ImageFont.load_default()
    FONT_SUB = ImageFont.load_default()


# ------------------------------------------------------------------------------
# GLOBAL STATE
# ------------------------------------------------------------------------------

Gst.init(None)

appsrc = None
main_loop = None
current_image = None
image_lock = threading.Lock()
station_logo = None
station_logo_source = None
station_logo_retry_time = 0
fallback_metadata = None
config_directory = None

pipeline = None
icecast_source = None
audio_convert = None
audio_failed = False
audio_reconnecting = False
reconnect_source_id = None

# ------------------------------------------------------------------------------
# IMAGE GENERATION
# ------------------------------------------------------------------------------

def resolve_local_path(path):
    """Resolve a configured local path relative to the configuration file."""
    path = Path(path)

    if path.is_absolute():
        return path

    return config_directory / path


def get_station_logo():
    """Load and cache the station logo, retrying the primary source periodically."""
    global station_logo
    global station_logo_source
    global station_logo_retry_time

    now = time.monotonic()

    if station_logo is not None and station_logo_source == "primary":
        return station_logo

    if (
        station_logo is not None
        and now < station_logo_retry_time
    ):
        return station_logo

    if STATION_LOGO.startswith(("http://", "https://")):
        try:
            response = requests.get(STATION_LOGO, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            station_logo = Image.open(
                BytesIO(response.content)
            ).convert("RGBA")

            if station_logo_source != "primary":
                logger.info("Primary station logo fetched successfully.")

            station_logo_source = "primary"
            station_logo_retry_time = 0

            return station_logo

        except requests.RequestException as error:
            logger.warning(f"Error fetching station logo: {error}")

        except Exception as error:
            logger.warning(f"Error processing station logo: {error}")

    else:
        local_path = resolve_local_path(STATION_LOGO)

        try:
            station_logo = Image.open(local_path).convert("RGBA")
            station_logo_source = "primary"
            station_logo_retry_time = 0

            return station_logo

        except FileNotFoundError:
            logger.warning(f"Station logo file not found: {local_path}")

        except Exception as error:
            logger.warning(f"Error processing local station logo: {error}")

    fallback_logo_path = resolve_local_path(FALLBACK_STATION_LOGO)

    try:
        station_logo = Image.open(fallback_logo_path).convert("RGBA")
        station_logo_source = "fallback"
        station_logo_retry_time = now + STATION_LOGO_RETRY_INTERVAL

        return station_logo

    except FileNotFoundError:
        logger.warning(f"Fallback station logo file not found: {fallback_logo_path}")

    except Exception as error:
        logger.warning(f"Error processing fallback station logo: {error}")

    generic_logo_path = (
        Path(__file__).resolve().parent / "images" / "station_logo.png"
    )

    try:
        station_logo = Image.open(generic_logo_path).convert("RGBA")
        station_logo_source = "generic"
        station_logo_retry_time = now + STATION_LOGO_RETRY_INTERVAL

        return station_logo

    except Exception as error:
        logger.error(f"Error processing generic station logo: {error}")

    return None


def get_track_metadata():
    try:
        response = requests.get(TRACK_META_URL, timeout=REQUEST_TIMEOUT)

        if response.status_code == 204:
            return None, "empty"

        response.raise_for_status()

        return response.json(), "success"

    except requests.RequestException as error:
        logger.error(f"Error fetching track metadata: {error}")
        return None, "error"

    except ValueError as error:
        logger.error(f"Error parsing track metadata JSON: {error}")
        return None, "error"


def get_album_artwork(image_path):
    if not image_path:
        return None

    if image_path.startswith(("http://", "https://")):
        try:
            response = requests.get(image_path, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return Image.open(
                BytesIO(response.content)
            ).convert("RGB")
        except requests.RequestException as error:
            logger.error(f"Error fetching album artwork: {error}")
        except Exception as error:
            logger.error(f"Error processing album artwork: {error}")

    else:
        local_path = resolve_local_path(image_path)

        try:
            return Image.open(local_path).convert("RGB")
        except FileNotFoundError:
            logger.warning(f"Album artwork file not found: {local_path}")
        except Exception as error:
            logger.warning(f"Error processing local album artwork: {error}")

    generic_artwork_path = (
        Path(__file__).resolve().parent / "images" / "album_cover.png"
    )

    try:
        return Image.open(generic_artwork_path).convert("RGB")
    except Exception as error:
        logger.error(f"Error processing generic album artwork: {error}")

    return None

def get_track_identity(data):
    """Return a unique identifier for the track based on its metadata."""
    return f"{data.get('title', '')}-{data.get('artist', '')}-{data.get('album', '')}-{data.get('imagePath', '')}"

def generate_image(data):
    img_width = IMAGE_DEFINITION * 16 // 9
    img_height = IMAGE_DEFINITION

    image = Image.new("RGB", (img_width, img_height), color="#18181b")
    draw = ImageDraw.Draw(image)

    art_size = int(ART_SIZE_BASE * SCALE)
    art_x = int(50 * SCALE)
    art_y = img_height - art_size - int(50 * SCALE)
    draw.rectangle(
        [art_x, art_y, art_x + art_size, art_y + art_size],
        fill="#3f3f46",
    )

    album_artwork = get_album_artwork(data.get("imagePath"))
    if album_artwork is not None:
        background = album_artwork.filter(ImageFilter.GaussianBlur(radius=64))
        background = background.resize((img_width, img_width))
        background = ImageEnhance.Brightness(background).enhance(0.6)
        image.paste(background, (0, -(img_width - img_height) // 2))

        album_cover = album_artwork.resize((art_size, art_size))
        image.paste(album_cover, (art_x, art_y))

    text_block_height = FONT_SIZE_TITLE + FONT_SIZE_SUB * 2 + 20
    text_x = art_size + int(70 * SCALE)
    text_y = art_y + (art_size - text_block_height) // 2

    draw.text((text_x, text_y), data["title"], fill="#ffffff", font=FONT_TITLE)
    draw.text(
        (text_x, text_y + FONT_SIZE_TITLE + 10),
        data["artist"],
        fill="#a1a1aa",
        font=FONT_SUB,
    )
    draw.text(
        (text_x, text_y + FONT_SIZE_TITLE + FONT_SIZE_SUB + 20),
        data["album"],
        fill="#71717a",
        font=FONT_SUB,
    )

    logo_size = 50
    logo = get_station_logo()
    if logo is not None:
        logo = logo.resize((logo_size, logo_size))
        image.paste(logo, (50, 50), logo)

    draw.text(
        (50 + logo_size + 20, 50 + logo_size // 2 - FONT_SIZE_SUB // 2),
        STATION_NAME,
        fill="#a1a1aa",
        font=FONT_SUB,
    )
    return image

def encode_image(image):
    """Encode the PIL image to JPEG bytes."""
    output = BytesIO()
    image.save(output, format="JPEG", quality=85)
    return output.getvalue()


def run_image_worker(stop_event):
    """Generate images outside the GLib/GStreamer main loop.

    Event.wait() sleeps without busy-waiting and returns immediately at shutdown.
    """
    global current_image

    previous_track = None
    metadata_empty_count = 0
    fallback_active = False
    metadata_error_active = False

    logger.info(
        f"Now playing image generator started. - "
        f"Update interval: {UPDATE_INTERVAL} seconds"
    )

    while not stop_event.is_set():
        try:
            data, result = get_track_metadata()

            if result == "success":
                metadata_empty_count = 0

                if metadata_error_active:
                    logger.info("Metadata API recovered.")
                    metadata_error_active = False

                track_identity = get_track_identity(data)

                if track_identity != previous_track:
                    logger.info("Track metadata changed. Generating new image.")
                    logger.info(f"Track: {data.get('title')} - {data.get('artist')} - {data.get('album')}")

                    image = generate_image(data)
                    jpeg_data = encode_image(image)

                    with image_lock:
                        current_image = jpeg_data

                    previous_track = track_identity
                    fallback_active = False

                    logger.info(
                        f"Image generated and stored in memory. "
                        f"Size: {len(jpeg_data)} bytes"
                    )

            elif result == "empty":
                if not fallback_active:
                    metadata_empty_count += 1

                    logger.warning(
                        f"Metadata API returned HTTP 204 "
                        f"({metadata_empty_count}/{METADATA_EMPTY_THRESHOLD})"
                    )

                    if metadata_empty_count >= METADATA_EMPTY_THRESHOLD:
                        fallback_data = {
                            "title": fallback_metadata["title"],
                            "artist": fallback_metadata["artist"],
                            "album": fallback_metadata["album"],
                            "imagePath": fallback_metadata["image_path"],
                        }

                        fallback_identity = get_track_identity(fallback_data)

                        if fallback_identity != previous_track:
                            logger.warning("Metadata unavailable. Generating fallback image.")

                            image = generate_image(fallback_data)
                            jpeg_data = encode_image(image)

                            with image_lock:
                                current_image = jpeg_data

                            previous_track = fallback_identity

                            logger.info(
                                f"Fallback image generated and stored in memory. "
                                f"Size: {len(jpeg_data)} bytes"
                            )

                        fallback_active = True

            else:
                metadata_empty_count = 0

                if not metadata_error_active:
                    logger.error("Metadata API unavailable. Using fallback metadata.")
                    metadata_error_active = True

                fallback_data = {
                    "title": fallback_metadata["title"],
                    "artist": fallback_metadata["artist"],
                    "album": fallback_metadata["album"],
                    "imagePath": fallback_metadata["image_path"],
                }

                fallback_identity = get_track_identity(fallback_data)

                if fallback_identity != previous_track:
                    logger.warning("Generating fallback image.")

                    image = generate_image(fallback_data)
                    jpeg_data = encode_image(image)

                    with image_lock:
                        current_image = jpeg_data

                    previous_track = fallback_identity

                    logger.info(
                        f"Fallback image generated and stored in memory. "
                        f"Size: {len(jpeg_data)} bytes"
                    )

                fallback_active = True

        except Exception as error:
            logger.error(f"Error generating image: {error}")

        stop_event.wait(UPDATE_INTERVAL)

    logger.info("Now playing image generator stopped.")


# ------------------------------------------------------------------------------
# GSTREAMER VIDEO INPUT
# ------------------------------------------------------------------------------


def push_frame():
    with image_lock:
        image_data = current_image

    if image_data is None:
        return True

    buffer = Gst.Buffer.new_allocate(None, len(image_data), None)
    if buffer is None:
        logger.error("Unable to allocate GStreamer buffer")
        return False

    buffer.fill(0, image_data)
    result = appsrc.emit("push-buffer", buffer)

    if result != Gst.FlowReturn.OK:
        logger.error(f"Error pushing video frame: {result}")
        return False

    return True


# ------------------------------------------------------------------------------
# GSTREAMER PIPELINE
# ------------------------------------------------------------------------------

def create_pipeline():
    global appsrc
    global icecast_source
    global audio_convert

    pipeline = Gst.Pipeline.new("stream-pipeline")

    appsrc = Gst.ElementFactory.make("appsrc", "image-source")
    jpegdec = Gst.ElementFactory.make("jpegdec", "jpeg-decoder")
    videoconvert = Gst.ElementFactory.make("videoconvert", "video-convert")
    videoscale = Gst.ElementFactory.make("videoscale", "video-scale")
    videocaps = Gst.ElementFactory.make("capsfilter", "video-caps")
    x264enc = Gst.ElementFactory.make("x264enc", "h264-encoder")
    h264parse = Gst.ElementFactory.make("h264parse", "h264-parser")

    source = Gst.ElementFactory.make("uridecodebin3", "icecast-source")
    audio_queue = Gst.ElementFactory.make("queue", "audio_queue")
    audioconvert = Gst.ElementFactory.make("audioconvert", "audio-convert")
    audioresample = Gst.ElementFactory.make("audioresample", "audio-resample")
    audiocaps = Gst.ElementFactory.make("capsfilter", "audio-caps")
    avenc_aac = Gst.ElementFactory.make("avenc_aac", "aac-encoder")
    aacparse = Gst.ElementFactory.make("aacparse", "aac-parser")

    mpegtsmux = Gst.ElementFactory.make("mpegtsmux", "mpegts-mux")
    udpsink = Gst.ElementFactory.make("udpsink", "udp-sink")

    elements = [
        appsrc, jpegdec, videoconvert, videoscale, videocaps, x264enc, h264parse,
        source, audio_queue, audioconvert, audioresample, audiocaps, avenc_aac,
        aacparse, mpegtsmux, udpsink,
    ]
    if any(element is None for element in elements):
        raise RuntimeError("Unable to create one or more GStreamer elements")

    icecast_source = source
    audio_convert = audioconvert

    appsrc.set_property("format", Gst.Format.TIME)
    appsrc.set_property("is-live", True)
    appsrc.set_property("block", True)
    appsrc.set_property("do-timestamp", True)
    appsrc.set_property(
        "caps", Gst.Caps.from_string(f"image/jpeg,framerate={VIDEO_FPS}/1")
    )

    videocaps.set_property(
        "caps",
        Gst.Caps.from_string(
            f"video/x-raw,width={VIDEO_WIDTH},height={VIDEO_HEIGHT},"
            f"framerate={VIDEO_FPS}/1"
        ),
    )
    x264enc.set_property("tune", "zerolatency")
    x264enc.set_property("speed-preset", "veryfast")
    x264enc.set_property("bitrate", VIDEO_BITRATE)
    x264enc.set_property("key-int-max", VIDEO_FPS)
    x264enc.set_property("byte-stream", True)
    h264parse.set_property("config-interval", -1)

    source.set_property("uri", ICECAST_URL)
    source.connect("pad-added", on_audio_pad_added, audioconvert)
    audio_queue.set_property("max-size-time", 2 * Gst.SECOND)
    audio_queue.set_property("max-size-bytes", 0)
    audio_queue.set_property("max-size-buffers", 0)
    audiocaps.set_property(
        "caps", Gst.Caps.from_string("audio/x-raw,rate=48000,channels=2")
    )
    avenc_aac.set_property("bitrate", AUDIO_BITRATE)

    mpegtsmux.set_property("alignment", 7)
    mpegtsmux.set_property("pat-interval", 9000)
    mpegtsmux.set_property("pmt-interval", 9000)
    mpegtsmux.set_property("pcr-interval", 3600)
    udpsink.set_property("host", UDP_HOST)
    udpsink.set_property("port", UDP_PORT)
    udpsink.set_property("sync", False)
    udpsink.set_property("async", False)

    for element in elements:
        pipeline.add(element)

    video_links = [
        (appsrc, jpegdec), (jpegdec, videoconvert),
        (videoconvert, videoscale), (videoscale, videocaps),
        (videocaps, x264enc), (x264enc, h264parse),
        (h264parse, mpegtsmux),
    ]
    audio_links = [
        (audioconvert, audio_queue), (audio_queue, audioresample),
        (audioresample, audiocaps), (audiocaps, avenc_aac),
        (avenc_aac, aacparse), (aacparse, mpegtsmux),
    ]
    for source_element, sink_element in video_links + audio_links:
        if not source_element.link(sink_element):
            raise RuntimeError(
                f"Unable to link {source_element.get_name()} -> "
                f"{sink_element.get_name()}"
            )

    if not mpegtsmux.link(udpsink):
        raise RuntimeError("Unable to link mpegtsmux -> udpsink")

    return pipeline


def on_audio_pad_added(decodebin, pad, audioconvert):
    global audio_failed
    global audio_reconnecting

    caps = pad.get_current_caps() or pad.query_caps(None)
    media_type = caps.get_structure(0).get_name()
    logger.info(f"New Icecast stream pad: {media_type}")

    if media_type.startswith("audio/"):
        sink_pad = audioconvert.get_static_pad("sink")
        if sink_pad.is_linked():
            logger.debug("Audio pad already linked")
            return

        result = pad.link(sink_pad)
        if result != Gst.PadLinkReturn.OK:
            logger.error(f"Unable to link Icecast audio: {result}")
        else:
            logger.info("Icecast audio linked successfully.")

            if audio_failed:
                logger.info("Icecast audio connection restored.")

            audio_failed = False
            audio_reconnecting = False


def reconnect_audio_source():
    global icecast_source
    global audio_failed
    global audio_reconnecting
    global reconnect_source_id

    logger.info("Attempting to reconnect Icecast audio source...")
    audio_reconnecting = True

    old_source = icecast_source

    if old_source is not None:
        logger.info("Removing failed Icecast source...")

        old_source.set_state(Gst.State.NULL)
        pipeline.remove(old_source)

    new_source = Gst.ElementFactory.make(
        "uridecodebin3",
        "icecast-source",
    )

    if new_source is None:
        logger.error("Unable to create new Icecast source.")
        audio_reconnecting = False
        reconnect_source_id = None
        return False

    new_source.set_property("uri", ICECAST_URL)
    new_source.connect(
        "pad-added",
        on_audio_pad_added,
        audio_convert,
    )

    pipeline.add(new_source)

    icecast_source = new_source

    new_source.sync_state_with_parent()

    logger.info("New Icecast source started.")

    audio_reconnecting = False

    reconnect_source_id = None

    return False


def on_message(bus, message):
    global audio_failed
    global audio_reconnecting
    global reconnect_source_id

    message_type = message.type

    if message_type == Gst.MessageType.ERROR:
        error, debug = message.parse_error()

        source = message.src
        source_name = source.get_name() if source is not None else "unknown"

        logger.error(f"GStreamer error from {source_name}: {error}")

        if debug:
            logger.debug(f"Debug information: {debug}")

        icecast_source_element = pipeline.get_by_name("icecast-source")
        is_audio_source_error = False

        if icecast_source_element is not None and source is not None:
            current = source

            while current is not None:
                if current == icecast_source_element:
                    is_audio_source_error = True
                    break

                current = current.get_parent()

        if is_audio_source_error:
            if not audio_failed:
                logger.warning(
                    "Icecast audio source failed. "
                    "Video will continue running."
                )

            audio_failed = True

            if reconnect_source_id is None and not audio_reconnecting:
                logger.info("Scheduling Icecast audio reconnect in 5 seconds.")

                reconnect_source_id = GLib.timeout_add_seconds(
                    5,
                    reconnect_audio_source,
                )
        else:
            main_loop.quit()

    elif message_type == Gst.MessageType.EOS:
        source = message.src
        source_name = source.get_name() if source is not None else "unknown"

        logger.info(f"GStreamer reached end of stream from {source_name}")

        icecast_source_element = pipeline.get_by_name("icecast-source")
        is_audio_source_eos = False

        if icecast_source_element is not None and source is not None:
            current = source

            while current is not None:
                if current == icecast_source_element:
                    is_audio_source_eos = True
                    break

                current = current.get_parent()

        if is_audio_source_eos:
            if not audio_failed:
                logger.warning(
                    "Icecast audio source reached end of stream. "
                    "Video will continue running."
                )

            audio_failed = True

            if reconnect_source_id is None and not audio_reconnecting:
                logger.info("Scheduling Icecast audio reconnect in 5 seconds.")

                reconnect_source_id = GLib.timeout_add_seconds(
                    5,
                    reconnect_audio_source,
                )
        else:
            main_loop.quit()

    elif message_type == Gst.MessageType.WARNING:
        warning, debug = message.parse_warning()
        logger.warning(f"GStreamer warning: {warning}")

        if debug:
            logger.debug(f"Debug information: {debug}")

    return True


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def handle_shutdown_signal(signum, frame):
    """Request a clean shutdown when the process receives a termination signal."""
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name}. Shutting down streamer...")

    if main_loop is not None:
        main_loop.quit()


def main():
    global main_loop
    global pipeline
    global CHANNEL_NAME
    global STATION_NAME
    global STATION_LOGO
    global FALLBACK_STATION_LOGO
    global TRACK_META_URL
    global ICECAST_URL
    global UDP_HOST
    global UDP_PORT
    global fallback_metadata
    global config_directory

    if len(sys.argv) != 2:
        print("Usage: python3 streamer.py <config-file>")
        sys.exit(1)

    configure_logging()

    config_file = Path(sys.argv[1])
    config = load_config(config_file)
    config_directory = config_file.resolve().parent

    CHANNEL_NAME = config["channel_name"]
    STATION_NAME = config["station_name"]
    STATION_LOGO = config["station_logo"]
    FALLBACK_STATION_LOGO = config["fallback_station_logo"]
    TRACK_META_URL = config["track_meta_url"]
    ICECAST_URL = config["icecast_url"]
    UDP_HOST = config["udp_host"]
    UDP_PORT = config["udp_port"]
    fallback_metadata = config["fallback_metadata"]

    logger.info("Starting video/audio streamer")
    logger.info(f"Configuration: {config_file}")
    logger.info(f"Channel:       {CHANNEL_NAME}")
    logger.info(f"Station:       {STATION_NAME}")
    logger.info(f"Resolution:    {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
    logger.info(f"Frame rate:    {VIDEO_FPS} fps")
    logger.info(f"Icecast:       {ICECAST_URL}")
    logger.info(f"UDP Output:    {UDP_HOST}:{UDP_PORT}")

    stop_event = threading.Event()
    image_worker = threading.Thread(
        target=run_image_worker,
        args=(stop_event,),
        name="image-generator",
    )
    pipeline = None
    source_id = None

    try:
        # Start the worker before the pipeline so it can create the first JPEG.
        image_worker.start()

        pipeline = create_pipeline()
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_message)

        main_loop = GLib.MainLoop()
        signal.signal(signal.SIGINT, handle_shutdown_signal)
        signal.signal(signal.SIGTERM, handle_shutdown_signal)
        pipeline.set_state(Gst.State.PLAYING)
        source_id = GLib.timeout_add(int(1000 / VIDEO_FPS), push_frame)
        main_loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Stopping streamer...")
        stop_event.set()

        if source_id is not None:
            GLib.source_remove(source_id)

        if reconnect_source_id is not None:
            GLib.source_remove(reconnect_source_id)

        if appsrc is not None:
            appsrc.emit("end-of-stream")

        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)

        # A request may still be within REQUEST_TIMEOUT, so wait for it to finish.
        image_worker.join()
        logger.info("Streamer stopped.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        logger.error(f"Runtime error: {error}")
        sys.exit(1)
