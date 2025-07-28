#!/usr/bin/env python3
# youtubemusicartistdownloader.py

import argparse
import concurrent.futures
import difflib
import os
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.parse
import tempfile
from mutagen.easymp4 import EasyMP4
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from threading import Thread, Semaphore, Event, Lock   # ← added Lock already present but needed again

# ──────────────────────────────────────────────────────────────────────────────
# ── COOKIE / SELENIUM CONFIG ──────────────────────────────────────────────────

# Path to your ChromeDriver
chromedriver_path = '/usr/bin/chromedriver'

# Mandatory initial Netscape-cookie file (provided by the user)
COOKIE_BOOT_FILE = "logincookies.txt"

# Folder for periodically refreshed cookie dumps
TMP_COOKIE_DIR = "tmp-cookie"

# Stable, atomically replaced cookie file used by yt-dlp
COOKIE_ACTIVE_FILE = os.path.join(TMP_COOKIE_DIR, "cookies-latest.txt")

# Interval (seconds) to refresh cookies in the background browser
COOKIE_DUMP_INTERVAL = 120

# Suffix whitelist for all Google/YouTube auth cookies
ALLOWED_COOKIE_SUFFIXES = (
    ".youtube.com",           # incl. accounts.youtube.com, music.youtube.com …
    ".google.com",            # incl. accounts.google.com …
    ".googleusercontent.com", # token rotation / CDNs
    ".googleapis.com",        # NEW: covers youtubei.googleapis.com etc.
)

def cookie_allowed(domain: str) -> bool:
    """Return True if *domain* matches one of the allowed suffixes."""
    return any(domain == suf.lstrip(".") or domain.endswith(suf)
               for suf in ALLOWED_COOKIE_SUFFIXES)

# Global stop event for cookie refresher thread
stop_cookie_refresher = Event()

# Signals that at least one valid cookie dump is ready
first_cookie_dump_ready = Event()

# Lock to guard reads/writes if ever needed elsewhere
_cookie_lock = Lock()

# NEW: global lock to serialize moves into the final "music" folder
move_lock = Lock()

# ── FIX 3: keep a global handle to the cookie driver so we can shut it down safely ──
_cookie_driver = None

# ──────────────────────────────────────────────────────────────────────────────
# ── ORIGINAL UTILITIES (UNTOUCHED EXCEPT WHERE NOTED) ─────────────────────────

def build_headless_options():
    opt = Options()
    opt.add_argument("--headless")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    return opt

def get_user_agent(chromedriver_path):
    # Setze die Optionen für den temporären Chrome-Browser
    temp_options = build_headless_options()

    # Initialisiere den temporären Webdriver
    temp_service = Service(chromedriver_path)
    tmpdriver = webdriver.Chrome(service=temp_service, options=temp_options)

    # Erfasse den User-Agent
    user_agent = tmpdriver.execute_script("return navigator.userAgent")

    # Beende den temporären Webdriver
    tmpdriver.quit()

    user_agent = str(user_agent)
    user_agent = user_agent.replace("Headless", "")

    print(f"Debug: latest useragent: {user_agent}")

    return user_agent

# Erfasse den User-Agent
user_agent = get_user_agent(chromedriver_path)

# Setze die Optionen für den Chrome-Browser mit dem erfassten User-Agent
def build_main_driver():
    chrome_options = build_headless_options()
    chrome_options.add_argument(f'user-agent={user_agent}')
    service = Service(chromedriver_path)
    return webdriver.Chrome(service=service, options=chrome_options)

# ── FIX: defer driver creation to main() to avoid zombie driver on early exit ──
driver = None  # will be initialized lazily inside main()

def save_page_source(filename):
    with open(filename, 'w', encoding='utf-8') as file:
        file.write(driver.page_source)

def click_privacy_button():
    try:
        button = driver.find_element(By.XPATH, '//button[@aria-label="Reject all"]')
        button.click()
        time.sleep(1)  # Kurze Wartezeit, um sicherzustellen, dass die Aktion abgeschlossen ist
        print("Debug: 'Alle ablehnen' button clicked successfully.")
    except Exception:
        print(f"Debug: Privacy button not found or could not be clicked.")

# ── NEW: driver-aware variant to avoid touching the global driver from threads ──
def click_privacy_button_on(drv):
    """Same as click_privacy_button(), but operates on the given WebDriver instance."""
    try:
        button = drv.find_element(By.XPATH, '//button[@aria-label="Reject all"]')
        button.click()
        time.sleep(1)
        print("Debug: 'Alle ablehnen' button clicked successfully (thread-local).")
    except Exception:
        print("Debug: Privacy button not found or could not be clicked (thread-local).")

