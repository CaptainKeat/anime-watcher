# Changelog

## Unreleased

## 1.1.18 — 2026-10-09

- Home focuses on Continue watching and Up next; remove the duplicate Your collection section.
- Show at most 12 Up next episodes in total, with anime posters or wide YouTube thumbnails inside each card. Click the artwork/card or Play to start the selected episode.

## 1.1.17 — 2026-10-09

- Review imported videos in an editable table before moving, including bulk series/season/episode/Sub/Dub changes, actual-resolution checks, and file/folder drag and drop.
- Replace or upgrade one existing same-language episode with higher verified resolution through Import or Manage versions. Preserve watch history and subtitles, verify the incoming copy, and roll back failed file/database updates. Old copies remain recoverable or can be recycled after success.
- Home shows **Up next** for each series with a direct Play button.
- **Season completeness** shows separate Sub/Dub counts and missing episodes. **Download missing** uses the last viewed source episode list, with a checked timestamp and honest unknown totals when no list is available.
- Pause/resume the download queue, drag queued cards to change their order, and retry all failed videos for the current profile without duplicating entries.
- Preview public YouTube playlists, select videos, and queue them in order into one series with chosen quality and episode numbering.
- Automatic daily, manual, and pre-restore library backups preserve each profile's organization, settings, and watch progress. Restore validates the backup and saves the current state first; media files remain on their drives.

## 1.1.16 — 2026-10-09

- The Library episode selector shows a watch-progress bar beneath each episode's play button, with the watched percentage and saved playback time. Completed episodes have green bars and keep their actual watched fraction.
- Sub/Dub and quality copies share one episode indicator using the furthest saved percentage on any copy; progress from separate versions is never added together. Episodes with unknown duration show the saved time without guessing a percentage.
- Returning from playback saves the final position before the episode selector is rendered, so the bar immediately reflects where you stopped. Works for Anime and YouTube series.

## 1.1.15 — 2026-10-09

- Library has separate **Anime** and **YouTube** tabs with shared search and refresh. YouTube series use wide 16:9 thumbnails; anime posters keep their portrait layout.
- Import includes a **These are YouTube videos** checkbox. New series created by YouTube downloads go to the YouTube tab automatically; existing series keep the tab you chose.
- Open any existing series and choose **Move to YouTube** or **Move to Anime** to move the whole series between tabs while preserving its files, episode versions, details, and watch progress. Refresh and restarts remember the choice.
- Moving a series to YouTube can restore its actual thumbnail and description from saved download source information. Anime metadata lookups cannot overwrite YouTube series artwork, and YouTube series renames keep their thumbnails.

## 1.1.14 — 2026-10-09

- Add more YouTube links while videos are downloading. Each video gets its own Downloads card and keeps its selected quality, series, season, episode, and profile. The simultaneous-download limit controls how many run at once.
- Adding a YouTube video uses the download arrow animation and stays on **Find videos**. The link field clears for the next video; progress, Cancel, and Retry are available on each Downloads card. Repeated links reuse their queued or active card.
- Retry reuses the same card and remembers download options across restarts. Concurrent imports allocate separate automatic episode slots while preserving existing files.

## 1.1.13 — 2026-10-09

- **Find videos** episode lists show each episode's highest offered quality, including FHD (1080p), HD (720p), and single-stream resolution when available. Labels distinguish player offerings from the saved file's verified resolution.
- Quality checks run one at a time in the background for the current Sub/Dub tab and season. Downloads take priority, navigation stops unused checks, and cached results avoid repeated page loads. An unavailable quality check leaves download buttons usable.

## 1.1.12 — 2026-10-08

- **Manage versions → Edit episode / version** lets you correct a file's season, episode number, and Sub/Dub label. **Group with episode** picks an existing episode so separate versions appear together and count as one episode.
- The editor shows the filename and previews the resulting episode, available versions, and destination. Changes preserve watch progress, quality labels, subtitles, and source information, with collision checks and rollback if a file or database update fails.

## 1.1.11 — 2026-10-08

