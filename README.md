# Anime Watcher

<p align="center">
  <img src="assets/anime_watcher_logo.png" alt="Anime Watcher logo" width="180">
</p>

Anime Watcher is a private, local-first Windows anime library organizer and Qt-powered desktop player. It scans folders you choose, organizes episodes by anime and season, remembers playback progress, retrieves optional artwork and details, and provides a modern streaming-style player without uploading your library.

## Highlights

- Organizes episodes into `Anime Title / Season 01 / Title - S01E01 [Sub].mkv`.
- Bulk moves selected episodes into an existing or new anime and season while preserving watch progress, subtitles, and quality versions.
- Recognizes common `S01E01`, `Episode 01`, `EP01`, and release filenames.
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
- **Schedule** opens with **Current airings**, showing this week's confirmed episode releases across anime, including shows outside your library. Switch between Week/Month, filter by show, select a day for episode details, and open AniList pages. **My library** shows linked shows; saved schedules remain available offline and notifications are under **Recent activity**. Optional AniList linking also syncs completed episode progress and list status/score. AniList does not publish dub air dates, so Dub notifications come from newly discovered local Dub files rather than guessed schedules.
- Refreshes posters, official names, and synopsis details after an anime is renamed.
- Moves deleted episodes to the Windows Recycle Bin after confirmation.
- Searches user-supplied public catalog pages and opens episode pages in your browser.
- Imports local files/folders and downloads user-authorized direct media URLs before organizing them.
- Downloads individual YouTube videos and Shorts into the library with quality choices, progress, and cancellation.

To merge a separately named season, open that anime and click **Move episodes…**.
Choose the existing destination anime, set the season, and click **Move episodes**.
All files start selected; use the source-season filter or checkboxes for a smaller
batch. Episode numbers stay the same unless **Renumber episodes** is checked.
The **Files** page also has checkboxes, **Select shown**, and **Move selected**.
The preview checks all destination slots and companion files before enabling the
move. Conflicts preserve existing files; failed batches roll back together.

Anime Watcher does not bypass DRM, defeat access controls, or download media without permission.

The checkbox at the top of **Downloads** saves your permission confirmation for the
current profile, covering YouTube and other supported video downloads. It starts unchecked; tick
it once to cover future downloads, or untick it to block new downloads until you
confirm again. Downloads already started can finish.

**Downloads → Downloads** lists every job with its title, anime thumbnail, release
year, source, profile, status, progress, and Cancel button. Artwork and years load
in the background and are reused across a season. Unavailable years are labeled.
The sidebar and tab show the number active and queued.
The simultaneous-download setting controls how many jobs run; additional jobs wait
in the queue. Progress continues when you change pages. Integrated player windows
stay in the background; **Open player**
lets you inspect one if it needs help. Completed, failed, and cancelled entries stay
until **Clear finished entries**; clearing entries does not delete files. Queue
history survives restarts, though interrupted transfers do not resume automatically.
The downloader retries quality selection and reloads the player once if it cannot confirm the
highest available quality. Persistent failures and transfers with no progress for
two minutes release their slot so other jobs can continue. **Retry** resets the
existing download entry and retains its attempt history. It uses the original profile and
requires that profile's permission checkbox. Local `download-queue.json` snapshots
record public episode pages, statuses, and quality choices for troubleshooting;
temporary media URLs and browser cookies are excluded.

For a full season, select a season and the **Sub** or **Dub** tab, then click
**Download season**. For a smaller batch, tick episode checkboxes or use **Select
all**, then **Download selected**. Both actions use the current version tab and
season filter and queue episodes in order. **Skip episodes already in library**
starts checked; untick it to include existing episodes for quality upgrades.
Other language versions do not count as existing copies. Already queued episodes
and duplicate links are skipped; special episodes needing a manual library slot
cannot be selected in bulk. Progress, Cancel, and Retry stay in the Downloads tab,
with simultaneous transfers controlled by the saved queue setting.

The Downloads screen shows transfer speed and estimated time remaining. Its
**Simultaneous downloads** setting accepts 1–6: use 1 to give one episode the
available bandwidth, or increase it for multiple episodes. Reducing the setting
lets active transfers finish before starting more. It is remembered per profile
and controls the whole session queue, including jobs from other profiles.
The downloader releases the player's preview stream once the video download is accepted.
It stages files in `.anime-watcher-downloads` inside the selected library so
verified imports can move on the same volume, and indexes only the completed
episode. Library scans exclude that staging folder; failed or cancelled files
remain there for inspection. Quality selection and FFprobe verification still
apply. Transfer speeds depend on the host and shared bandwidth; more connections
do not always improve them.

