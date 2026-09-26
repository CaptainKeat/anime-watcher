from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from .media_language import probe_embedded_language
from .organizer import parse_episode, scan_video_files


class LibraryDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS series (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_title TEXT,
                synopsis TEXT,
                poster_path TEXT,
                metadata_id INTEGER,
                metadata_updated TEXT
            );
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY,
                series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
                season INTEGER NOT NULL DEFAULT 1,
                episode INTEGER NOT NULL DEFAULT 0,
                title TEXT,
                path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                language TEXT NOT NULL DEFAULT 'Unknown',
                duration_ms INTEGER NOT NULL DEFAULT 0,
                progress_ms INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                last_watched TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_episode_order ON episodes(series_id, season, episode);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                series_id INTEGER REFERENCES series(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                fingerprint TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                read INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        series_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(series)")}
        additions = {
            "anilist_id": "INTEGER",
            "anilist_title": "TEXT",
            "next_airing_episode": "INTEGER",
            "next_airing_at": "INTEGER",
            "release_status": "TEXT",
        }
        for name, sql_type in additions.items():
            if name not in series_columns:
                self.connection.execute(f"ALTER TABLE series ADD COLUMN {name} {sql_type}")
        self.connection.commit()

    def setting(self, key: str, default: Any = None) -> Any:
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        self.connection.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self.connection.commit()

    def scan_library(self, root: str | Path) -> dict[str, int]:
        files = scan_video_files(root)
        seen: set[str] = set()
        detected = 0
        existing_languages = {
            row["path"].lower(): row["language"]
            for row in self.connection.execute("SELECT path,language FROM episodes")
        }
        for path in files:
            info = parse_episode(path)
            title = info.title
            language = info.language
            if language == "Unknown":
                existing_language = existing_languages.get(str(path).lower(), "Unknown")
                if existing_language in {"Sub", "Dub"}:
                    language = existing_language
                else:
                    language = probe_embedded_language(path)
                    if language != "Unknown":
                        detected += 1
            # Organized paths are authoritative and avoid parser ambiguity.
            try:
                relative = path.relative_to(Path(root))
                if len(relative.parts) >= 3:
                    title = relative.parts[0]
            except ValueError:
                pass
            self.connection.execute("INSERT OR IGNORE INTO series(title) VALUES(?)", (title,))
            series_id = self.connection.execute("SELECT id FROM series WHERE title=? COLLATE NOCASE", (title,)).fetchone()["id"]
            self.connection.execute(
                """INSERT INTO episodes(series_id,season,episode,title,path,language)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
                   series_id=excluded.series_id, season=excluded.season,
                   episode=excluded.episode, language=excluded.language""",
                (series_id, info.season, info.episode, f"Episode {info.episode}", str(path), language),
            )
            seen.add(str(path).lower())
        rows = self.connection.execute("SELECT id,path FROM episodes").fetchall()
        removed = 0
        for row in rows:
            if row["path"].lower() not in seen:
                self.connection.execute("DELETE FROM episodes WHERE id=?", (row["id"],))
                removed += 1
        self.connection.execute("DELETE FROM series WHERE id NOT IN (SELECT DISTINCT series_id FROM episodes)")
        # A common release layout has an explicitly labeled Dub beside an
        # unlabeled Japanese/subbed copy. Only infer that narrow pairing; a
        # lone untagged file stays Unknown instead of pretending certainty.
        inferred = self.connection.execute(
            """UPDATE episodes AS candidate SET language='Sub'
               WHERE candidate.language='Unknown' AND EXISTS (
                   SELECT 1 FROM episodes AS dub
                   WHERE dub.series_id=candidate.series_id
                     AND dub.season=candidate.season
                     AND dub.episode=candidate.episode
                     AND dub.id<>candidate.id
                     AND dub.language='Dub'
               )"""
        ).rowcount
        detected += max(0, inferred)
        # Continue a confirmed release-group pattern across later episodes.
        # Example: once paired [AH2] files are confirmed Sub, later [AH2]
        # episodes without a Dub counterpart can inherit that classification.
        rows = self.connection.execute(
            "SELECT id,series_id,path,language FROM episodes"
        ).fetchall()
        release_groups: dict[tuple[int, str], list[sqlite3.Row]] = {}
        for row in rows:
            match = re.match(r"^\s*(\[[^]]+\])", Path(row["path"]).name)
            if match:
                release_groups.setdefault((row["series_id"], match.group(1).casefold()), []).append(row)
        for group in release_groups.values():
            known = {row["language"] for row in group if row["language"] in {"Sub", "Dub"}}
            if len(known) != 1:
                continue
            group_language = next(iter(known))
            unknown_ids = [row["id"] for row in group if row["language"] == "Unknown"]
            if unknown_ids:
                placeholders = ",".join("?" for _ in unknown_ids)
                self.connection.execute(
                    f"UPDATE episodes SET language=? WHERE id IN ({placeholders})",
                    (group_language, *unknown_ids),
                )
                detected += len(unknown_ids)
        self.connection.commit()
        return {"files": len(files), "removed": removed, "language_updates": detected}

    def series(self, search: str = "") -> list[sqlite3.Row]:
        query = """
            SELECT s.*, COUNT(DISTINCT e.season*10000+e.episode) episode_count,
                   COUNT(DISTINCT CASE WHEN e.completed=1 THEN e.season*10000+e.episode END) completed_count,
                   MAX(e.last_watched) last_watched
            FROM series s JOIN episodes e ON e.series_id=s.id
        """
        params: tuple[Any, ...] = ()
        if search:
            query += " WHERE COALESCE(s.display_title,s.title) LIKE ?"
            params = (f"%{search}%",)
        query += " GROUP BY s.id ORDER BY COALESCE(s.display_title,s.title) COLLATE NOCASE"
        return self.connection.execute(query, params).fetchall()

    def get_series(self, series_id: int) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM series WHERE id=?", (series_id,)).fetchone()

    def episodes(self, series_id: int) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM episodes WHERE series_id=? ORDER BY season,episode,CASE language WHEN 'Sub' THEN 0 WHEN 'Dub' THEN 1 ELSE 2 END,path",
            (series_id,),
        ).fetchall()

    def all_episodes(self, search: str = "") -> list[sqlite3.Row]:
        query = """SELECT e.*,COALESCE(s.display_title,s.title) series_title
                   FROM episodes e JOIN series s ON s.id=e.series_id"""
        params: tuple[Any, ...] = ()
        if search:
            query += " WHERE COALESCE(s.display_title,s.title) LIKE ? OR e.path LIKE ?"
            params = (f"%{search}%", f"%{search}%")
        query += " ORDER BY series_title COLLATE NOCASE,e.season,e.episode,e.language,e.path"
        return self.connection.execute(query, params).fetchall()

    def episode(self, episode_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT e.*,COALESCE(s.display_title,s.title) series_title FROM episodes e JOIN series s ON s.id=e.series_id WHERE e.id=?",
            (episode_id,),
        ).fetchone()

    def relocate_episode(self, episode_id: int, path: str | Path, series_title: str,
                         season: int, episode: int, language: str) -> int:
        current = self.connection.execute("SELECT series_id FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if not current:
            raise ValueError("Episode is no longer in the library database")
        old_series_id = current["series_id"]
        try:
            self.connection.execute("INSERT OR IGNORE INTO series(title) VALUES(?)", (series_title,))
            new_series = self.connection.execute(
                "SELECT id FROM series WHERE title=? COLLATE NOCASE", (series_title,)
            ).fetchone()
            if not new_series:
                raise ValueError("Could not create the renamed series")
            self.connection.execute(
                """UPDATE episodes SET series_id=?,season=?,episode=?,title=?,path=?,language=?
                   WHERE id=?""",
                (new_series["id"], season, episode, f"Episode {episode}", str(path), language, episode_id),
            )
            self.connection.execute(
                "DELETE FROM series WHERE id=? AND id NOT IN (SELECT DISTINCT series_id FROM episodes)",
                (old_series_id,),
            )
            self.connection.commit()
            return new_series["id"]
        except Exception:
            self.connection.rollback()
            raise

    def rename_series(self, series_id: int, title: str, episode_paths: Mapping[int, str | Path]) -> None:
        series = self.get_series(series_id)
        if not series:
            raise ValueError("Anime is no longer in the library database")
        conflict = self.connection.execute(
            "SELECT id FROM series WHERE title=? COLLATE NOCASE AND id<>?", (title, series_id)
        ).fetchone()
        if conflict:
            raise ValueError("Another anime already uses that name")
        try:
            self.connection.execute(
                """UPDATE series SET title=?,display_title=?,synopsis=NULL,poster_path=NULL,
                   metadata_id=NULL,metadata_updated=NULL,anilist_id=NULL,anilist_title=NULL,
                   next_airing_episode=NULL,next_airing_at=NULL,release_status=NULL WHERE id=?""",
                (title, title, series_id),
            )
            for episode_id, path in episode_paths.items():
                self.connection.execute(
                    "UPDATE episodes SET path=? WHERE id=? AND series_id=?",
                    (str(path), episode_id, series_id),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def next_episode(self, episode_id: int, direction: int = 1) -> sqlite3.Row | None:
        current = self.episode(episode_id)
        if not current:
            return None
        op, order = (">", "ASC") if direction > 0 else ("<", "DESC")
        return self.connection.execute(
            f"""SELECT * FROM episodes WHERE series_id=? AND
                (season*10000+episode) {op} (?*10000+?)
                ORDER BY season {order},episode {order},
                         CASE WHEN language=? THEN 0 WHEN language='Unknown' THEN 1 ELSE 2 END,
                         path LIMIT 1""",
            (current["series_id"], current["season"], current["episode"], current["language"]),
        ).fetchone()

    def episode_variants(self, episode_id: int) -> list[sqlite3.Row]:
        current = self.episode(episode_id)
        if not current:
            return []
        return self.connection.execute(
            """SELECT * FROM episodes WHERE series_id=? AND season=? AND episode=?
               ORDER BY CASE language WHEN 'Sub' THEN 0 WHEN 'Dub' THEN 1 ELSE 2 END,path""",
            (current["series_id"], current["season"], current["episode"]),
        ).fetchall()

    def series_language_preference(self, series_id: int) -> str:
        preferences = self.setting("series_language_preferences", {})
        if not isinstance(preferences, dict):
            return "Sub"
        language = str(preferences.get(str(series_id), "Sub"))
        return language if language in {"Sub", "Dub"} else "Sub"

    def set_series_language_preference(self, series_id: int, language: str) -> None:
        if language not in {"Sub", "Dub"}:
            return
        preferences = self.setting("series_language_preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
        key = str(series_id)
        if preferences.get(key) == language:
            return
        preferences[key] = language
        self.set_setting("series_language_preferences", preferences)

    def save_progress(self, episode_id: int, progress_ms: int, duration_ms: int) -> None:
        completed = int(duration_ms > 0 and (progress_ms / duration_ms >= 0.90 or duration_ms - progress_ms < 120000))
        self.connection.execute(
            """UPDATE episodes SET progress_ms=?,duration_ms=?,completed=?,
               last_watched=datetime('now','localtime') WHERE id=?""",
            (max(0, progress_ms), max(0, duration_ms), completed, episode_id),
        )
        self.connection.commit()

    def continue_watching(self, limit: int = 12) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT e.*,COALESCE(s.display_title,s.title) series_title,s.poster_path
               FROM episodes e JOIN series s ON s.id=e.series_id
               WHERE e.progress_ms>0 AND e.completed=0 ORDER BY e.last_watched DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    def update_metadata(self, series_id: int, display_title: str, synopsis: str, poster_path: str, metadata_id: int) -> None:
        self.connection.execute(
            """UPDATE series SET display_title=?,synopsis=?,poster_path=?,metadata_id=?,
               metadata_updated=datetime('now','localtime') WHERE id=?""",
            (display_title, synopsis, poster_path, metadata_id, series_id),
        )
        self.connection.commit()

    def link_anilist(self, series_id: int, media: Mapping[str, Any]) -> None:
        titles = media.get("title") if isinstance(media.get("title"), Mapping) else {}
        title = str(titles.get("english") or titles.get("romaji") or titles.get("native") or "").strip()
        next_airing = media.get("nextAiringEpisode") if isinstance(media.get("nextAiringEpisode"), Mapping) else {}
        self.connection.execute(
            """UPDATE series SET anilist_id=?,anilist_title=?,release_status=?,
               next_airing_episode=?,next_airing_at=? WHERE id=?""",
            (
                int(media["id"]), title, str(media.get("status") or ""),
                next_airing.get("episode"), next_airing.get("airingAt"), series_id,
            ),
        )
        self.connection.commit()

    def linked_series(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM series WHERE anilist_id IS NOT NULL ORDER BY COALESCE(display_title,title) COLLATE NOCASE"
        ).fetchall()

    def update_release_schedule(self, media: Mapping[str, Any]) -> tuple[sqlite3.Row | None, bool]:
        media_id = int(media.get("id") or 0)
        current = self.connection.execute("SELECT * FROM series WHERE anilist_id=?", (media_id,)).fetchone()
        if not current:
            return None, False
        next_airing = media.get("nextAiringEpisode") if isinstance(media.get("nextAiringEpisode"), Mapping) else {}
        episode = next_airing.get("episode")
        airing_at = next_airing.get("airingAt")
        changed = episode is not None and (
            current["next_airing_episode"] != episode or current["next_airing_at"] != airing_at
        )
        self.connection.execute(
            """UPDATE series SET release_status=?,next_airing_episode=?,next_airing_at=?
               WHERE id=?""",
            (str(media.get("status") or ""), episode, airing_at, current["id"]),
        )
        self.connection.commit()
        return self.get_series(int(current["id"])), changed

    def add_notification(self, kind: str, title: str, body: str, series_id: int | None = None,
                         fingerprint: str = "") -> bool:
        stable = fingerprint or f"{kind}|{series_id or 0}|{title}|{body}"
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO notifications(kind,series_id,title,body,fingerprint)
               VALUES(?,?,?,?,?)""",
            (kind, series_id, title, body, stable),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def notifications(self, unread_only: bool = False) -> list[sqlite3.Row]:
        query = "SELECT * FROM notifications"
        if unread_only:
            query += " WHERE read=0"
        query += " ORDER BY created_at DESC,id DESC"
        return self.connection.execute(query).fetchall()

    def unread_notification_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM notifications WHERE read=0").fetchone()[0])

    def mark_notifications_read(self) -> None:
        self.connection.execute("UPDATE notifications SET read=1")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
