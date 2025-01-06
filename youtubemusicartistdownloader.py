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
from mutagen.easymp4 import EasyMP4
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from threading import Thread, Semaphore

# Pfad zu deinem ChromeDriver
chromedriver_path = '/usr/bin/chromedriver'

# Funktion, um den User-Agent zu erfassen
def get_user_agent(chromedriver_path):
    # Setze die Optionen für den temporären Chrome-Browser
    temp_options = Options()
    temp_options.add_argument("--headless")
    temp_options.add_argument("--no-sandbox")
    temp_options.add_argument("--disable-dev-shm-usage")

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
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument(f'user-agent={user_agent}')

# Initialisiere den Webdriver mit dem erfassten User-Agent
service = Service(chromedriver_path)
driver = webdriver.Chrome(service=service, options=chrome_options)

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

def similarity_ratio(str1, str2):
    return difflib.SequenceMatcher(None, str1, str2).ratio()

def extract_artist_href(search_term, artist):
    youtube_music_search_link = f"https://music.youtube.com/search?q={search_term}"
    print(f"Debug: Loading search page: {youtube_music_search_link}")
    driver.get(youtube_music_search_link)
    time.sleep(1)  # Wartezeit, um sicherzustellen, dass die Seite vollständig geladen ist
    click_privacy_button()  # Datenschutzbutton klicken
    #save_page_source('search_page.html')  # Speichern der geladenen Suchseite für Debugging

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
            # Versuchen, den <a>-Tag mit dem Abschnittsnamen zu finden
            link_element = section.find_element(By.XPATH, f"//yt-formatted-string[contains(@class, 'title text style-scope ytmusic-carousel-shelf-basic-header-renderer') and .//a[contains(@href, 'browse/') and contains(text(), '{section_name}')]]//a")
            href = link_element.get_attribute('href')
            print(f"Debug: Found {section_name} section with href: {href}")
            link_element.click()  # Klick auf das Link-Element
            time.sleep(1)  # Kurze Wartezeit, um sicherzustellen, dass die Aktion abgeschlossen ist
            return section, True
        except Exception:
            print(f"Debug: No <a> tag found for {section_name}.")
            try:
                # Wenn kein <a>-Tag gefunden wird, versuchen, den <yt-formatted-string>-Tag zu finden
                title_element = section.find_element(By.XPATH, f'.//yt-formatted-string[contains(text(), "{section_name}")]')
                print(f"Debug: Found {section_name} section without href")
                return section, False
            except Exception:
                print(f"Debug: No <yt-formatted-string> tag found for {section_name}.")
                continue
    print(f"Debug: {section_name} section not found.")
    return None, False


def scroll_to_bottom(driver, scroll_pause_time=2):
    """
    Scrolls to the bottom of the page to load all elements.
    :param driver: Selenium WebDriver instance.
    :param scroll_pause_time: Time to wait for the new elements to load after each scroll.
    :param max_scrolls: Maximum number of scrolls to avoid infinite loops.
    """
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        # Scroll to the bottom
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(scroll_pause_time)  # wait for new content to load

        # Check new height after scrolling
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
    print("Debug: Scrolling completed or maximum scroll count reached.")

def extract_item_hrefs_from_page(section=None):
    if section is None:
        # Scroll to the bottom of the page to load all items
        scroll_to_bottom(driver)

        # After scrolling, collect all the item links
        item_elements = driver.find_elements(By.CSS_SELECTOR, 'a.yt-simple-endpoint.image-wrapper.style-scope.ytmusic-two-row-item-renderer')
    else:
        # Scroll within a specific section if provided
        scroll_to_bottom(driver)

        # After scrolling, collect all the item links from the section
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
    # Get the path of the deepest folder in src_folder
    deepest_folder = get_deepest_folder(src_folder)
    print(f"Debug: Deepest folder in src_folder: {deepest_folder}")

    # Check if the corresponding path exists in dest_folder
    relative_path = os.path.relpath(deepest_folder, src_folder)
    dest_deepest_folder = os.path.join(dest_folder, relative_path)
    print(f"Debug: Checking for deepest folder in dest_folder: {dest_deepest_folder}")

    if os.path.exists(dest_deepest_folder):
        # Count the number of files in both the src and dest deepest folders
        src_file_count = count_files(deepest_folder)
        dest_file_count = count_files(dest_deepest_folder)

        # Determine which folder has fewer files and rename it
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

def move_to_finished_folder(src_folder, dest_folder):
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    handle_album_conflicts(src_folder, dest_folder)

    for root, dirs, files in os.walk(src_folder, topdown=False):
        # Ensure the destination directories exist
        for name in dirs:
            dest_dir = os.path.join(dest_folder, os.path.relpath(os.path.join(root, name), src_folder))
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir)

        # Move all files
        for name in files:
            src_file = os.path.join(root, name)
            dest_file = os.path.join(dest_folder, os.path.relpath(src_file, src_folder))
            dest_dir = os.path.dirname(dest_file)
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir)
            shutil.move(src_file, dest_file)

    # Remove empty directories
    shutil.rmtree(src_folder)

    print(f"Debug: Moved {src_folder} to {dest_folder}")