def similarity_ratio(str1, str2):
    return difflib.SequenceMatcher(None, str1, str2).ratio()

def extract_artist_href(search_term, artist):
    youtube_music_search_link = f"https://music.youtube.com/search?q={search_term}"
    print(f"Debug: Loading search page: {youtube_music_search_link}")
    driver.get(youtube_music_search_link)
    time.sleep(1)
    click_privacy_button()

    artist_elements = driver.find_elements(By.CSS_SELECTOR, 'a.yt-simple-endpoint.thumbnail-link[href*="channel/"]')
    print(f"Debug: Found {len(artist_elements)} elements with selector 'a.yt-simple-endpoint.thumbnail-link'")

    for element in artist_elements:
        title = element.get_attribute('title')
        href = element.get_attribute('href')
        similarity = similarity_ratio(artist.lower(), title.lower())
        print(f"Debug: Found element with title '{title}' and href '{href}' with similarity {similarity:.2f}")
        if similarity > 0.6 and "channel/" in href:
            print(f"Debug: Matching element found with href: {href}")
            return title, href
    print("Debug: No matching element found.")
    return None, None

def extract_section_hrefs(section_name):
    sections = driver.find_elements(By.CSS_SELECTOR, 'div.ytmusic-shelf')
    for section in sections:
        try:
            link_element = section.find_element(
                By.XPATH,
                f"//yt-formatted-string[contains(@class, 'title text style-scope ytmusic-carousel-shelf-basic-header-renderer') and .//a[contains(@href, 'browse/') and contains(text(), '{section_name}')]]//a"
            )
            href = link_element.get_attribute('href')
            print(f"Debug: Found {section_name} section with href: {href}")
            link_element.click()
            time.sleep(1)
            return section, True
        except Exception:
            print(f"Debug: No <a> tag found for {section_name}.")
            try:
                title_element = section.find_element(By.XPATH, f'.//yt-formatted-string[contains(text(), "{section_name}")]')
                print(f"Debug: Found {section_name} section without href")
                return section, False
            except Exception:
                print(f"Debug: No <yt-formatted-string> tag found for {section_name}.")
                continue
    print(f"Debug: {section_name} section not found.")
    return None, False

def scroll_to_bottom(driver, scroll_pause_time=2):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_pause_time)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    print("Debug: Scrolling completed or maximum scroll count reached.")

def extract_item_hrefs_from_page(section=None):
    if section is None:
        scroll_to_bottom(driver)
        item_elements = driver.find_elements(By.CSS_SELECTOR, 'a.yt-simple-endpoint.image-wrapper.style-scope.ytmusic-two-row-item-renderer')
    else:
        scroll_to_bottom(driver)
        item_elements = section.find_elements(By.CSS_SELECTOR, 'a.yt-simple-endpoint.image-wrapper.style-scope.ytmusic-two-row-item-renderer')

    item_hrefs = []
    for element in item_elements:
        href = element.get_attribute('href')
        if "browse/" in href:
            item_hrefs.append(href)

    print(f"Debug: Total number of items found: {len(item_hrefs)}")
    return item_hrefs

def update_metadata(file_path, album_artist):
    audio = EasyMP4(file_path)
    audio['albumartist'] = album_artist
    audio.save()
    print(f"Debug: Updated metadata with album artist {album_artist} for {file_path}")

def handle_album_conflicts(src_folder, dest_folder):
    deepest_folder = get_deepest_folder(src_folder)
    print(f"Debug: Deepest folder in src_folder: {deepest_folder}")

    relative_path = os.path.relpath(deepest_folder, src_folder)
    dest_deepest_folder = os.path.join(dest_folder, relative_path)
    print(f"Debug: Checking for deepest folder in dest_folder: {dest_deepest_folder}")

    if os.path.exists(dest_deepest_folder):
        src_file_count = count_files(deepest_folder)
        dest_file_count = count_files(dest_deepest_folder)

        if src_file_count < dest_file_count:
            rename_to = determine_unique_name(dest_deepest_folder, "(EP) " + os.path.basename(deepest_folder))
            new_deepest_folder = os.path.join(os.path.dirname(deepest_folder), rename_to)
            os.rename(deepest_folder, new_deepest_folder)
            print(f"Debug: Renamed {deepest_folder} to {new_deepest_folder}")
        else:
            rename_to = determine_unique_name(dest_deepest_folder, "(EP) " + os.path.basename(dest_deepest_folder))
            new_dest_deepest_folder = os.path.join(os.path.dirname(dest_deepest_folder), rename_to)
            os.rename(dest_deepest_folder, new_dest_deepest_folder)
            print(f"Debug: Renamed {dest_deepest_folder} to {new_dest_deepest_folder}")
    else:
        print(f"Debug: No path conflict found.")

