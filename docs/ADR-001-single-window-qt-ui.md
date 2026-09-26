# ADR-001: Use one Qt window for the desktop interface

- Status: Accepted
- Date: 2026-09-19

## Context

The previous CustomTkinter player combined the root window, VLC's native video
surface, and separate top-level control/preview overlays. It manually synchronized
their physical bounds. Moving that collection between monitors with different DPI
and resolutions caused repeated resize work, visible bleed across displays, lag,
and inconsistent control sizing.

## Decision

Use PySide6/Qt for the desktop UI and Qt Multimedia for playback. The application
has one `QMainWindow`; library pages and the player are pages inside that window.
Video, controls, and the timeline preview are composed by Qt in the same player
page. Qt owns playback presentation, per-monitor DPI changes, window moves,
maximization, and fullscreen placement.

Keep the existing database, organizer, metadata, downloader, and preview generator.

## Consequences

- No manually synchronized top-level player overlays.
- Styled external ASS/SSA subtitles are rendered by libass to transparent pixels and placed in the existing `QGraphicsScene`; libass never owns a window or native video surface.
- Fullscreen applies to the monitor containing the app window.
- Window moves and monitor DPI changes no longer trigger custom geometry polling.
- The Windows bundle is larger because it includes Qt Multimedia and its FFmpeg backend.
- The legacy CustomTkinter module remains temporarily as rollback reference but is
  excluded from release builds and is no longer the application entry point.
