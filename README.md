# YouTube-Music-Artist-Downloader

NOTE: THE SCRIPT CURRENTLY ONLY WORKS IN GERMANY DUE TO STRING-CHECKS IN THE SCRIPT

The goal of this script is to build up a new database of music from my most wanted artists. It is made for Arch but will work on other systems as well, by modifying the dependencies for selenium.

The script uses Selenium to scrape the YouTube Music Website and yt-dlp to download the music.

## How it works:

1. Create a folder for the script and the input file.
2. Download the script and create a file called `artist.txt` and put it in the folder.
3. Fill the `artist.txt` with the artists you want to download. For every artist, use a new line. Example:
   ```
   Townes van Zandt
   Seeed
   ACDC
   ```
4. Install all dependencies of the script:
   - **Python libraries:**
     - selenium (https://aur.archlinux.org/packages/python-selenium)
     - mutagen (https://archlinux.org/packages/extra/any/python-mutagen/)
   - **System packages:**
     - google-chrome (https://aur.archlinux.org/packages/google-chrome)
     - chromedriver (https://aur.archlinux.org/packages/chromedriver)
     - yt-dlp (https://archlinux.org/packages/extra/any/yt-dlp/)
     - python (https://archlinux.org/packages/core/x86_64/python/)
5. Open terminal in the folder.
6. Start the script with the command `python youtubemusicartistdownloader.py`.

The script will download all albums and singles of the artists in `artist.txt` and save them into the subfolder `music` in the following structure: `/album_artist/album/title.m4a` including all metadata and the album cover.

## Features

### Integration of livealbumtagger.py

You can now use the `livealbumtagger.py` script by adding a flag when running the main script. This will allow you to tag live albums specifically.

Usage:
```
python youtubemusicartistdownloader.py --livealbumtagger
```
or:
```
python youtubemusicartistdownloader.py -lat
```

### Multithreading/concurrent downloads

You can download multiple albums in parallel. This makes the script much faster.

Usage:
```
python youtubemusicartistdownloader.py --threads 10
```
or:
```
python youtubemusicartistdownloader.py -t 10
```

Have fun with the script.