def determine_unique_name(base_folder, base_name):
    index = 1
    new_name = base_name
    while os.path.exists(os.path.join(os.path.dirname(base_folder), new_name)):
        new_name = f"{base_name}{index}"
        index += 1
    return new_name

def get_deepest_folder(folder):
    deepest_path = ""
    max_depth = 0
    for root, dirs, files in os.walk(folder):
        depth = root[len(folder):].count(os.sep)
        if depth > max_depth:
            max_depth = depth
            deepest_path = root
    return deepest_path

def count_files(folder):
    return sum([len(files) for r, d, files in os.walk(folder)])

# ── FIXED: single-writer lock around final move to avoid race conditions ──────
def move_to_finished_folder(src_folder, dest_folder):
    """Move *src_folder* into *dest_folder* atomically under a global lock."""
    with move_lock:
        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder)

        handle_album_conflicts(src_folder, dest_folder)

        for root, dirs, files in os.walk(src_folder, topdown=False):
            for name in dirs:
                dest_dir = os.path.join(dest_folder, os.path.relpath(os.path.join(root, name), src_folder))
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)

            for name in files:
                src_file = os.path.join(root, name)
                dest_file = os.path.join(dest_folder, os.path.relpath(src_file, src_folder))
                dest_dir = os.path.dirname(dest_file)
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)
                shutil.move(src_file, dest_file)

        shutil.rmtree(src_folder)
        print(f"Debug: Moved {src_folder} to {dest_folder}")

def sanitize_filename(name):
    if name == '':
        return ''
    def replace_insane(char):
        if char == '\n':
            return ' '
        elif char in '"*:<>?|/\\':
            return '_'
        elif char == '?' or ord(char) < 32 or ord(char) == 127:
            return ''
        elif char == '"':
            return ''
        elif char == ':':
            return '_-'
        elif char in '\\/|*<>':
            return '_'
        if char in '!&\'()[]{}$;^,#' or char.isspace() or ord(char) > 127:
            return '' if unicodedata.category(char)[0] in 'CM' else '_'
        return char
    name = unicodedata.normalize('NFKC', name)
    name = re.sub(r'[0-9]+(?::[0-9]+)+', lambda m: m.group(0).replace(':', '_'), name)
    result = ''.join(map(replace_insane, name))
    result = re.sub(r'(\0.)(?:(?=\1)..)+', r'\1', result)
    STRIP_RE = r'(?:\0.|[ _-])*'
    result = re.sub(f'^\0.{STRIP_RE}|{STRIP_RE}\0.$', '', result)
    result = result.replace('\0', '') or '_'
    while '__' in result:
        result = result.replace('__', '_')
    result = result.strip('_')
    if result.startswith('-_'):
        result = result[2:]
    if result.startswith('-'):
        result = '_' + result[len('-'):]
    result = result.lstrip('.')
    if not result:
        result = '_'
    return result

# ──────────────────────────────────────────────────────────────────────────────
# ── NETSCAPE COOKIE FILE I/O ──────────────────────────────────────────────────

def read_netscape_cookies(path: str):
    cookies = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue
            domain, flag, cpath, secure, exp, name, value = parts[:7]
            cookies.append({
                "domain": domain.lstrip("."),
                "path": cpath,
                "secure": secure.upper() == "TRUE",
                "expiry": int(exp) if exp.isdigit() else None,
                "name": name,
                "value": value,
            })
    return cookies

