import sys
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")

from gi.repository import Gst, GstApp, GLib


# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------

IMAGE_FILE = Path("now_playing.jpg")

VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 25

VIDEO_BITRATE = 2500

AUDIO_BITRATE = 128000

ICECAST_URL = "http://arn-instore.streamguys1.com/wwr_007"

UDP_HOST = "127.0.0.1"
UDP_PORT = 1234


# ------------------------------------------------------------------------------
# INITIALISE GSTREAMER
# ------------------------------------------------------------------------------

Gst.init(None)


# ------------------------------------------------------------------------------
# GLOBAL STATE
# ------------------------------------------------------------------------------

appsrc = None
main_loop = None

current_image = None
current_mtime = None


# ------------------------------------------------------------------------------
# LOAD IMAGE
# ------------------------------------------------------------------------------

def load_image():

    global current_image
    global current_mtime

    try:
        mtime = IMAGE_FILE.stat().st_mtime_ns

    except FileNotFoundError:
        print(f"Image file not found: {IMAGE_FILE}")
        return None

    # Image has not changed.

    if current_image is not None and mtime == current_mtime:
        return current_image

    try:
        with open(IMAGE_FILE, "rb") as file:
            image_data = file.read()

        current_image = image_data
        current_mtime = mtime

        print(f"Loaded new image: {IMAGE_FILE}")

        return current_image

    except Exception as error:
        print(f"Error reading image: {error}")
        return None


# ------------------------------------------------------------------------------
# PUSH VIDEO FRAME
# ------------------------------------------------------------------------------

def push_frame():

    image_data = load_image()

    if image_data is None:
        return True

    buffer = Gst.Buffer.new_allocate(
        None,
        len(image_data),
        None
    )

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
# CREATE GSTREAMER PIPELINE
# ------------------------------------------------------------------------------