- Library has a **Refresh library** button beside search to pick up files added, moved, or deleted outside the app. The current search stays in place, and refresh results or errors appear inline.
- Folder scanning and language detection run in the background. Duplicate refreshes are prevented, callbacks stay with their original profile and folder, and a disconnected drive or unreadable folder does not clear the library index.
- Refresh keeps metadata and watch progress for unchanged paths, and preserves completed downloads indexed while the background scan was running.

## 1.1.10 — 2026-10-08

- **Find videos** search results show a poster with the anime's release year underneath, before opening its episode list or downloading anything. Existing library details appear immediately; other artwork loads in the background.
- Search results keep their episode and page buttons available while details load. Unknown artwork and years are clearly labeled, and old lookups cannot update another search or profile.
- Search artwork is reused for subsequent downloads and imports. Download metadata requests take priority, and navigating away discards unstarted search lookups.
- Metadata searches compare more candidates and prefer exact canonical titles when adaptations share a short alias, keeping original shows and spin-offs distinct.

## 1.1.9 — 2026-10-08

- Adding the first downloaded episode automatically fetches the anime's poster, description, and release year. An earlier failed lookup gets another chance after import, without duplicating an active lookup or holding up downloads.
- YouTube download cards use the video's actual thumbnail and upload year. New library entries also receive the thumbnail and video description, while existing anime details are preserved.
- Thumbnail fetching runs separately from video transfers, persists in download history, and stays with the original profile. YouTube imports index the completed file directly.

## 1.1.8 — 2026-10-08

- Download cards show anime artwork with its release year underneath. Existing library details are reused; new details load in the background once per series without holding up video downloads. Artwork and years persist in download history.
- Anime details show the release year under the poster. The details button is now **Grab details and thumbnail**.
- Existing library metadata gains saved release years through background backfilling. Unavailable years remain clearly labeled, and metadata callbacks stay with their original profile without changing the page being viewed.

## 1.1.7 — 2026-10-08

- Updating takes one click: download, verification, installation, and automatic reopening continue without confirmation dialogs. Download progress and loading indicators appear in the sidebar and Settings.
- Update checks, errors, and installation results appear inline. Failed downloads can be retried; an installer startup failure keeps the app open and retains the verified package for retry.
- Starting the installer runs in the background so the loading indicator stays responsive while waiting for the installer to be ready.

## 1.1.6 — 2026-10-08

- Home and Library fit anime cards across the available window width and wrap onto new rows when resized or maximized. Resizing keeps existing cards and their click targets intact.
- Continue watching wraps on narrower Home windows without forcing horizontal scrolling.

## 1.1.5 — 2026-10-08

- Downloads lists active jobs first and keeps each series in numeric season/episode order. Finished cards move back into their episode position, with progress, retry controls, and card identity preserved.
- Full-season downloads continue to start at the lowest eligible episode and admit later episodes in ascending order, even when the source lists the season backwards.

## 1.1.4 — 2026-10-08

- Downloads badges count active and queued episodes together, keeping imports counted until completion and dropping finished jobs from the total. Hover over Downloads for an active/queued/failed breakdown.
- A red exclamation badge appears in the sidebar and Downloads tab while any jobs have failed, including restored failures at startup. Retrying clears that job's warning immediately; other unresolved failures keep the badge visible. Clearing finished entries also clears their warnings.

## 1.1.3 — 2026-10-08

- Maintenance release for testing the complete in-app update flow from v1.1.2: update detection, verified download, installation, and automatic reopen. Application behavior is unchanged from v1.1.2.

## 1.1.2 — 2026-10-08

- Fixed the Windows update helper silently exiting before installing or reopening the app. Anime Watcher now waits for the hidden helper to confirm it is ready before closing; startup failures keep the app open and provide a persistent diagnostic log.
- The helper runs outside the app folder and resets the packaged runtime environment for a fresh restart. Verified replacement and rollback backups remain in place.

## 1.1.1 — 2026-10-08