def write_netscape_cookies(cookies, out_path: str):
    header = (
        "# Netscape HTTP Cookie File generated by youtubemusicartistdownloader.py\n"
        "# This file is automatically overwritten – do not edit.\n\n"
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(header)
        for c in cookies:
            domain = "." + c["domain"].lstrip(".")
            flag   = "TRUE"
            path   = c.get("path", "/")
            secure = "TRUE" if c.get("secure") else "FALSE"
            expiry = str(c.get("expiry", 2147483647))
            name   = c["name"]
            value  = c["value"]
            fh.write("\t".join([domain, flag, path, secure, expiry, name, value]) + "\n")

# ──────────────────────────────────────────────────────────────────────────────
# ── COOKIE REFRESHER THREAD (FIXED: ATOMIC WRITES, STABLE FILE) ───────────────

def _atomic_replace_cookie_file(cookies):
    """
    Write cookies to a temporary file and atomically replace COOKIE_ACTIVE_FILE.
    Ensures readers never see a partially written file.
    """
    with _cookie_lock:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=TMP_COOKIE_DIR, prefix=".cookies-", suffix=".tmp")
        os.close(tmp_fd)  # We'll reopen with text mode
        write_netscape_cookies(cookies, tmp_path)
        os.replace(tmp_path, COOKIE_ACTIVE_FILE)  # atomic on POSIX/NTFS
    first_cookie_dump_ready.set()

def start_cookie_refresher() -> Thread:
    """
    Launch a second Selenium browser that keeps the session fresh and dumps
    cookies every COOKIE_DUMP_INTERVAL seconds into COOKIE_ACTIVE_FILE atomically.
    """
    os.makedirs(TMP_COOKIE_DIR, exist_ok=True)

    # Use the SAME user agent as the main driver to avoid inconsistencies
    opt = build_headless_options()
    opt.add_argument(f'user-agent={user_agent}')
    svc = Service(chromedriver_path)

    # ── FIX 3: store driver globally for guaranteed shutdown ──
    global _cookie_driver
    _cookie_driver = webdriver.Chrome(service=svc, options=opt)
    cdriver = _cookie_driver

    # Initial visit so we can add cookies
    cdriver.get("https://music.youtube.com")
    time.sleep(1)

    # Import boot cookies (filtered)
    boot_cookies = read_netscape_cookies(COOKIE_BOOT_FILE)
    for ck in boot_cookies:
        if cookie_allowed(ck["domain"]):
            try:
                cdriver.add_cookie(ck)
            except Exception:
                pass

    # Do an immediate first dump so downloads don't start with an outdated file
    try:
        cdriver.get("https://music.youtube.com")
        click_privacy_button_on(cdriver)
        cookies = [c for c in cdriver.get_cookies() if cookie_allowed(c["domain"])]
        _atomic_replace_cookie_file(cookies)
        print("Debug: Initial cookie dump written.")
    except Exception as e:
        print(f"Debug: Initial cookie dump failed – {e}")

    def loop():
        while not stop_cookie_refresher.is_set():
            try:
                cdriver.get("https://music.youtube.com")
                click_privacy_button_on(cdriver)
                cookies = [c for c in cdriver.get_cookies() if cookie_allowed(c["domain"])]
                _atomic_replace_cookie_file(cookies)
                print("Debug: Refreshed cookies written atomically.")
            except Exception as e:
                print(f"Debug: Cookie refresh failed – {e}")
            stop_cookie_refresher.wait(COOKIE_DUMP_INTERVAL)

        # graceful shutdown
        try:
            cdriver.quit()
        except Exception:
            pass

    t = Thread(target=loop, name="CookieRefresher", daemon=True)
    t.start()
    return t

def latest_cookie_file() -> str:
    """
    Always return the stable, atomically updated COOKIE_ACTIVE_FILE if present.
    Fallback to COOKIE_BOOT_FILE only if nothing else exists yet.
    """
    with _cookie_lock:
        if os.path.exists(COOKIE_ACTIVE_FILE):
            return COOKIE_ACTIVE_FILE
    return COOKIE_BOOT_FILE

# ──────────────────────────────────────────────────────────────────────────────
# ── DOWNLOADER (MODIFIED TO ALWAYS USE LATEST COOKIES SAFELY) ────────────────

