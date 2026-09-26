from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


ANILIST_GRAPHQL = "https://graphql.anilist.co"


def _graphql(query: str, variables: dict[str, Any] | None = None, token: str = "", timeout: float = 15.0) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "AnimeWatcher/2.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(ANILIST_GRAPHQL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            message = detail.get("errors", [{}])[0].get("message", str(exc))
        except Exception:
            message = str(exc)
        raise RuntimeError(f"AniList request failed: {message}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not reach AniList: {exc}") from exc
    errors = payload.get("errors")
    if errors:
        message = errors[0].get("message", "Unknown AniList error") if isinstance(errors, list) else str(errors)
        raise RuntimeError(f"AniList request failed: {message}")
    return payload.get("data") or {}


def search_anime(title: str) -> list[dict]:
    query = """
    query ($search: String) {
      Page(page: 1, perPage: 12) {
        media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
          id title { romaji english native } format status episodes seasonYear
          coverImage { medium }
          nextAiringEpisode { episode airingAt timeUntilAiring }
        }
      }
    }
    """
    data = _graphql(query, {"search": title.strip()})
    return list((data.get("Page") or {}).get("media") or [])


def viewer(token: str) -> dict:
    data = _graphql("query { Viewer { id name avatar { medium } } }", token=token)
    result = data.get("Viewer")
    if not isinstance(result, dict):
        raise RuntimeError("AniList did not return a signed-in user")
    return result


def save_list_entry(token: str, media_id: int, progress: int, status: str = "CURRENT", score: float | None = None) -> dict:
    mutation = """
    mutation ($mediaId: Int, $progress: Int, $status: MediaListStatus, $score: Float) {
      SaveMediaListEntry(mediaId: $mediaId, progress: $progress, status: $status, score: $score) {
        id mediaId progress status score
      }
    }
    """
    variables = {"mediaId": int(media_id), "progress": max(0, int(progress)), "status": status, "score": score}
    data = _graphql(mutation, variables, token=token)
    return data.get("SaveMediaListEntry") or {}


def release_schedule(media_ids: list[int]) -> list[dict]:
    clean_ids = sorted({int(value) for value in media_ids if int(value) > 0})
    if not clean_ids:
        return []
    query = """
    query ($ids: [Int]) {
      Page(page: 1, perPage: 50) {
        media(id_in: $ids, type: ANIME) {
          id status episodes title { romaji english }
          nextAiringEpisode { episode airingAt timeUntilAiring }
        }
      }
    }
    """
    data = _graphql(query, {"ids": clean_ids})
    return list((data.get("Page") or {}).get("media") or [])