- Schedule defaults to Current airings for this week, including shows outside your library, with Week/Month views, confirmed local airing times, show filtering, and AniList links. My library and Recent activity remain available. Cached schedules stay visible if refreshing fails.
- A blue Update available button appears in the sidebar when a newer stable app release is found, opens the verified updater, shows download progress, and changes to Restart to update once ready. Automatic checks run at startup and every six hours while open; temporary check failures retry after fifteen minutes.
- Updates is now Schedule, with a month calendar, highlighted dates, per-show filtering, selected-day episode cards, and month/Today navigation. Confirmed AniList airings use local time, refresh in the background, and stay available from cache offline. Existing notifications remain under Recent activity.
- Application updates now appears at the top of Settings for easier access.

- Clicking Download best available keeps the current episode list, Sub/Dub selection, and scroll position. A brief arrow animation flies toward Downloads and the episode row confirms it was added without changing tabs.
- Background downloads create a visible browser widget only when Open player is requested, avoiding unnecessary graphics setup on the first download.
- Selected Sub/Dub catalog tabs use a purple background, bold white text, and a contrasting underline.

## 1.1.0 — 2026-10-08

- Settings now checks the official `CaptainKeat/anime-watcher` GitHub releases for stable updates once a day or on demand. Packaged builds download only the exact versioned Windows ZIP, verify GitHub's SHA-256 digest, reject unsafe archives, stage the replacement beside the current app, keep a rollback backup, and reopen after a successful install. Profiles, watch progress, and the selected library remain outside the application folder.

- Release packaging now runs source and packaged-app privacy audits that block personal identities, user-profile paths, credential patterns, media, runtime databases, cookies, and unsafe archive contents. User-entered catalog/direct-download URLs reject embedded credentials and non-HTTP(S) redirects; metadata posters are restricted to trusted HTTPS image hosts, size-bounded, and written atomically.

- Series pages and Files now support selecting and moving episodes in bulk to an existing/new series, setting a season, and optionally renumbering episode groups. Batch moves preserve watch progress, versions, quality labels, subtitles, and provenance, validate all destinations up front, and roll back files/database changes on failure.

- Supported players that explicitly expose one stream without a quality selector now download without waiting for a missing menu. HD/FHD alternatives still take priority; saved files are verified and labeled with their actual resolution.

- Completed downloads have green bars and cards; failures have red bars, cards, and a failed-count summary. Manual video retries reuse the same job and block, reset progress, and retain attempt history. Finished download history survives restarts.
- Video downloads now allow four automatic attempts, including transient transfer and saved-file verification failures. Retries wait for worker cleanup, preserve rejected files, and rejoin behind queued episodes; disk/import errors and user cancellation are not automatically retried.

- The downloader prepares one upcoming episode near transfer completion, holds it in the queue until admitted, and refreshes stale selections. Verification/import no longer occupy transfer slots, with import backpressure and separate transfer/import counts; saved videos still require quality verification before indexing.
- The downloader retains the selected source before an unsupported Qt preview replaces it with an error clip; missing selected sources retry the normal quality control promptly, with bounded reloads and saved-file resolution checks.

- Downloads now show measured speed and remaining time, with a saved 1–6 simultaneous-download setting. The downloader stops preview buffering after accepting a download, stages on the library volume to avoid copying from APPDATA, and indexes the imported episode without rescanning every file. Pending and failed staging files are excluded from library scans; quality verification remains required.

### Added

