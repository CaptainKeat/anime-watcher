# Anime Watcher

<p align="center">
  <img src="assets/anime_watcher_logo.png" alt="Anime Watcher logo" width="180">
</p>

Anime Watcher is a private, local-first Windows anime library organizer and VLC-powered desktop player. It scans folders you choose, organizes episodes by anime and season, remembers playback progress, retrieves optional artwork and details, and provides a modern streaming-style player without uploading your library.

## Highlights

- Organizes episodes into `Anime Title / Season 01 / Title - S01E01 [Sub].mkv`.
- Recognizes common `S01E01`, `Episode 01`, `EP01`, and AnimeHeaven-style filenames.
- Plays VLC-supported formats including MKV, MP4, WebM, and AVI.
- Saves playback progress every ten seconds and resumes where you stopped.
- Provides transparent auto-hiding controls that leave embedded subtitles visible.
- Supports click-to-pause, previous/next episode, ±10 seconds, autoplay, speed, volume, audio tracks, subtitle tracks, and current-monitor fullscreen.
- Automatically prepares timeline thumbnails and shows frame previews while hovering or scrubbing.
- Groups separate Sub and Dub files as variants of the same episode.
- Renames anime, seasons, episodes, and Sub/Dub labels without losing watch progress.
- Refreshes posters, official names, and synopsis details after an anime is renamed.
- Moves deleted episodes to the Windows Recycle Bin after confirmation.
- Searches user-supplied public catalog pages and opens episode pages in your browser.
- Imports local files/folders and downloads user-authorized direct media URLs before organizing them.

Anime Watcher does not bypass DRM, defeat access controls, or download media without permission.

## Install on Windows

1. Open the repository's **Releases** page and download `Anime-Watcher-v1.0.0-Windows.zip`.
2. Install [VLC Media Player](https://www.videolan.org/vlc/) in its standard 64-bit location.
3. Install FFmpeg for timeline previews:

   ```powershell
   winget install Gyan.FFmpeg
   ```

4. Extract the entire ZIP. Do not run the executable from inside the ZIP.
5. Open the extracted `Anime Watcher` folder and run `Anime Watcher.exe`.
6. Open **Settings**, choose your anime library folder, save, and refresh the library.

The library location starts empty. Anime Watcher does not create or scan a drive until you choose a folder.

The application is currently unsigned, so Windows SmartScreen may show a warning on first launch. Choose **More info** and **Run anyway** only when the file came from this repository's official release.

See [INSTALL.md](INSTALL.md) for detailed setup and troubleshooting.

## Privacy and library safety

- Episodes are never included with the application or uploaded by Anime Watcher.
- Your selected anime folder remains wherever you placed it.
- No drive or library folder is selected automatically on first launch.
- Runtime state is stored locally in `%APPDATA%\AnimeWatcher`.
- The repository excludes video extensions, databases, downloads, caches, posters, build output, cookies, and environment files.
- Metadata lookup sends only an anime title to supported public metadata services.

## Run from source

Requirements: Windows 10/11, Python 3.11 or newer, VLC, and FFmpeg.

```powershell
git clone https://github.com/CaptainKeat/anime-watcher.git
cd anime-watcher
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

## Build the Windows application

With the virtual environment activated:

```powershell
.\build.ps1
```

The packaged app is written to `dist\Anime Watcher\Anime Watcher.exe`.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## Organizer CLI

The CLI performs a dry run unless `--execute` is supplied:

```powershell
python cli.py "C:\Path\To\Downloads" --library "D:\Anime"
python cli.py "C:\Path\To\Downloads" --library "D:\Anime" --execute
```

Duplicate files are never overwritten. Exact duplicates are reported, and conflicting filenames receive `(2)`, `(3)`, and so on.

## Project status

Version 1.0.0 is the first packaged GitHub release. See [CHANGELOG.md](CHANGELOG.md) for release details.
