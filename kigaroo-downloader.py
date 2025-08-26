import re
import os
import asyncio
import json
import glob
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from playwright.async_api import async_playwright
from exif import Image, GpsAltitudeRef, DATETIME_STR_FORMAT
from pathvalidate import sanitize_filename

with open("config.json", "r") as jsonfile:
    config = json.load(jsonfile)


def remove_emojis(data) -> str:
    emoj: re.Pattern[str] = re.compile(
        "["
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f300-\U0001f5ff"  # symbols & pictographs
        "\U0001f680-\U0001f6ff"  # transport & map symbols
        "\U0001f1e0-\U0001f1ff"  # flags (iOS)
        "\U00002500-\U00002bef"  # chinese char
        "\U00002702-\U000027b0"
        "\U000024c2-\U0001f251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u2640-\u2642"
        "\u2600-\u2b55"
        "\u200d"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\ufe0f"  # dingbats
        "\u3030"
        "]+",
        re.UNICODE,
    )
    return re.sub(emoj, "", data)


def replace_vowels(string: str) -> str:
    """replace special German umlauts (vowel mutations) from text.
    ä -> ae, Ä -> Ae...
    ü -> ue, Ü -> Ue...
    ö -> oe, Ö -> Oe...
    ß -> ss
    """
    vowel_char_map: dict[int, str] = {
        ord("ä"): "ae",
        ord("ü"): "ue",
        ord("ö"): "oe",
        ord("ß"): "ss",
        ord("Ä"): "Ae",
        ord("Ü"): "Ue",
        ord("Ö"): "Oe",
    }
    return string.translate(vowel_char_map)


save_to = {}


def handle_image(data: bytes, info: dict) -> None:
    dir_path = info["album"]["dir_path"]
    fname = info["title"] + ".jpg"
    file_path = os.path.join(dir_path, fname)
    if not os.path.isdir(dir_path):
        os.makedirs(dir_path)

    image = Image(data)
    image.gps_latitude = tuple(config["location"]["latitude"])
    image.gps_latitude_ref = config["location"]["latitude_ref"]
    image.gps_longitude = tuple(config["location"]["longitude"])
    image.gps_longitude_ref = config["location"]["longitude_ref"]
    image.gps_altitude = config["location"]["altitude"]
    image.gps_altitude_ref = GpsAltitudeRef.ABOVE_SEA_LEVEL

    image_description: str = replace_vowels(info["album"]["title"])
    image.image_description = image_description.encode("ascii", "ignore").decode()

    image.datetime_original = info["album"]["date"].strftime(DATETIME_STR_FORMAT)

    print("saving to", file_path)
    with open(file_path, "wb") as new_image_file:
        new_image_file.write(image.get_file())


async def on_response(response) -> None:
    # hook to save files on download
    if response.request.url in save_to:
        if not response.ok:
            raise Exception("Download failed")

        details: dict = save_to[response.request.url]
        data: bytes = await response.body()
        handle_image(data, details)


async def run() -> None:
    async with async_playwright() as p:
        # Launch headless Chromium
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(base_url=config["base_url"])
        page = await context.new_page()
        page.on("response", on_response)

        # Go to login page
        await page.goto("/login")

        # Fill in the login form
        await page.fill('input[name="_username"]', config["username"])
        await page.fill('input[name="_password"]', config["password"])

        await page.press('input[name="_password"]', "Enter")

        await page.wait_for_load_state("networkidle")

        assert "backend" in page.url

        await page.goto("/backend/gallery/")
        await page.wait_for_load_state("networkidle")

        collections = page.locator('css=article[class="app-gridCard kgr-grid__cell"]')
        count = await collections.count()
        albums = []
        for i in range(count):
            collection = collections.nth(i)

            title_element = collection.locator("h3 a")
            title_text = await title_element.text_content()
            title_link = await title_element.get_attribute("href")
            date_text = await collection.locator(
                "div.kgr-card__footerContents > div.kgr-postfix__fluid"
            ).text_content()
            image_count_text = await collection.locator(
                "div.kgr-centered.kgr-centered--vertically"
            ).text_content()
            image_count = int(image_count_text)

            pdate_parts = date_text.strip().split(".")
            assert len(pdate_parts) == 3
            datetime_taken = datetime(
                year=int(pdate_parts[2]),
                month=int(pdate_parts[1]),
                day=int(pdate_parts[0]),
                hour=10,
                minute=0,
                second=0,
            )

            title_text: str = remove_emojis(title_text).strip()
            date_text = date_text.strip()

            dirdate: str = datetime_taken.strftime("%Y-%m-%d")
            tdir = Path(f"{dirdate} - {title_text}")
            tdir = sanitize_filename(tdir)
            dir_path = os.path.join(config["save_dir"], tdir)

            albums.append(
                {
                    "title": title_text,
                    "url": title_link,
                    "date": datetime_taken,
                    "dir_path": dir_path,
                    "image_count": image_count,
                }
            )

            #print("album", i, title_text, date_text, datetime_taken, title_link, image_count)

        for album in albums:
            if os.path.isdir(album["dir_path"]):
                glob_path = os.path.join(album["dir_path"], "*.jpg")
                image_files_count: int = len(glob.glob(glob_path))
                if image_files_count == album['image_count']:
                    print(f"skipping aready downloaded album: {album['title']}")
                    continue
                else:
                    print(
                        f"redownloading album: {album['title']}, have {image_files_count} files, expecting {album['image_count']}"
                    )

            print(f"processing album {album['title']}")

            await page.goto(album["url"])
            await page.wait_for_load_state("networkidle")

            image_boxes = page.locator(
                'css=article[class="app-gridCard kgr-grid__cell"]'
            )
            count = await image_boxes.count()
            images = []
            for i in range(count):
                image_boxe = image_boxes.nth(i)
                card_element = image_boxe.locator("a.kgr-card__image")
                card_link: str = await card_element.get_attribute("href")
                card_title: str = await card_element.get_attribute("title")
                images.append({"title": card_title, "url": card_link})

                # print("image", i, card_title, card_link)

            for image in images:
                full_url = urljoin(config["base_url"], image["url"])
                save_to[full_url] = {"album": album, "title": image["title"]}
                await page.goto(image["url"])
                await page.wait_for_load_state("networkidle")

        await browser.close()


asyncio.run(run())
