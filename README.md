# Anime Watcher

<p align="center">
  <img src="assets/anime_watcher_logo.png" alt="Anime Watcher logo" width="180">
</p>

Anime Watcher is a private, local-first Windows anime library organizer and Qt-powered desktop player. It scans folders you choose, organizes episodes by anime and season, remembers playback progress, retrieves optional artwork and details, and provides a modern streaming-style player without uploading your library.

## Highlights

- Organizes episodes into `Anime Title / Season 01 / Title - S01E01 [Sub].mkv`.
- Recognizes common `S01E01`, `Episode 01`, `EP01`, and AnimeHeaven-style filenames.
- Plays common formats including MKV, MP4, WebM, and AVI through Qt's bundled FFmpeg media backend.
- Uses one Qt application window for the library, video, controls, and previews so moving between mixed-DPI monitors and TVs stays smooth.
- Saves playback progress every ten seconds and resumes where you stopped.
- Provides transparent auto-hiding controls that leave embedded subtitles visible.
- Uses a streaming-style control bar with a full-width timeline, click-to-pause, ±10-second buttons, Left/Right arrow seeking, volume, next episode, and current-monitor fullscreen.
- Keeps version, audio, subtitle, playback-speed, and autoplay choices inside the in-player Settings panel.
- Automatically discovers matching `.srt`, `.vtt`, `.ass`, and `.ssa` subtitle files beside an episode. External ASS/SSA tracks use the bundled libass renderer for authored fonts, colors, outlines, positioning, animation, signs, and karaoke timing. Font files placed beside the subtitle or in a neighboring `Fonts` folder are loaded automatically.
- Remembers the selected subtitle track and per-anime subtitle delay, with shortcuts to cycle tracks or shift captions by 0.1 seconds.
- Can generate translated English subtitles locally with Whisper when an episode has none; the one-time model download is about 488 MB, uses the GPU when available, and does not upload the video or require an API key.
- Shows the real source quality in Settings and switches between actual local 1080p/720p/etc. copies when more than one exists; it never labels upscaling as higher quality.
- Marks embedded Intro/Opening, Recap, Ending/Outro, and Filler/Preview chapters on the timeline and offers the matching Skip action only while that section is playing.
- Automatically prepares timeline thumbnails and shows frame previews while hovering or scrubbing.
- Groups separate Sub and Dub files as variants of the same episode.
- Shows one picker row per episode, starts with Sub by default, and remembers a per-anime language preference after you switch versions.
- Detects Sub/Dub from filename labels and embedded stream language tags, then conservatively infers matching unlabeled variants without uploading audio.
- Keeps next/previous/autoplay on the current version when possible and warns before switching versions.
- Renames anime, seasons, episodes, and Sub/Dub labels without losing watch progress.
- Includes a searchable file manager for correcting anime, season, episode, and Sub/Dub identification.
- Supports customizable player shortcuts and same-window picture-in-picture mode.
- Supports multiple local profiles, each with separate library settings, progress, preferences, and integrations; the original database remains the Default profile.
- Optionally links exact anime to AniList, syncs completed episode progress and list status/score, and shows official airing schedule notifications. AniList does not publish dub air dates, so Dub notifications come from newly discovered local Dub files rather than guessed schedules.
- Refreshes posters, official names, and synopsis details after an anime is renamed.
- Moves deleted episodes to the Windows Recycle Bin after confirmation.
- Searches user-supplied public catalog pages and opens episode pages in your browser.
- Imports local files/folders and downloads user-authorized direct media URLs before organizing them.

Anime Watcher does not bypass DRM, defeat access controls, or download media without permission.

## Install on Windows

1. Open the repository's **Releases** page and download `Anime-Watcher-v1.0.1-Windows.zip`.
2. Install FFmpeg for timeline previews:

   ```powershell
   winget install Gyan.FFmpeg
   ```

3. Extract the entire ZIP. Do not run the executable from inside the ZIP.
4. Open the extracted `Anime Watcher` folder and run `Anime Watcher.exe`.
5. Open **Settings**, choose your anime library folder, save, and refresh the library.

The library location starts empty. Anime Watcher does not create or scan a drive until you choose a folder.

Automatic English subtitle generation is optional. Install a Windows build of
[whisper.cpp](https://github.com/ggml-org/whisper.cpp/releases); if Anime Watcher cannot find
`whisper-cli.exe`, it will ask you to choose it. The first generation asks before downloading
the official model, and later episodes run locally without another model download.

The application is currently unsigned, so Windows SmartScreen may show a warning on first launch. Choose **More info** and **Run anyway** only when the file came from this repository's official release.

See [INSTALL.md](INSTALL.md) for detailed setup and troubleshooting.

## Privacy and library safety

- Episodes are never included with the application or uploaded by Anime Watcher.
- Your selected anime folder remains wherever you placed it.
- No drive or library folder is selected automatically on first launch.
- Runtime state is stored locally in `%APPDATA%\AnimeWatcher`.
- AniList is opt-in. Its access token is protected with Windows DPAPI for the current Windows account and is never stored as plain text.
- The repository excludes video extensions, databases, downloads, caches, posters, build output, cookies, and environment files.
- Metadata lookup sends only an anime title to supported public metadata services.
- Imported subtitle files stay beside their episode. Automatic transcription runs locally; only the optional Whisper model itself is downloaded.
- The bundled libass runtime renders subtitle pixels into the same Qt graphics scene as the video. It does not create a second native playback or overlay window.

## Run from source

Requirements: Windows 10/11, Python 3.11 or newer, and FFmpeg.

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

The current development build uses a single Qt window and preserves existing library, metadata, Sub/Dub, downloader, and playback data. Features under test for the next release are listed in [CHANGELOG.md](CHANGELOG.md).