def create_pipeline():

    global appsrc

    pipeline = Gst.Pipeline.new("stream-pipeline")

    # --------------------------------------------------------------------------
    # VIDEO
    # --------------------------------------------------------------------------

    appsrc = Gst.ElementFactory.make(
        "appsrc",
        "image-source"
    )

    jpegdec = Gst.ElementFactory.make(
        "jpegdec",
        "jpeg-decoder"
    )

    videoconvert = Gst.ElementFactory.make(
        "videoconvert",
        "video-convert"
    )

    videoscale = Gst.ElementFactory.make(
        "videoscale",
        "video-scale"
    )

    videocaps = Gst.ElementFactory.make(
        "capsfilter",
        "video-caps"
    )

    x264enc = Gst.ElementFactory.make(
        "x264enc",
        "h264-encoder"
    )

    h264parse = Gst.ElementFactory.make(
        "h264parse",
        "h264-parser"
    )

    # --------------------------------------------------------------------------
    # AUDIO
    # --------------------------------------------------------------------------

    source = Gst.ElementFactory.make(
        "uridecodebin3",
        "icecast-source"
    )

    audio_queue = Gst.ElementFactory.make("queue", "audio_queue")
    audio_queue.set_property("max-size-time", 2 * Gst.SECOND)
    audio_queue.set_property("max-size-bytes", 0)
    audio_queue.set_property("max-size-buffers", 0)

    audioconvert = Gst.ElementFactory.make(
        "audioconvert",
        "audio-convert"
    )

    audioresample = Gst.ElementFactory.make(
        "audioresample",
        "audio-resample"
    )

    audiocaps = Gst.ElementFactory.make(
        "capsfilter",
        "audio-caps"
    )

    avenc_aac = Gst.ElementFactory.make(
        "avenc_aac",
        "aac-encoder"
    )

    aacparse = Gst.ElementFactory.make(
        "aacparse",
        "aac-parser"
    )

    # --------------------------------------------------------------------------
    # MUX / OUTPUT
    # --------------------------------------------------------------------------

    mpegtsmux = Gst.ElementFactory.make(
        "mpegtsmux",
        "mpegts-mux"
    )

    mpegtsmux.set_property(
        "alignment",
        7
    )

    mpegtsmux.set_property(
        "pat-interval",
        9000
    )

    mpegtsmux.set_property(
        "pmt-interval",
        9000
    )

    mpegtsmux.set_property(
        "pcr-interval",
        3600
    )

    udpsink = Gst.ElementFactory.make(
        "udpsink",
        "udp-sink"
    )

    elements = [
        appsrc,
        jpegdec,
        videoconvert,
        videoscale,
        videocaps,
        x264enc,
        h264parse,

        source,
        audio_queue,
        audioconvert,
        audioresample,
        audiocaps,
        avenc_aac,
        aacparse,

        mpegtsmux,
        udpsink,
    ]

    for element in elements:

        if element is None:
            raise RuntimeError(
                "Unable to create one or more GStreamer elements"
            )

    # --------------------------------------------------------------------------
    # APP SOURCE
    # --------------------------------------------------------------------------

    appsrc.set_property(
        "format",
        Gst.Format.TIME
    )

    appsrc.set_property(
        "is-live",
        True
    )

    appsrc.set_property(
        "block",
        True
    )

    appsrc.set_property(
        "do-timestamp",
        True
    )

    appsrc.set_property(
        "caps",
        Gst.Caps.from_string(
            f"image/jpeg,"
            f"framerate={VIDEO_FPS}/1"
        )
    )

    # --------------------------------------------------------------------------
    # VIDEO CAPS
    # --------------------------------------------------------------------------

    videocaps.set_property(
        "caps",
        Gst.Caps.from_string(
            f"video/x-raw,"
            f"width={VIDEO_WIDTH},"
            f"height={VIDEO_HEIGHT},"
            f"framerate={VIDEO_FPS}/1"
        )
    )

    # --------------------------------------------------------------------------
    # H.264
    # --------------------------------------------------------------------------

    x264enc.set_property(
        "tune",
        "zerolatency"
    )

    x264enc.set_property(
        "speed-preset",
        "veryfast"
    )

    x264enc.set_property(
        "bitrate",
        VIDEO_BITRATE
    )

    x264enc.set_property(
        "key-int-max",
        VIDEO_FPS
    )

    x264enc.set_property(
        "byte-stream",
        True
    )

    h264parse.set_property(
        "config-interval",
        -1
    )

    # --------------------------------------------------------------------------
    # ICECAST SOURCE
    # --------------------------------------------------------------------------

    source.set_property(
        "uri",
        ICECAST_URL
    )

    source.connect(
        "pad-added",
        on_audio_pad_added,
        audioconvert
    )

    # --------------------------------------------------------------------------
    # AUDIO CAPS
    # --------------------------------------------------------------------------

    audiocaps.set_property(
        "caps",
        Gst.Caps.from_string(
            "audio/x-raw,"
            "rate=48000,"
            "channels=2"
        )
    )

    # --------------------------------------------------------------------------
    # AAC
    # --------------------------------------------------------------------------

    avenc_aac.set_property(
        "bitrate",
        AUDIO_BITRATE
    )

    # --------------------------------------------------------------------------
    # UDP OUTPUT
    # --------------------------------------------------------------------------

    udpsink.set_property("host", UDP_HOST)
    udpsink.set_property("port", UDP_PORT)
    udpsink.set_property("sync", False)
    udpsink.set_property("async", False)

    # --------------------------------------------------------------------------
    # ADD ELEMENTS
    # --------------------------------------------------------------------------

    for element in elements:

        pipeline.add(element)

    # --------------------------------------------------------------------------
    # LINK VIDEO
    # --------------------------------------------------------------------------

    video_links = [
        (appsrc, jpegdec),
        (jpegdec, videoconvert),
        (videoconvert, videoscale),
        (videoscale, videocaps),
        (videocaps, x264enc),
        (x264enc, h264parse),
        (h264parse, mpegtsmux),
    ]

    for source_element, sink_element in video_links:

        if not source_element.link(sink_element):

            raise RuntimeError(
                f"Unable to link "
                f"{source_element.get_name()} -> "
                f"{sink_element.get_name()}"
            )

    # --------------------------------------------------------------------------
    # LINK AUDIO
    # --------------------------------------------------------------------------

    audio_links = [
        (audioconvert, audio_queue),
        (audio_queue, audioresample),
        (audioresample, audiocaps),
        (audiocaps, avenc_aac),
        (avenc_aac, aacparse),
        (aacparse, mpegtsmux),
    ]

    for source_element, sink_element in audio_links:

        if not source_element.link(sink_element):

            raise RuntimeError(
                f"Unable to link "
                f"{source_element.get_name()} -> "
                f"{sink_element.get_name()}"
            )

    # --------------------------------------------------------------------------
    # MUX → OUTPUT
    # --------------------------------------------------------------------------

    if not mpegtsmux.link(udpsink):

        raise RuntimeError(
            "Unable to link mpegtsmux -> udpsink"
        )

    return pipeline


