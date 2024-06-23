# YouTube-Music-Artist-Downloader
The goal of this script is, to build up a new database of music of my most wanted Artists. It is made for Arch but will work on other systems as well, by modifying the dependencies for selenium.

The script uses Selenium to scrape the YouTube Music Website and it uses yt-dlp to download the music.

How it works:
1. Create a folder for the script and the input file
2. Download the file and create a file called `artist.txt` and put it in said folder
3. Fill the `artist.txt` with the artist you want to download. For every artist use an new line.
Exampel:
```
Townes van Zandt
Seeed
ACDC
```
4. Install all dependencies of the script:<br />

python-libs:<br />
- selenium (https://aur.archlinux.org/packages/python-selenium)
- mutagen (https://archlinux.org/packages/extra/any/python-mutagen/)

System-packages:<br />
- google-chrome (https://aur.archlinux.org/packages/google-chrome)
- chromedriver (https://aur.archlinux.org/packages/chromedriver)
- yt-dlp (https://archlinux.org/packages/extra/any/yt-dlp/)
- python (https://archlinux.org/packages/core/x86_64/python/)

5. Open terminal in folder
6. Start the script with the command `python musicscraper.py`

The script will download all albums and singles of the artists in `artist.txt` and save into the subfolder `music` in the following structure: /album_artist/album/title.m4a including all metadata and the albumcover.

Have fun with the script.
