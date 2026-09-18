import json
import requests
import time
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance


# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------

STATION_NAME = "Woolworths Radio"
STATION_LOGO = "https://i.iheart.com/v3/re/new_assets/617f2881bd5039e366ef0289?ops=fit(240%2C240)"
TRACK_META_URL = "https://au.api.iheart.com/api/v3/live-meta/stream/9195/currentTrackMeta"

UPDATE_INTERVAL =  5
IMAGE_DEFINITION = 720 # EG: 480 for 480p, 720 for 720p, 1080 for 1080p, etc.
OUTPUT_FILE = Path("now_playing.jpg")

REQUEST_TIMEOUT = 10  # seconds

# Base definitions for image dimensions based on 16:9 aspect ratio
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
        "/usr/share/fonts/liberation-sans-fonts/"
        "LiberationSans-Bold.ttf",
        FONT_SIZE_TITLE
    )
    FONT_SUB = ImageFont.truetype(
        "/usr/share/fonts/liberation-sans-fonts/"
        "LiberationSans-Regular.ttf",
        FONT_SIZE_SUB
    )

except IOError:
    FONT_TITLE = ImageFont.load_default()
    FONT_SUB = ImageFont.load_default()


# ------------------------------------------------------------------------------
# CACHED STATION LOGO
# ------------------------------------------------------------------------------

station_logo = None

def get_station_logo():

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


# ------------------------------------------------------------------------------
# TRACK METADATA
# ------------------------------------------------------------------------------

def get_track_metadata():

    default_data = { # default json data when metadata not available
        "title": STATION_NAME,
        "artist": "Clear Channel Australia",
        "album": "iHeartRadio",
        "imagePath": STATION_LOGO
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


# ------------------------------------------------------------------------------
# ALBUM ARTWORK
# ------------------------------------------------------------------------------

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


# ------------------------------------------------------------------------------
# IMAGE GENERATION
# ------------------------------------------------------------------------------

def generate_image():

    data = get_track_metadata()

    # Canvas
    img_width = IMAGE_DEFINITION * 16 // 9
    img_height = IMAGE_DEFINITION

    image = Image.new("RGB", (img_width, img_height), color="#18181b")
    draw = ImageDraw.Draw(image)

    # Album artwork placeholder
    art_size = int(ART_SIZE_BASE * SCALE)
    art_x, art_y = int(50 * SCALE), img_height - art_size - int(50 * SCALE)
    art_color = "#3f3f46"
    draw.rectangle(
        [art_x, art_y, art_x + art_size, art_y + art_size], fill=art_color
    )

    # Album artwork
    album_artwork = get_album_artwork(data.get("imagePath"))
    if album_artwork is not None:

        # Blurred background
        background = album_artwork.filter(ImageFilter.GaussianBlur(radius=64))
        background = background.resize((img_width, img_width))
        enhancer = ImageEnhance.Brightness(background)
        background = enhancer.enhance(0.6)
        image.paste(background, (0, -(img_width - img_height) // 2))

        # Album cover
        album_cover = album_artwork.resize((art_size, art_size))
        image.paste(album_cover, (art_x, art_y))

    # Track Information
    text_block_height = FONT_SIZE_TITLE + FONT_SIZE_SUB * 2 + 20 # title + artist + album + padding
    text_x = art_size + int(70 * SCALE) # 50 left padding + art_size + 20 padding between album art and text
    text_y = art_y + (art_size - text_block_height) // 2

    # - Track name
    draw.text(
        (text_x, text_y), data["title"], fill="#ffffff", font=FONT_TITLE
    )

    # - Artist name
    draw.text(
        (text_x, text_y + FONT_SIZE_TITLE + 10), data["artist"], fill="#a1a1aa", font=FONT_SUB
    )

    # - Album name
    draw.text(
        (text_x, text_y + FONT_SIZE_TITLE + FONT_SIZE_SUB + 20), data['album'], fill="#71717a", font=FONT_SUB
    )

    # Station logo
    logo = get_station_logo()

    if logo is not None:
        logo_size = 50
        logo = logo.resize((logo_size, logo_size))
        image.paste(logo, (50, 50), logo)

    draw.text(
        (50 + logo_size + 20, 50 + logo_size // 2 - FONT_SIZE_SUB // 2), STATION_NAME, fill="#a1a1aa", font=FONT_SUB
    )

    # Return the generated image
    return image


# ------------------------------------------------------------------------------
# IMAGE OUTPUT
# ------------------------------------------------------------------------------

def save_image(image):
    temporary_file = OUTPUT_FILE.with_suffix(".tmp.jpg")
    image.save(temporary_file, "JPEG", quality=90, optimize=True)
    temporary_file.replace(OUTPUT_FILE)


# ------------------------------------------------------------------------------
# MAIN LOOP
# ------------------------------------------------------------------------------

def main():

    print(
        f"Now playing image generator started. "
        f"Output file: {OUTPUT_FILE} - "
        f"Update interval: {UPDATE_INTERVAL} seconds"
    )

    try:
        while True:
            try:
                image = generate_image()
                save_image(image)
                print(f"Image generated and saved to {OUTPUT_FILE}")
            except Exception as error:
                print(f"Error generating image: {error}")

            time.sleep(UPDATE_INTERVAL)

    except KeyboardInterrupt:
        print("\nNow playing image generator stopped.")


# ------------------------------------------------------------------------------
# MAIN ENTRY POINT
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    main()
