# Changelog

## Unreleased

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
