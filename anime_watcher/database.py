from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

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
            """
        )
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
        for path in files:
            info = parse_episode(path)
            title = info.title
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
                (series_id, info.season, info.episode, f"Episode {info.episode}", str(path), info.language),
            )
            seen.add(str(path).lower())
        rows = self.connection.execute("SELECT id,path FROM episodes").fetchall()
        removed = 0
        for row in rows:
            if row["path"].lower() not in seen:
                self.connection.execute("DELETE FROM episodes WHERE id=?", (row["id"],))
                removed += 1
        self.connection.execute("DELETE FROM series WHERE id NOT IN (SELECT DISTINCT series_id FROM episodes)")
        self.connection.commit()
        return {"files": len(files), "removed": removed}

    def series(self, search: str = "") -> list[sqlite3.Row]:
        query = """
            SELECT s.*, COUNT(e.id) episode_count,
                   SUM(CASE WHEN e.completed=1 THEN 1 ELSE 0 END) completed_count,
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
                   metadata_id=NULL,metadata_updated=NULL WHERE id=?""",
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
                ORDER BY season {order},episode {order} LIMIT 1""",
            (current["series_id"], current["season"], current["episode"]),
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

    def close(self) -> None:
        self.connection.close()
