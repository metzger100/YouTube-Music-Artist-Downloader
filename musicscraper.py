import difflib
import os
import shutil
import subprocess
import time
import urllib.parse
from mutagen.easymp4 import EasyMP4
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# Pfad zu deinem ChromeDriver
chromedriver_path = '/usr/bin/chromedriver'

# Setze die Optionen für den Chrome-Browser
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

# Setze den User-Agent
user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
chrome_options.add_argument(f'user-agent={user_agent}')

# Initialisiere den Webdriver
service = Service(chromedriver_path)
driver = webdriver.Chrome(service=service, options=chrome_options)

def save_page_source(filename):
    with open(filename, 'w', encoding='utf-8') as file:
        file.write(driver.page_source)

def click_privacy_button():
    try:
        button = driver.find_element(By.XPATH, '//button[@aria-label="Alle ablehnen"]')
        button.click()
        time.sleep(2)  # Kurze Wartezeit, um sicherzustellen, dass die Aktion abgeschlossen ist
        print("Debug: 'Alle ablehnen' button clicked successfully.")
    except Exception as e:
        print(f"Debug: Privacy button not found or could not be clicked: {e}")

def similarity_ratio(str1, str2):
    return difflib.SequenceMatcher(None, str1, str2).ratio()

def extract_artist_href(search_term, artist):
    youtube_music_search_link = f"https://music.youtube.com/search?q={search_term}"
    print(f"Debug: Loading search page: {youtube_music_search_link}")
    driver.get(youtube_music_search_link)
    time.sleep(2)  # Wartezeit, um sicherzustellen, dass die Seite vollständig geladen ist
    click_privacy_button()  # Datenschutzbutton klicken
    # save_page_source('search_page.html')  # Speichern der geladenen Suchseite für Debugging

    artist_elements = driver.find_elements(By.CSS_SELECTOR, 'a.yt-simple-endpoint.thumbnail-link')
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
            # First, check if there is an <a> tag with the section name (href-Titelklasse)
            link_element = section.find_element(By.XPATH, f'.//a[contains(text(), "{section_name}")]')
            href = link_element.get_attribute('href')
            print(f"Debug: Found {section_name} section with href: {href}")
            link_element.click()  # Click on the link element
            time.sleep(2)  # Kurze Wartezeit, um sicherzustellen, dass die Aktion abgeschlossen ist
            return section, True
        except Exception:
            try:
                # If no href-Titelklasse, check for yt-formatted-string with the section name
                title_element = section.find_element(By.XPATH, f'.//yt-formatted-string[contains(text(), "{section_name}")]')
                print(f"Debug: Found {section_name} section without href")
                return section, False
            except Exception as e:
                continue
    print(f"Debug: {section_name} section not found.")
    return None, False

def extract_item_hrefs_from_page(section=None):
    if section is None:
        item_elements = driver.find_elements(By.CSS_SELECTOR, 'a.yt-simple-endpoint.image-wrapper.style-scope.ytmusic-two-row-item-renderer')
    else:
        item_elements = section.find_elements(By.CSS_SELECTOR, 'a.yt-simple-endpoint.image-wrapper.style-scope.ytmusic-two-row-item-renderer')

    print(f"Debug: Found {len(item_elements)} elements in the specified section with selector 'a.yt-simple-endpoint.image-wrapper.style-scope.ytmusic-two-row-item-renderer'")

    item_hrefs = []
    for element in item_elements:
        href = element.get_attribute('href')
        if "browse/" in href:
            item_hrefs.append(href)
            print(f"Debug: Item href added: {href}")

    print(f"Debug: Total number of items found: {len(item_hrefs)}")
    return item_hrefs

def read_artists(filename):
    with open(filename, 'r', encoding='utf-8') as file:
        return [line.strip() for line in file if line.strip()]

def update_metadata(file_path, album_artist):
    audio = EasyMP4(file_path)
    audio['albumartist'] = album_artist
    audio.save()
    print(f"Debug: Updated metadata with album artist {album_artist} for {file_path}")

def move_to_finished_folder(src_folder, dest_folder):
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)
    for item in os.listdir(src_folder):
        s = os.path.join(src_folder, item)
        d = os.path.join(dest_folder, item)
        shutil.move(s, d)
    print(f"Debug: Moved {src_folder} to {dest_folder}")

def download_item(item_url, artist_name):
    music_folder = "tmp"
    if not os.path.exists(music_folder):
        os.makedirs(music_folder)
    command = [
        "yt-dlp",
        "-f", "bestaudio",
        "--extract-audio",
        "--parse-metadata", "release_year:(?s)(?P<meta_date>.+)",
        "--audio-format", "m4a",
        "--embed-metadata",
        "--add-metadata",
        "--embed-thumbnail",
        "--output", os.path.join(music_folder, "%(artist)s/%(album)s/%(title)s.%(ext)s"),
        item_url
    ]
    subprocess.run(command)

    # Update metadata and move files
    artist_folder = os.path.join(music_folder, artist_name)
    for root, dirs, files in os.walk(artist_folder):
        for file in files:
            if file.endswith(".m4a"):
                file_path = os.path.join(root, file)
                update_metadata(file_path, artist_name)

    time.sleep(2)
    finished_folder = os.path.join("music", artist_name)
    move_to_finished_folder(artist_folder, finished_folder)
    time.sleep(2)

def main():
    artists = read_artists("artists.txt")
    for artist in artists:
        print(f"Debug: Processing artist: {artist}")
        encoded_artist = urllib.parse.quote(artist)
        artist_name, artist_href = extract_artist_href(encoded_artist, artist)
        if artist_href:
            print(f"Debug: Artist href found: {artist_href}")
            driver.get(artist_href)
            time.sleep(2)
            # save_page_source('artist_page.html')  # Speichern der geladenen Künstlerseite für Debugging

            # Process Albums
            albums_section, is_album_href = extract_section_hrefs("Alben")
            if albums_section:
                if is_album_href:
                    album_hrefs = extract_item_hrefs_from_page()
                else:
                    album_hrefs = extract_item_hrefs_from_page(albums_section)
                for album_href in album_hrefs:
                    youtube_music_album = f"{album_href}"
                    print("Album Link:", youtube_music_album)
                    download_item(youtube_music_album, artist_name)
            else:
                print("Debug: Albums section not found.")

            # Process Singles
            singles_section, is_single_href = extract_section_hrefs("Singles")
            if singles_section:
                if is_single_href:
                    single_hrefs = extract_item_hrefs_from_page()
                else:
                    single_hrefs = extract_item_hrefs_from_page(singles_section)
                for single_href in single_hrefs:
                    youtube_music_single = f"{single_href}"
                    print("Single Link:", youtube_music_single)
                    download_item(youtube_music_single, artist_name)
            else:
                print("Debug: Singles section not found.")
        else:
            print("Debug: Artist href not found.")
    print("Debug: Quitting driver")
    driver.quit()

if __name__ == "__main__":
    main()