# ------------------------------------------------------------------------------
# AUDIO PAD HANDLER
# ------------------------------------------------------------------------------

def on_audio_pad_added(
    decodebin,
    pad,
    audioconvert
):

    caps = pad.get_current_caps()

    if caps is None:

        caps = pad.query_caps(None)

    structure = caps.get_structure(0)

    media_type = structure.get_name()

    print(
        f"New Icecast stream pad: {media_type}"
    )

    if media_type.startswith("audio/"):

        sink_pad = audioconvert.get_static_pad("sink")

        if sink_pad.is_linked():

            print("Audio pad already linked")
            return

        result = pad.link(sink_pad)

        if result != Gst.PadLinkReturn.OK:

            print(
                f"Unable to link Icecast audio: {result}"
            )

        else:

            print("Icecast audio linked successfully.")


# ------------------------------------------------------------------------------
# GSTREAMER BUS
# ------------------------------------------------------------------------------

def on_message(bus, message):

    global main_loop

    message_type = message.type

    if message_type == Gst.MessageType.ERROR:

        error, debug = message.parse_error()

        print(
            f"GStreamer error: {error}"
        )

        if debug:

            print(
                f"Debug information: {debug}"
            )

        main_loop.quit()

    elif message_type == Gst.MessageType.EOS:

        print(
            "GStreamer reached end of stream"
        )

        main_loop.quit()

    elif message_type == Gst.MessageType.WARNING:

        warning, debug = message.parse_warning()

        print(
            f"GStreamer warning: {warning}"
        )

        if debug:

            print(
                f"Debug information: {debug}"
            )

    return True


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():

    global main_loop

    print(
        "Starting video/audio streamer"
    )

    print(
        f"Image:       {IMAGE_FILE}"
    )

    print(
        f"Resolution:  "
        f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}"
    )

    print(
        f"Frame rate:  {VIDEO_FPS} fps"
    )

    print(
        f"Icecast:     {ICECAST_URL}"
    )

    print(
        f"UDP Output:    {UDP_HOST}:{UDP_PORT}"
    )

    pipeline = create_pipeline()

    bus = pipeline.get_bus()

    bus.add_signal_watch()

    bus.connect(
        "message",
        on_message
    )

    main_loop = GLib.MainLoop()

    pipeline.set_state(
        Gst.State.PLAYING
    )

    interval_ms = int(
        1000 / VIDEO_FPS
    )

    source_id = GLib.timeout_add(
        interval_ms,
        push_frame
    )

    try:

        main_loop.run()

    except KeyboardInterrupt:

        print(
            "\nStopping streamer..."
        )

    finally:

        try:
            GLib.source_remove(source_id)
        except Exception:
            pass

        appsrc.emit(
            "end-of-stream"
        )

        pipeline.set_state(
            Gst.State.NULL
        )

        print(
            "Streamer stopped."
        )


# ------------------------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------------------------

if __name__ == "__main__":

    main()