Verification and import release the transfer slot as soon as the video finishes
downloading, so the next episode can start while the previous one is checked and
added. The queue pauses admission if two imports are pending, keeping slow disks
from accumulating work. The Downloads summary counts active transfers and importing
episodes separately. Failed verification never marks a video as added.
Near the end of a transfer, the downloader can prepare one queued episode's normal player and
highest-quality selection in advance. It stays queued until a transfer slot opens,
releases its preview buffer when ready, and reloads selections older than 30 seconds.
The source player's announcements still apply.
Completed entries have green bars and cards; failed entries have red bars and cards.
The summary includes a failed count. **Retry** resets the same download block and puts
it behind already queued episodes. Finished history and retry reasons survive
restarts, while retry still requires the original profile, library, and permission.
The downloader makes up to four automatic attempts for player selection, stalled/interrupted
transfers, and invalid or lower-resolution saved files. Rejected files are retained;
disk/import errors and user cancellation are not automatically retried.
When Qt cannot decode the selected video, its preview stops before the player can
replace it with an error clip. The selected source is retained for the download;
FFprobe still checks its actual resolution before library import.

Use **Downloads → Download a YouTube video**: paste a video or Shorts link, choose
Best available or a resolution limit, confirm download permission, and click
**Download YouTube video**. Completed videos appear in your library. You can leave
the page during a download and return to check progress or cancel. Each attempt
uses a separate folder under the app's Downloads directory; failed or cancelled
partial files are retained there. Playlist parameters on a video link are ignored;
channel links, playlist-only links, and live/upcoming broadcasts are not downloaded.

**Add to series** defaults to matching the video title to an existing series, then
its saved YouTube channel. Episode labels in titles (including `Episode 10`, `S02E03`,
and `#10`) determine the slot; otherwise the app uses the next episode. Choose an
existing series or type a new name to override grouping, and set Season/Episode to
override numbering. A channel associated with several series is not an automatic
match by itself. An occupied slot is reported instead of overwriting an episode.

For existing files, choose **Move to series** on the episode row, in **Manage versions**,
or in **Files**. Select a series (or type a new one) and check the suggested slot.
Watch progress, sidecar subtitles, and saved YouTube channel information follow the
file. Older downloads can match by title; their channel information is learned when
a new download is matched. Small `.youtube.json` files beside new videos retain the
public title, video ID, channel, and source URL for future grouping.

YouTube support uses [yt-dlp](https://github.com/yt-dlp/yt-dlp), bundled in Windows
builds. Install the project requirements for source runs. A supported local
[Deno or Node.js runtime](https://github.com/yt-dlp/yt-dlp/wiki/EJS) is needed for
current YouTube extraction; the app detects these on PATH. FFmpeg enables separate
video/audio streams and higher resolutions; without it, the app requests a combined
video/audio file, which may have fewer quality options. Resolution choices are
maximums: the available source can be lower. No browser cookies are read or stored.

## Install on Windows

1. Open the repository's **Releases** page and download `Anime-Watcher-v1.1.8-Windows.zip`.
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

## Update Anime Watcher

In updater-enabled builds, **Application updates** is at the top of **Settings**. Choose
**Check now**. Anime Watcher also checks at startup and every six hours by default;
automatic checks can be disabled in Settings. A blue **Update available** button
appears in the sidebar when a newer stable release is found. Click it to download
and install, or use **Download & install** in Settings. One click starts the whole
update, with a download bar and loading indicator in the sidebar and Settings.
The app installs and reopens automatically without confirmation dialogs. Errors
and installation results appear inline; a failed installer startup offers
**Restart to update** to retry the verified package. The app downloads the exact versioned Windows ZIP from
the official `CaptainKeat/anime-watcher` release, verifies the SHA-256 digest
reported by GitHub, stages it beside the current application, closes, keeps the
previous application folder as a rollback backup, installs, and reopens.

Profiles, watch history, settings, posters, previews, and the selected anime
library are stored outside the application folder and are not moved by an update.
The app is not code-signed; SHA-256 verification detects a damaged or mismatched
GitHub asset but is not a substitute for a publisher signature.

Version 1.1.0 is the first build with the in-app updater. Anyone using v1.0.1 or
older must download and extract an updater-enabled release manually once. Later stable releases can
then be installed from Settings.

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

To build the updater-compatible release ZIP and its local SHA-256 manifest after
setting the new semantic version in `anime_watcher/__init__.py`, run:

```powershell
.\package-release.ps1
```

Publish the generated `Anime-Watcher-vX.Y.Z-Windows.zip` under the matching
stable GitHub tag `vX.Y.Z`. The updater deliberately ignores drafts,
prereleases, differently named assets, and releases without GitHub's SHA-256
digest metadata.

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

Version 1.1.8 uses a single Qt window and preserves existing library, metadata, Sub/Dub, downloader, and playback data. Future work is listed under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).