def download_item(item_url, artist_name, tmp_folder):
    sanitized_artist_name = sanitize_filename(artist_name)

    if not os.path.exists(tmp_folder):
        os.makedirs(tmp_folder)

    def run_download():
        command = [
            "yt-dlp",
            "--cookies", latest_cookie_file(),
            "--retries", "5",
            "--retry-sleep", "5",
            "--concurrent-fragments", "10",
            "-f", "bestaudio",
            "-t", "sleep",
            "--extract-audio",
            "--parse-metadata", "release_year:(?s)(?P<meta_date>.+)",
            "--parse-metadata", "playlist_index:(?s)(?P<track_number>.+)",
            "--audio-format", "m4a",
            "--embed-metadata",
            "--add-metadata",
            "--embed-thumbnail",
            "--compat-options", "filename-sanitization",
            "--output", os.path.join(tmp_folder, sanitized_artist_name, "%(album)s/%(title)s.%(ext)s"),
            item_url
        ]
        subprocess.run(command)

    def contains_webm_or_webp(folder):
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.endswith(".webm") or file.endswith(".webp"):
                    return True
        return False

    def get_error_folder_name(base_folder):
        index = 0
        while True:
            error_folder = f"{base_folder}_Error{index}"
            if not os.path.exists(error_folder):
                return error_folder
            index += 1

    attempts = 0
    max_attempts = 10
    while attempts < max_attempts:
        run_download()
        attempts += 1
        album_folder = os.path.join(tmp_folder, sanitized_artist_name)
        if not contains_webm_or_webp(album_folder):
            break
        print(f"Debug: Found .webm or .webp files, retrying download attempt {attempts}/{max_attempts}")

    if not contains_webm_or_webp(album_folder):
        for root, dirs, files in os.walk(tmp_folder):
            for file in files:
                if file.endswith(".m4a"):
                    file_path = os.path.join(root, file)
                    update_metadata(file_path, artist_name)

        time.sleep(1)
        finished_folder = "music"
        move_to_finished_folder(tmp_folder, finished_folder)
        time.sleep(1)
    else:
        error_folder = get_error_folder_name(tmp_folder)
        os.rename(tmp_folder, error_folder)
        print(f"Error: Failed to download {item_url} after {max_attempts} attempts")

def download_items_in_parallel(item_urls, max_threads):
    semaphore = Semaphore(max_threads)

    def worker(item_data, idx):
        item_url, artist_name = item_data
        tmp_folder = f"tmp{idx}"
        with semaphore:
            download_item(item_url, artist_name, tmp_folder)

    total = len(item_urls)
    open(f"{total}_Albums_are downloaded.txt", 'w').close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        executor.map(worker, item_urls, range(len(item_urls)))
    os.remove(f"{total}_Albums_are downloaded.txt")

# ──────────────────────────────────────────────────────────────────────────────
# ── CLEANUP UTILITIES (NEW) ───────────────────────────────────────────────────

def cleanup_resources(main_driver=None, cookie_thread=None):
    # ── FIX 3: proactively quit the cookie driver before/while joining the thread ──
    global _cookie_driver
    try:
        if main_driver:
            main_driver.quit()
    except Exception:
        pass

    if cookie_thread:
        stop_cookie_refresher.set()

        # try to close the cookie driver to unblock potential network waits
        if _cookie_driver is not None:
            try:
                _cookie_driver.quit()
            except Exception:
                pass

        # wait at most 15 seconds
        if cookie_thread.is_alive():
            cookie_thread.join(timeout=15)

        # still not dead? log & skip deleting the temp dir to avoid races
        if cookie_thread.is_alive():
            print("Warn: cookie refresher didn't stop within 15s – skipping TMP_COOKIE_DIR removal.")
            return

    shutil.rmtree(TMP_COOKIE_DIR, ignore_errors=True)
    _cookie_driver = None
    print("Debug: Cleanup completed.")

