# Installing Anime Watcher

## Recommended installation

### 1. Install FFmpeg

FFmpeg generates timeline preview images without changing active playback.

```powershell
winget install Gyan.FFmpeg
```

Close and reopen your terminal after installation if you plan to run Anime Watcher from source.

### 2. Download Anime Watcher

1. Open the GitHub **Releases** page.
2. Download `Anime-Watcher-v1.1.2-Windows.zip`.
3. Right-click the ZIP and choose **Extract All**.
4. Keep every extracted file together. The `_internal` folder is required.
5. Run `Anime Watcher.exe`.

Anime Watcher is currently unsigned. If Windows SmartScreen appears, verify that the ZIP came from the official `CaptainKeat/anime-watcher` release, choose **More info**, and then choose **Run anyway**.

## Updating

Updater-enabled builds show a blue **Update available** button in the sidebar when
a newer stable release is found. Click it to download the verified update, then
choose **Restart to update** when ready. You can also open **Settings → Application
updates → Check now**. Automatic checks run at startup and every six hours; you can
turn them off without disabling the manual check.

The updater accepts only the exact versioned Windows ZIP from the official
`CaptainKeat/anime-watcher` stable release. It verifies the SHA-256 digest
reported by GitHub, rejects unsafe archive paths, stages the new app beside the
current folder, and installs only after Anime Watcher closes. The previous app
folder is retained as a rollback backup, and the app reopens when installation
succeeds. Profiles, playback history, settings, and your anime library are not
moved.

Anime Watcher is not code-signed. The digest check detects a damaged or
mismatched GitHub asset, but it does not provide a publisher signature.

Version 1.1.0 is the first updater-enabled release. If you are on v1.0.1 or older,
manually download and extract the latest release once; future stable updates can then be
installed in-app.

## First-run setup

1. Open **Settings**.
2. Select the folder containing your anime library.
3. Save the setting and refresh the library.
4. If your files are not organized yet, use **Import** to select individual files or a folder.

## Optional AniList connection

Anime Watcher works without an AniList account. To sync progress and receive official airing updates:

1. Create an AniList developer application and configure its authorization redirect for the AniList PIN/token flow.
2. In Anime Watcher, open **Settings**, enter the application client ID, and choose **Open authorization**.
3. Authorize in your browser, paste the returned token, and choose **Save & verify**.
4. Open an anime and choose **Link AniList** to select the exact title.

The access token is encrypted for your current Windows account using DPAPI. AniList provides official airing dates but not dub-release dates; Anime Watcher never invents dub dates.

Anime Watcher leaves the library location empty on first launch. It does not create or scan a drive until you choose a folder and save it.

## Local data

Anime Watcher stores its database, posters, preview cache, and authorized-download staging files under:

```text
%APPDATA%\AnimeWatcher
```

Your episodes remain in the library folder you selected. They are not copied into the GitHub project and are never uploaded automatically.

## Troubleshooting

### Video does not play

Close Anime Watcher, reopen it, and try the episode again. Playback uses the Qt FFmpeg backend bundled with the application, so VLC is not required. Diagnostic crash information is stored locally in `%APPDATA%\AnimeWatcher\crash.log`.

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