- Catalog episode checkboxes, Select all, Download selected, and Download season queue the current Sub/Dub version and season in episode order. Existing copies are skipped by default, with an option to include quality upgrades; duplicate and already queued episodes are skipped. Batches update the queue list once and respect the simultaneous-download setting.
- Video quality selection retries the actual menu control, waits for a stable confirmed source, and reloads once on timeout. Unresolved quality selection and stalled transfers fail clearly and release their queue slot; failed entries offer Retry. Local queue snapshots help diagnose failures.
- Shared Downloads tab with per-video progress, cancellation, completed/failed entries, and active-count badges. Integrated players run in the background; jobs run concurrently according to the queue setting and additional jobs wait.
- A saved, initially unchecked download-permission checkbox per profile covers YouTube and other supported video downloads and can be revoked for future downloads.
- Catalog episode lists separate Sub and Dub into counted tabs, retain season filtering, and use explicit local-library availability labels.
- Supported catalog search through its normal form and an isolated browser session, episode lists scoped to the selected show, season/Sub/Dub filters, and local availability indicators.
- Video downloads select the best offered quality and verify the saved file before importing into an existing matching series. Existing copies are preserved, and source provenance follows manual library moves.
- YouTube downloads match existing series by normalized titles or saved channel IDs and infer episode slots. Downloads can target an existing/new series and explicit season/episode numbers.
- Move to series actions on episode rows, Manage versions, and Files preserve watch progress, subtitles, and YouTube provenance, reject occupied slots, and roll back file moves when database updates fail.

- YouTube video and Shorts downloads in the Downloads page, with resolution limits, background progress, cancellation, and automatic library import. yt-dlp and its JavaScript solver scripts are included in Windows builds.
- Multiple local profiles with isolated databases, watch history, library location, settings, and integrations. Existing data remains in the Default profile.
- A searchable file manager for correcting anime, season, episode number, and Sub/Dub identification.
- Customizable player keyboard shortcuts, including track cycling, subtitle timing, episode navigation, fullscreen, and picture-in-picture.
- Same-window picture-in-picture mode positioned on the monitor currently containing the player.
- AniList opt-in account connection, exact-title linking, progress/list/score updates, and official airing schedules. Tokens are encrypted with Windows DPAPI.
- Persistent in-app and Windows notifications for AniList airing changes and newly discovered local Sub/Dub episodes.
- Timeline markers and contextual skip buttons for named Intro, Outro, Recap, and Filler/Preview chapters.
- Per-anime subtitle delay and remembered external/embedded subtitle selection.
- SSA sidecars plus overlapping ASS/SSA dialogue and top/bottom alignment.
- Full external ASS/SSA rendering through bundled libass, including authored typesetting, animation, karaoke timing, outlines, positioning, and adjacent custom fonts.
- Matching SRT, VTT, and basic ASS sidecar subtitles are discovered automatically and selectable from the player Settings panel.
- Subtitles can be imported for the current episode or generated as translated English SRT files with local GPU-accelerated Whisper processing.
- The player Settings panel now reports the real local source resolution and offers `Auto`, `1080p`, `720p`, and other choices only when those episode files actually exist.
- Left and Right arrow keys seek backward and forward by ten seconds.
- Skip Intro now reads embedded Intro/Opening chapters, appears only during that chapter, and seeks to its exact end time.
- Sub/Dub detection now combines filename labels, embedded stream-language metadata, paired episode variants, and confirmed release-group patterns.
- The player exposes an explicit Sub/Dub version selector when both files exist.
- The episode picker collapses Sub/Dub files into one row and starts with Sub as the initial per-anime preference.

### Changed

- Sidecar subtitle files with the same source filename now follow imported episodes into the organized anime/season folder.
- Redesigned the player controls around a streaming-style full-width timeline and compact bottom action row; version, audio, subtitles, playback speed, and autoplay now live in a gear menu.
- Rebuilt the desktop interface on PySide6/Qt as one top-level application window, with video, controls, and timeline previews contained in one player page.
- Removed CustomTkinter DPI polling and manual top-level overlay positioning; Qt now owns mixed-DPI monitor moves, maximization, and current-screen fullscreen.
- Debounced timeline preview generation so fast scrubbing does not launch a burst of competing FFmpeg processes.
- Next, previous, and autoplay prefer the currently selected language and warn before falling back to another version.
- Switching versions in the player preserves the playback position and saves that language as the anime's new default.
- Episode rows show more prominent `SUB VERSION`, `DUB VERSION`, or `UNKNOWN VERSION` labels.
- Sub/Dub and next-episode transitions now reuse the active Qt media surface instead of destroying and recreating overlay windows.
- Resume seeking is non-blocking and preview warmup is limited to five low-priority frames to reduce large-display resize lag.
- Corrected an inverted CustomTkinter DPI resize guard that caused window-size feedback loops when moving the player between differently scaled monitors or TVs.
- Fullscreen and player overlays now use native physical-pixel bounds, preventing a high-DPI TV's dimensions from being multiplied again and spilling across adjacent monitors.

