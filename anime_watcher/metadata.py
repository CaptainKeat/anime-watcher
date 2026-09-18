from __future__ import annotations

import json
import html
import re
import urllib.parse
import urllib.request
from pathlib import Path


API_ROOT = "https://api.jikan.moe/v4"
KITSU_ROOT = "https://kitsu.io/api/edge"
TVMAZE_ROOT = "https://api.tvmaze.com"


def clean_search_title(title: str) -> str:
    title = re.sub(r"\bSeason\s*\d+\b|\bS\d+\b", "", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -")


def _download_poster(poster_url: str | None, cache_dir: str | Path, cache_key: str) -> str:
    if not poster_url:
        return ""
    target_dir = Path(cache_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(urllib.parse.urlparse(poster_url).path).suffix or ".jpg"
    target = target_dir / f"{cache_key}{suffix}"
    if not target.exists():
        image_request = urllib.request.Request(poster_url, headers={"User-Agent": "AnimeWatcher/1.0"})
        with urllib.request.urlopen(image_request, timeout=20) as response, target.open("wb") as output:
            output.write(response.read())
    return str(target)


def _fetch_jikan(title: str, cache_dir: str | Path) -> dict:
    query = urllib.parse.urlencode({"q": clean_search_title(title), "limit": 5, "sfw": "true"})
    request = urllib.request.Request(
        f"{API_ROOT}/anime?{query}",
        headers={"User-Agent": "AnimeWatcher/1.0 (personal local library)"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    candidates = payload.get("data") or []
    if not candidates:
        raise LookupError(f"No metadata found for {title}")
    item = candidates[0]
    display = item.get("title_english") or item.get("title") or title
    poster_url = (((item.get("images") or {}).get("jpg") or {}).get("large_image_url") or
                  ((item.get("images") or {}).get("jpg") or {}).get("image_url"))
    poster_path = _download_poster(poster_url, cache_dir, f"jikan-{item['mal_id']}")
    return {
        "id": int(item["mal_id"]),
        "title": display,
        "synopsis": item.get("synopsis") or "",
        "poster_path": poster_path,
        "episodes": item.get("episodes"),
        "season": item.get("season"),
        "year": item.get("year"),
    }


def _fetch_kitsu(title: str, cache_dir: str | Path) -> dict:
    query = urllib.parse.urlencode({"filter[text]": clean_search_title(title), "page[limit]": 5})
    request = urllib.request.Request(
        f"{KITSU_ROOT}/anime?{query}",
        headers={"User-Agent": "AnimeWatcher/1.0", "Accept": "application/vnd.api+json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    candidates = payload.get("data") or []
    if not candidates:
        raise LookupError(f"No Kitsu metadata found for {title}")
    item = candidates[0]
    attributes = item.get("attributes") or {}
    titles = attributes.get("titles") or {}
    display = titles.get("en") or attributes.get("canonicalTitle") or titles.get("en_jp") or title
    poster_data = attributes.get("posterImage") or {}
    poster_url = poster_data.get("original") or poster_data.get("large") or poster_data.get("medium")
    poster_path = _download_poster(poster_url, cache_dir, f"kitsu-{item['id']}")
    start_date = attributes.get("startDate") or ""
    return {
        "id": int(item["id"]),
        "title": display,
        "synopsis": attributes.get("synopsis") or attributes.get("description") or "",
        "poster_path": poster_path,
        "episodes": attributes.get("episodeCount"),
        "season": None,
        "year": int(start_date[:4]) if len(start_date) >= 4 and start_date[:4].isdigit() else None,
    }


def _fetch_tvmaze(title: str, cache_dir: str | Path) -> dict:
    query = urllib.parse.urlencode({"q": clean_search_title(title)})
    request = urllib.request.Request(f"{TVMAZE_ROOT}/search/shows?{query}", headers={"User-Agent": "AnimeWatcher/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        candidates = json.load(response)
    if not candidates:
        raise LookupError(f"No TVmaze metadata found for {title}")
    item = candidates[0]["show"]
    images = item.get("image") or {}
    poster_path = _download_poster(images.get("original") or images.get("medium"), cache_dir, f"tvmaze-{item['id']}")
    summary = re.sub(r"<[^>]+>", "", item.get("summary") or "")
    premiered = item.get("premiered") or ""
    return {
        "id": int(item["id"]),
        "title": item.get("name") or title,
        "synopsis": html.unescape(summary),
        "poster_path": poster_path,
        "episodes": None,
        "season": None,
        "year": int(premiered[:4]) if len(premiered) >= 4 and premiered[:4].isdigit() else None,
    }


def fetch_metadata(title: str, cache_dir: str | Path) -> dict:
    """Fetch cached poster/title data with independent provider fallbacks."""
    failures = []
    for provider in (_fetch_jikan, _fetch_kitsu, _fetch_tvmaze):
        try:
            result = provider(title, cache_dir)
            # Fan edits and abridged cuts may intentionally share artwork with the
            # source series; preserve that meaningful local edition label.
            if "abridged" in title.lower() and "abridged" not in result["title"].lower():
                result["title"] = title
            return result
        except Exception as exc:
            failures.append(f"{provider.__name__.removeprefix('_fetch_')}: {exc or type(exc).__name__}")
    raise LookupError("Metadata providers could not find this title. " + " | ".join(failures))
