# Installing Anime Watcher

## Recommended installation

### 1. Install VLC

Anime Watcher uses VLC for video and audio playback. Install the current 64-bit Windows version from [videolan.org](https://www.videolan.org/vlc/). The standard installation path is:

```text
C:\Program Files\VideoLAN\VLC
```

### 2. Install FFmpeg

FFmpeg generates timeline preview images without changing active playback.

```powershell
winget install Gyan.FFmpeg
```

Close and reopen your terminal after installation if you plan to run Anime Watcher from source.

### 3. Download Anime Watcher

1. Open the GitHub **Releases** page.
2. Download `Anime-Watcher-v1.0.1-Windows.zip`.
3. Right-click the ZIP and choose **Extract All**.
4. Keep every extracted file together. The `_internal` folder is required.
5. Run `Anime Watcher.exe`.

Anime Watcher is currently unsigned. If Windows SmartScreen appears, verify that the ZIP came from the official `CaptainKeat/anime-watcher` release, choose **More info**, and then choose **Run anyway**.

## First-run setup

1. Open **Settings**.
2. Select the folder containing your anime library.
3. Save the setting and refresh the library.
4. If your files are not organized yet, use **Import** to select individual files or a folder.

Anime Watcher leaves the library location empty on first launch. It does not create or scan a drive until you choose a folder and save it.

## Local data

Anime Watcher stores its database, posters, preview cache, and authorized-download staging files under:

```text
%APPDATA%\AnimeWatcher
```

Your episodes remain in the library folder you selected. They are not copied into the GitHub project and are never uploaded automatically.

## Troubleshooting

### The app cannot start VLC

Install the 64-bit version of VLC in the standard location, then reopen Anime Watcher.

### Timeline previews do not appear

Install FFmpeg with the command above. Anime Watcher also recognizes the standard FFmpeg package installed by WinGet.

### Windows shows a security warning

The first release is not code-signed. Only run the application when it was downloaded from the official GitHub release.

### The application icon has not refreshed

Unpin the older shortcut, launch the current release once, and pin the running application again.

## Uninstall

1. Close Anime Watcher.
2. Delete the extracted Anime Watcher application folder.
3. Optionally delete `%APPDATA%\AnimeWatcher` to remove settings, posters, previews, and playback history.

Deleting the application or its AppData folder does not delete your external anime library.
