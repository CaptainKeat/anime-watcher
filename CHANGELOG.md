# Changelog

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