def sanitize_filename(name):
    """
    Sanitize a string so it could be used as part of a filename.
    """
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
        if char in '!&\'()[]{}$;`^,#' or char.isspace() or ord(char) > 127:
            return '' if unicodedata.category(char)[0] in 'CM' else '_'
        return char

    # Replace look-alike Unicode glyphs
    name = unicodedata.normalize('NFKC', name)
    name = re.sub(r'[0-9]+(?::[0-9]+)+', lambda m: m.group(0).replace(':', '_'), name)  # Handle timestamps
    result = ''.join(map(replace_insane, name))
    result = re.sub(r'(\0.)(?:(?=\1)..)+', r'\1', result)  # Remove repeated substitute chars
    STRIP_RE = r'(?:\0.|[ _-])*'
    result = re.sub(f'^\0.{STRIP_RE}|{STRIP_RE}\0.$', '', result)  # Remove substitute chars from start/end
    result = result.replace('\0', '') or '_'

    while '__' in result:
        result = result.replace('__', '_')
    result = result.strip('_')
    # Common case of "Foreign band name - English song title"
    if result.startswith('-_'):
        result = result[2:]
    if result.startswith('-'):
        result = '_' + result[len('-'):]
    result = result.lstrip('.')
    if not result:
        result = '_'

    return result

def download_item(item_url, artist_name, tmp_folder):
    sanitized_artist_name = sanitize_filename(artist_name)

    if not os.path.exists(tmp_folder):
        os.makedirs(tmp_folder)

    def run_download():
        command = [
            "yt-dlp",
            "--retries", "5",
            "--retry-sleep",  "5",
            "--concurrent-fragments", "10",
            "-f", "bestaudio",
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

    # Update metadata and move files if download was successful
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

def main():
    parser = argparse.ArgumentParser(
        description=(
            "YouTube Music Artist Downloader\n\n"
            "This script automates downloading music from YouTube Music for specified artists.\n"
            "You can:\n"
            "1. Download music by reading artist names from 'artists.txt'.\n"
            "2. Provide a custom artist list file using '-all'.\n"
            "3. Directly download an album using '-da'.\n\n"
            "Usage examples:\n"
            "  python youtubemusicartistdownloader.py\n"
            "  python youtubemusicartistdownloader.py -all custom_artists.txt\n"
            "  python youtubemusicartistdownloader.py -lat\n"
            "  python youtubemusicartistdownloader.py -t 4\n"
            "  python youtubemusicartistdownloader.py -da \"Various Artists, https://music.youtube.com/playlist?list=OLAK5uy_example\"\n\n"
            "Options:"
        ),
        formatter_class=argparse.RawTextHelpFormatter
    )

    # Argumente definieren
    parser.add_argument(
        '-lat', '--livealbumtagger',
        action='store_true',
        help="Run the 'livealbumtagger.py' script after downloading. Requires 'livealbumtagger.py' in the script directory."
    )
    parser.add_argument(
        '-t', '--threads',
        type=int,
        default=1,
        help="Set the number of concurrent downloads (default: 1)."
    )
    parser.add_argument(
        '-all', '--artistlinklist',
        type=str,
        help="Provide a custom artist list file in the format: artist_name, artist_href."
    )
    parser.add_argument(
        '-da', '--directalbum',
        type=str,
        help="Directly download a single album. Format: 'artist_name, album_href'."
    )
    args = parser.parse_args()

    if args.directalbum:
        # Verarbeite die direkte Album-Flag
        try:
            artist_name, album_href = args.directalbum.split(",", 1)
            artist_name = artist_name.strip()
            album_href = album_href.strip()
            print(f"Debug: Direct album download for artist '{artist_name}' with URL '{album_href}'")

            # Starte den Download-Prozess direkt
            download_items_in_parallel([(album_href, artist_name)], args.threads)
        except ValueError:
            print("Error: Invalid format for --directalbum. Use: 'artist_name, album_href'")
        return  # Beende das Skript nach dem direkten Album-Download

    if args.artistlinklist:
        # Wenn die -all Flag gesetzt ist, lese die benutzerdefinierte Datei ein
        artist_file = args.artistlinklist
        artists = []
        with open(artist_file, 'r') as file:
            for line in file:
                # Jede Zeile enthält artist_name und artist_href, getrennt durch ein Komma
                artist_name, artist_href = line.strip().split(",", 1)
                artists.append((artist_name.strip(), artist_href.strip()))
    else:
        # Ansonsten wird die Standarddatei "artists.txt" verwendet
        artists = []
        with open("artists.txt", "r") as file:
            for line in file:
                artist = line.strip()
                if artist:
                    # Hier wird extract_artist_href aufgerufen, um den artist_href für jeden Künstler zu extrahieren
                    encoded_artist = urllib.parse.quote(artist, safe='')
                    artist_name, artist_href = extract_artist_href(encoded_artist, artist)
                    if artist_href:  # Wenn der href erfolgreich extrahiert wurde
                        artists.append((artist_name, artist_href))
                    else:
                        print(f"Debug: Kein href für {artist} gefunden!")

    all_hrefs = []  # Liste zur Sammlung aller Album-Hyperlinks mit zugehörigem Künstlernamen

    for artist_name, artist_href in artists:
        print(f"Debug: Processing artist: {artist_name}")
        if artist_href:
            print(f"Debug: Artist href found: {artist_href}")
            driver.get(artist_href)
            time.sleep(1)

            # Falls die -all Flag gesetzt ist, rufe die Methode click_privacy_button auf
            if args.artistlinklist:
                click_privacy_button()  # Diese Methode wird nach dem Laden der Seite aufgerufen

            #save_page_source('artist_page.html')  # Speichern der geladenen Künstlerseite für Debugging

            # Process Albums
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

            # Process Singles
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

    # Download all albums and singles in parallel
    download_items_in_parallel(all_hrefs, args.threads)

    print("Debug: Quitting driver")
    driver.quit()

    # Check if the livealbumtagger flag is active
    if args.livealbumtagger:
        if os.path.exists('livealbumtagger.py'):
            print("Debug: Running livealbumtagger.py")
            os.system('python livealbumtagger.py -p "music"')
        else:
            print("Error: livealbumtagger.py not found!")

if __name__ == "__main__":
    main()