### Fixed

- Leaving playback now unloads the video so Windows releases its file handle. Confirmed Delete, Rename, and Move actions also save progress and unload an affected active video before changing its file.

- Removed the full-player transparent widget layer and now overlay only the compact controls, preventing 4K video repaint churn while moving or resizing the window.
- Coalesced video-surface and control-layout resize work instead of queueing an unbounded zero-delay callback for every Windows resize event.
- Avoided repeated layout and raise operations on every mouse move, bounded ASS rendering to 1080p on larger displays, and removed duplicate ASS render ticks.
- Added a local UI-hang watchdog that writes all Python thread stacks to `%APPDATA%\AnimeWatcher\crash.log` if the event loop stops responding for eight seconds.
- Clicking or dragging the timeline now assigns the pointer position to the seek slider before seeking instead of only updating the hover preview.
- Left and Right arrow seeking now uses player-scoped shortcuts, so focused buttons, sliders, and Settings controls cannot swallow the ten-second seek keys.
- Replaced the native `QVideoWidget` surface with a composited graphics-scene video item so the timeline, controls, and settings cannot be covered by the video renderer.
- Player controls reappear whenever the pointer moves over the player.
- Replaced the mixed Qt/VLC native-window playback path with Qt Multimedia's FFmpeg-backed player so video and transparent controls share one compositor and one window.
- Player background workers now remain alive until their queued Qt signals finish, preventing native Python crashes caused by callbacks outliving their wrappers.
- Native crash and unhandled Python exception details are now written locally to `%APPDATA%\AnimeWatcher\crash.log`.
- Windows packaging now isolates PyInstaller from unrelated native toolchains so a foreign Poppler `icuuc.dll` cannot replace the Windows ICU expected by Qt.
- ASS subtitle pixels are composited as a graphics-scene item inside the existing video surface, avoiding the extra native Windows overlay that previously caused mixed-DPI TV lag and monitor spillover.
- The build now runs an offscreen executable smoke test and explicitly rejects PyInstaller's unhandled-exception dialog instead of treating the still-running dialog process as a successful launch.
- The build now checksum-documents and bundles an isolated libass dependency closure, then runs a packaged animated-ASS rendering smoke test before accepting the EXE.

## 1.0.1 — 2026-09-18

### Fixed

- Metadata searches now rank English, romanized, Japanese, and alias titles instead of accepting the first provider result.
- Weak provider matches are rejected so lookup can continue to a later exact match, preventing results such as Re:Zero for Redo of Healer.

## 1.0.0 — 2026-09-18

First packaged GitHub release.

- Privacy hardening: first-run library location is empty until the user selects it, and no machine-specific discovery paths are shipped.

### Library

- Local anime library scanning and season/episode organization.
- Safe anime and episode renaming with watch-progress preservation.
- Recycle Bin deletion with confirmation.
- Sub and Dub episode variants.
- Poster, official title, and synopsis metadata.

### Player

- VLC-powered embedded playback.
- Automatic resume and periodic progress saving.
- Transparent modern controls with subtitles left visible.
- Current-monitor fullscreen behavior.
- Click-to-pause, seeking, autoplay, speed, volume, audio, and subtitle controls.
- Automatically warmed timeline previews that remain above VLC's native video surface.

### Import and downloads

- Local file and folder import.
- Search for partial anime titles on user-supplied public catalog pages.
- Browser handoff for public episode pages.
- Confirmed direct-media downloads followed by automatic organization.

### Branding

- Custom Anime Watcher logo for the executable, shortcut, taskbar, and application window.