# ──────────────────────────────────────────────────────────────────────────────
# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    # Check if logincookies.txt is present
    if not os.path.isfile(COOKIE_BOOT_FILE):
        print(f"Error: Required '{COOKIE_BOOT_FILE}' not found! Aborting.")
        return

    parser = argparse.ArgumentParser(
        description=(
            "YouTube Music Artist Downloader\n\n"
            "Dieses Skript automatisiert das Herunterladen von Musik von YouTube Music für angegebene Künstler.\n"
            "Du kannst:\n"
            "1. Künstler aus 'artists.txt' laden.\n"
            "2. Eine eigene Künstlerliste via '-all' angeben.\n"
            "3. Direkt Alben via '-da' laden.\n\n"
            "Beispiele:\n"
            "  python youtubemusicartistdownloader.py\n"
            "  python youtubemusicartistdownloader.py -all custom_artists.txt\n"
            "  python youtubemusicartistdownloader.py -lat\n"
            "  python youtubemusicartistdownloader.py -t 4\n"
            "  python youtubemusicartistdownloader.py -da Albums.txt\n"
            "  python youtubemusicartistdownloader.py -t 10\n\n"
            "Optionen:"
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        '-lat', '--livealbumtagger',
        action='store_true',
        help="Führt 'livealbumtagger.py' nach dem Download aus (Datei muss existieren)."
    )
    parser.add_argument(
        '-t', '--threads',
        type=int,
        default=1,
        help="Setzt die Anzahl gleichzeitiger Downloads (Default: 1)."
    )
    parser.add_argument(
        '-all', '--artistlinklist',
        type=str,
        help="Benutzerdefinierte Künstlerliste (Format pro Zeile: artist_name, artist_href)."
    )
    parser.add_argument(
        '-da', '--directalbum',
        type=str,
        help="Datei mit Albumliste (Format: artist_name, album_href)."
    )

    args = parser.parse_args()

    # Start cookie refresher in background
    cookie_thread = None
    try:
        cookie_thread = start_cookie_refresher()

        # Wait (briefly) for the first atomic dump to avoid starting with stale cookies
        first_cookie_dump_ready.wait(timeout=10)

        # ── FIX: create the main Selenium driver only now (after cookie check) ──
        global driver
        driver = build_main_driver()

        if args.directalbum:
            album_file = args.directalbum
            albums = []
            try:
                with open(album_file, 'r') as file:
                    for line in file:
                        if line.strip():
                            artist_name, album_href = line.strip().split(",", 1)
                            albums.append((artist_name.strip(), album_href.strip()))

                print(f"Debug: Found {len(albums)} albums in '{album_file}'")

                album_urls = []
                for artist_name, album_href in albums:
                    if album_href.startswith("https://music.youtube.com/"):
                        album_urls.append((album_href, artist_name))
                    else:
                        album_urls.append((f"ytsearch:{album_href}", artist_name))

                download_items_in_parallel(album_urls, args.threads)
            except ValueError:
                print("Error: Invalid format in album file. Each line should be: 'artist_name, album_href'")
            except FileNotFoundError:
                print(f"Error: File '{album_file}' not found!")
            return

        if args.artistlinklist:
            artist_file = args.artistlinklist
            artists = []
            with open(artist_file, 'r') as file:
                for line in file:
                    if line.strip():
                        artist_name, artist_href = line.strip().split(",", 1)
                        artists.append((artist_name.strip(), artist_href.strip()))
        else:
            artists = []
            with open("artists.txt", "r") as file:
                for line in file:
                    artist = line.strip()
                    if artist:
                        encoded_artist = urllib.parse.quote(artist, safe='')
                        artist_name, artist_href = extract_artist_href(encoded_artist, artist)
                        if artist_href:
                            artists.append((artist_name, artist_href))
                        else:
                            print(f"Debug: Kein href für {artist} gefunden!")

        all_hrefs = []

        for artist_name, artist_href in artists:
            print(f"Debug: Processing artist: {artist_name}")
            if artist_href:
                print(f"Debug: Artist href found: {artist_href}")
                driver.get(artist_href)
                time.sleep(1)

                if args.artistlinklist:
                    click_privacy_button()

                albums_section, is_album_href = extract_section_hrefs("Albums")
                if albums_section:
                    if is_album_href:
                        album_hrefs = extract_item_hrefs_from_page()
                    else:
                        album_hrefs = extract_item_hrefs_from_page(albums_section)
                    print(f"Debug: Found {len(album_hrefs)} albums for {artist_name}")
                    all_hrefs.extend([(href, artist_name) for href in album_hrefs])
                else:
                    print("Debug: Albums section not found.")

                driver.get(artist_href)
                time.sleep(1)
                singles_section, is_single_href = extract_section_hrefs("Singles")
                if singles_section:
                    if is_single_href:
                        single_hrefs = extract_item_hrefs_from_page()
                    else:
                        single_hrefs = extract_item_hrefs_from_page(singles_section)
                    print(f"Debug: Found {len(single_hrefs)} singles for {artist_name}")
                    all_hrefs.extend([(href, artist_name) for href in single_hrefs])
                else:
                    print("Debug: Singles section not found.")
            else:
                print("Debug: Artist href not found.")

        print(f"Debug: Total {len(all_hrefs)} albums and singles to download")

        download_items_in_parallel(all_hrefs, args.threads)

        print("Debug: Quitting driver")

        if args.livealbumtagger:
            if os.path.exists('livealbumtagger.py'):
                print("Debug: Running livealbumtagger.py")
                os.system('python livealbumtagger.py -p \"music\"')
            else:
                print("Error: livealbumtagger.py not found!")

    except KeyboardInterrupt:
        print("Interrupted by user – shutting down …")
    finally:
        cleanup_resources(driver, cookie_thread)

if __name__ == "__main__":
    main()
