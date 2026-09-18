import threading
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

STATION_NAME = "Woolworths Radio"
STATION_LOGO = "https://i.iheart.com/v3/re/new_assets/617f2881bd5039e366ef0289?ops=fit(240%2C240)"
TRACK_META_URL = "https://au.api.iheart.com/api/v3/live-meta/stream/9195/currentTrackMeta"

UPDATE_INTERVAL = 5
IMAGE_DEFINITION = 720
OUTPUT_FILE = Path("now_playing.jpg")
REQUEST_TIMEOUT = 10  # seconds

IMAGE_FILE = OUTPUT_FILE
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 25
VIDEO_BITRATE = 2500
AUDIO_BITRATE = 128000
ICECAST_URL = "http://arn-instore.streamguys1.com/wwr_007"
UDP_HOST = "127.0.0.1"
UDP_PORT = 1234

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
current_mtime = None
station_logo = None


# ------------------------------------------------------------------------------
# IMAGE GENERATION
# ------------------------------------------------------------------------------

def get_station_logo():
    """Fetch the logo once, then reuse it for later images."""
    global station_logo

    if station_logo is not None:
        return station_logo

    try:
        response = requests.get(STATION_LOGO, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        station_logo = Image.open(BytesIO(response.content)).convert("RGBA")
        return station_logo
    except requests.RequestException as error:
        print(f"Error fetching station logo: {error}")
    except Exception as error:
        print(f"Error processing station logo: {error}")

    return None


def get_track_metadata():
    """Return current track metadata, or the existing station fallback."""
    default_data = {
        "title": STATION_NAME,
        "artist": "Clear Channel Australia",
        "album": "iHeartRadio",
        "imagePath": STATION_LOGO,
    }

    try:
        response = requests.get(TRACK_META_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as error:
        print(f"Error fetching track metadata: {error}")
    except ValueError as error:
        print(f"Error parsing track metadata: {error}")

    return default_data


def get_album_artwork(image_url):
    if not image_url:
        return None

    try:
        response = requests.get(image_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGB")
    except requests.RequestException as error:
        print(f"Error fetching album artwork: {error}")
    except Exception as error:
        print(f"Error processing album artwork: {error}")

    return None


def generate_image():
    data = get_track_metadata()
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


def save_image(image):
    """Atomically replace the JPEG so GStreamer never reads a partial file."""
    temporary_file = OUTPUT_FILE.with_suffix(".tmp.jpg")
    image.save(temporary_file, "JPEG", quality=90, optimize=True)
    temporary_file.replace(OUTPUT_FILE)


def run_image_worker(stop_event):
    """Generate images outside the GLib/GStreamer main loop.

    Event.wait() sleeps without busy-waiting and returns immediately at shutdown.
    """
    print(
        f"Now playing image generator started. Output file: {OUTPUT_FILE} - "
        f"Update interval: {UPDATE_INTERVAL} seconds"
    )

    while not stop_event.is_set():
        try:
            image = generate_image()
            save_image(image)
            print(f"Image generated and saved to {OUTPUT_FILE}")
        except Exception as error:
            print(f"Error generating image: {error}")

        stop_event.wait(UPDATE_INTERVAL)

    print("Now playing image generator stopped.")


# ------------------------------------------------------------------------------
# GSTREAMER VIDEO INPUT
# ------------------------------------------------------------------------------

def load_image():
    global current_image, current_mtime

    try:
        mtime = IMAGE_FILE.stat().st_mtime_ns
    except FileNotFoundError:
        if not hasattr(load_image, "_missing_image_reported"):
            print(f"Waiting for image generator: {IMAGE_FILE}")
            load_image._missing_image_reported = True
        return None

    load_image._missing_image_reported = False

    if current_image is not None and mtime == current_mtime:
        return current_image

    try:
        with open(IMAGE_FILE, "rb") as file:
            current_image = file.read()
        current_mtime = mtime
        print(f"Loaded new image: {IMAGE_FILE}")
        return current_image
    except Exception as error:
        print(f"Error reading image: {error}")
        return None


def push_frame():
    image_data = load_image()
    if image_data is None:
        return True

    buffer = Gst.Buffer.new_allocate(None, len(image_data), None)
    if buffer is None:
        print("Unable to allocate GStreamer buffer")
        return False

    buffer.fill(0, image_data)
    result = appsrc.emit("push-buffer", buffer)
    if result != Gst.FlowReturn.OK:
        print(f"Error pushing video frame: {result}")
        return False

    return True


# ------------------------------------------------------------------------------
# GSTREAMER PIPELINE
# ------------------------------------------------------------------------------

def create_pipeline():
    global appsrc

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
    caps = pad.get_current_caps() or pad.query_caps(None)
    media_type = caps.get_structure(0).get_name()
    print(f"New Icecast stream pad: {media_type}")

    if media_type.startswith("audio/"):
        sink_pad = audioconvert.get_static_pad("sink")
        if sink_pad.is_linked():
            print("Audio pad already linked")
            return

        result = pad.link(sink_pad)
        if result != Gst.PadLinkReturn.OK:
            print(f"Unable to link Icecast audio: {result}")
        else:
            print("Icecast audio linked successfully.")


def on_message(bus, message):
    message_type = message.type

    if message_type == Gst.MessageType.ERROR:
        error, debug = message.parse_error()
        print(f"GStreamer error: {error}")
        if debug:
            print(f"Debug information: {debug}")
        main_loop.quit()
    elif message_type == Gst.MessageType.EOS:
        print("GStreamer reached end of stream")
        main_loop.quit()
    elif message_type == Gst.MessageType.WARNING:
        warning, debug = message.parse_warning()
        print(f"GStreamer warning: {warning}")
        if debug:
            print(f"Debug information: {debug}")

    return True


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():
    global main_loop

    print("Starting video/audio streamer")
    print(f"Image:       {IMAGE_FILE}")
    print(f"Resolution:  {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
    print(f"Frame rate:  {VIDEO_FPS} fps")
    print(f"Icecast:     {ICECAST_URL}")
    print(f"UDP Output:  {UDP_HOST}:{UDP_PORT}")

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
        pipeline.set_state(Gst.State.PLAYING)
        source_id = GLib.timeout_add(int(1000 / VIDEO_FPS), push_frame)
        main_loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("Stopping streamer...")
        stop_event.set()

        if source_id is not None:
            GLib.source_remove(source_id)

        if appsrc is not None:
            appsrc.emit("end-of-stream")

        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)

        # A request may still be within REQUEST_TIMEOUT, so wait for it to finish.
        image_worker.join()
        print("Streamer stopped.")


if __name__ == "__main__":
    main()
