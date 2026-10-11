from __future__ import annotations

import json
import html
import re
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterable


API_ROOT = "https://api.jikan.moe/v4"
KITSU_ROOT = "https://kitsu.io/api/edge"
TVMAZE_ROOT = "https://api.tvmaze.com"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
MAX_POSTER_BYTES = 15 * 1024 * 1024
POSTER_HOST_SUFFIXES = (".myanimelist.net", ".kitsu.app", ".tvmaze.com", ".wikimedia.org")
MIN_TITLE_MATCH_SCORE = 0.72
TITLE_STOP_WORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to"}


def clean_search_title(title: str) -> str:
    title = re.sub(r"\bSeason\s*\d+\b|\bS\d+\b", "", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -")


def _normalized_title(title: str) -> str:
    value = html.unescape(clean_search_title(title or "")).casefold()
    value = value.replace("&", " and ")
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()


def _title_match_score(query: str, candidate: str) -> float:
    """Score a provider title without confusing one shared word for a match."""
    normalized_query = _normalized_title(query)
    normalized_candidate = _normalized_title(candidate)
    if not normalized_query or not normalized_candidate:
        return 0.0
    if normalized_query == normalized_candidate:
        return 1.0

    query_tokens = set(normalized_query.split())
    candidate_tokens = set(normalized_candidate.split())
    meaningful_query = query_tokens - TITLE_STOP_WORDS or query_tokens
    meaningful_candidate = candidate_tokens - TITLE_STOP_WORDS or candidate_tokens
    shared = meaningful_query & meaningful_candidate
    recall = len(shared) / len(meaningful_query)
    precision = len(shared) / len(meaningful_candidate)
    sequence = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
    score = (0.45 * sequence) + (0.40 * recall) + (0.15 * precision)

    # Accept extended official titles such as "Re:Zero — Starting Life in
    # Another World" when the user's complete meaningful title is present.
    if meaningful_query.issubset(meaningful_candidate):
        score = max(score, 0.86)
    if meaningful_query == meaningful_candidate:
        score = max(score, 0.98)
    return score


def _select_best_candidate(
    query: str,
    candidates: Iterable[dict],
    title_variants: Callable[[dict], Iterable[str]],
    provider_name: str,
) -> dict:
    scored: list[tuple[float, float, int, dict]] = []
    for index, candidate in enumerate(candidates):
        variants = [value for value in title_variants(candidate) if value]
        score = max((_title_match_score(query, value) for value in variants), default=0.0)
        # Adaptations can share a short alias. Prefer the canonical title when
        # both entries achieve the same best alias score.
        canonical_score = _title_match_score(query, variants[0]) if variants else 0.0
        scored.append((score, canonical_score, -index, candidate))
    if not scored:
        raise LookupError(f"No {provider_name} metadata found for {query}")
    score, _canonical_score, _negative_index, best = max(scored, key=lambda item: item[:3])
    if score < MIN_TITLE_MATCH_SCORE:
        raise LookupError(f"{provider_name} returned no confident title match for {query}")
    return best


def _jikan_title_variants(item: dict) -> list[str]:
    variants = [item.get("title"), item.get("title_english"), item.get("title_japanese")]
    variants.extend(item.get("title_synonyms") or [])
    variants.extend(entry.get("title") for entry in (item.get("titles") or []) if isinstance(entry, dict))
    return [value for value in variants if value]


def _kitsu_title_variants(item: dict) -> list[str]:
    attributes = item.get("attributes") or {}
    titles = attributes.get("titles") or {}
    variants = [attributes.get("canonicalTitle"), attributes.get("slug", "").replace("-", " ")]
    variants.extend(titles.values())
    variants.extend(attributes.get("abbreviatedTitles") or [])
    return [value for value in variants if value]


def _download_poster(poster_url: str | None, cache_dir: str | Path, cache_key: str) -> str:
    if not poster_url:
        return ""
    parsed = urllib.parse.urlparse(poster_url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or not any(host.endswith(suffix) for suffix in POSTER_HOST_SUFFIXES):
        raise ValueError("The metadata provider returned an unsupported poster address")
    target_dir = Path(cache_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(parsed.path).suffix or ".jpg"
    target = target_dir / f"{cache_key}{suffix}"
    if not target.exists():
        temporary = target.with_suffix(target.suffix + ".download")
        image_request = urllib.request.Request(poster_url, headers={"User-Agent": "AnimeWatcher/1.0"})
        try:
            with urllib.request.urlopen(image_request, timeout=20) as response, temporary.open("wb") as output:
                resolved = urllib.parse.urlparse(response.geturl())
                resolved_host = (resolved.hostname or "").casefold()
                if resolved.scheme != "https" or not any(resolved_host.endswith(suffix) for suffix in POSTER_HOST_SUFFIXES):
                    raise ValueError("The poster download redirected outside the metadata image hosts")
                if not response.headers.get_content_type().startswith("image/"):
                    raise ValueError("The metadata poster address did not return an image")
                received = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_POSTER_BYTES:
                        raise ValueError("The metadata poster is too large")
                    output.write(chunk)
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return str(target)


def _fetch_jikan(title: str, cache_dir: str | Path) -> dict:
    query = urllib.parse.urlencode({"q": clean_search_title(title), "limit": 20, "sfw": "true"})
    request = urllib.request.Request(
        f"{API_ROOT}/anime?{query}",
        headers={"User-Agent": "AnimeWatcher/1.0 (personal local library)"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    candidates = payload.get("data") or []
    if not candidates:
        raise LookupError(f"No metadata found for {title}")
    item = _select_best_candidate(title, candidates, _jikan_title_variants, "Jikan")
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
    query = urllib.parse.urlencode({"filter[text]": clean_search_title(title), "page[limit]": 20})
    request = urllib.request.Request(
        f"{KITSU_ROOT}/anime?{query}",
        headers={"User-Agent": "AnimeWatcher/1.0", "Accept": "application/vnd.api+json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    candidates = payload.get("data") or []
    if not candidates:
        raise LookupError(f"No Kitsu metadata found for {title}")
    item = _select_best_candidate(title, candidates, _kitsu_title_variants, "Kitsu")
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


def _screen_title(title):
    value = clean_search_title(title)
    match = re.search(r'(?:\s*[\[(]((?:19|20)\d{2})[\])]|\s+((?:19|20)\d{2}))$', value)
    if match and value[:match.start()].strip():
        return value[:match.start()].strip(), int(match.group(1) or match.group(2))
    return value, None


def _fetch_tvmaze(title: str, cache_dir: str | Path, *, screen=False) -> dict:
    lookup, year = _screen_title(title) if screen else (clean_search_title(title), None)
    query = urllib.parse.urlencode({"q": lookup})
    request = urllib.request.Request(f"{TVMAZE_ROOT}/search/shows?{query}", headers={"User-Agent": "AnimeWatcher/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        candidates = json.load(response)
    if not candidates:
        raise LookupError(f"No TVmaze metadata found for {title}")
    if year:
        candidates = [candidate for candidate in candidates if str((candidate.get('show') or {}).get('premiered') or '').startswith(str(year))]
    selected = _select_best_candidate(
        lookup,
        candidates,
        lambda candidate: [(candidate.get("show") or {}).get("name")],
        "TVmaze",
    )
    item = selected["show"]
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
        "provider": "TVmaze",
        "source_url": f"https://www.tvmaze.com/shows/{int(item['id'])}",
    }


def _fetch_tv_show(title, cache_dir):
    return _fetch_tvmaze(title, cache_dir, screen=True)


def _fetch_wikipedia_movie(title, cache_dir):
    lookup, requested_year = _screen_title(title)
    query = urllib.parse.urlencode(dict(action='query', format='json', generator='search',
        gsrsearch=lookup + ' film', gsrnamespace=0, gsrlimit=12,
        prop='extracts|pageimages|pageterms', exintro=1, explaintext=1,
        piprop='original', pilicense='any', wbptterms='description'))
    request = urllib.request.Request(f'{WIKIPEDIA_API}?{query}', headers={'User-Agent': 'AnimeWatcher/1.1 (local media metadata)'})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    candidates = []
    for page in (payload.get('query', {}).get('pages', {}) or {}).values():
        description = ' '.join((page.get('terms') or {}).get('description') or [])
        # Only movie articles, never the similarly named book, soundtrack or TV series.
        if not re.search(r'\bfilm\b', description, re.I) or re.search(r'\b(?:character|album|soundtrack|franchise|series|actor|actress|filmography|animal|song|list)\b', description, re.I):
            continue
        year = re.search(r'\b(?:18|19|20)\d{2}\b', description)
        page['_year'] = int(year.group()) if year else None
        page['_display'] = re.sub(r'\s*\((?:(?:18|19|20)\d{2}\s+)?film\)$', '', page['title'])
        if requested_year and page['_year'] != requested_year: continue
        candidates.append(page)
    candidates.sort(key=lambda page: page.get('index', 999))
    item = _select_best_candidate(lookup, candidates, lambda page: [page['_display'], page['title']], 'Wikipedia movie')
    score = _title_match_score(lookup, item['_display'])
    if not requested_year and any(page is not item and page['_year'] != item['_year'] and
            _title_match_score(lookup, page['_display']) >= score - 0.01 for page in candidates):
        raise LookupError('Several movies share this title. Include the release year in the library title, then Grab details again.')
    return dict(id=int(item['pageid']), title=item['_display'], synopsis=item.get('extract') or '',
                poster_path=_download_poster((item.get('original') or {}).get('source'), cache_dir, f"wikipedia-{item['pageid']}"),
                year=item['_year'], episodes=None, season=None, provider='Wikipedia',
                source_url='https://en.wikipedia.org/wiki/' + urllib.parse.quote(item['title'].replace(' ', '_'), safe=''))


def fetch_metadata(title: str, cache_dir: str | Path, library_type: str = 'Anime') -> dict:
    """Fetch cached poster/title data with independent provider fallbacks."""
    failures = []
    providers = {'Anime': (_fetch_jikan, _fetch_kitsu, _fetch_tvmaze),
                 'Movies': (_fetch_wikipedia_movie,), 'TV Shows': (_fetch_tv_show,)}
    if library_type not in providers:
        raise ValueError('Choose Anime, Movies, or TV Shows for title metadata.')
    for provider in providers[library_type]:
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


def metadata_source_url(provider, url):
    """Only provider-owned attribution links, never arbitrary stored URLs."""
    prefix = {'Wikipedia': 'https://en.wikipedia.org/wiki/', 'TVmaze': 'https://www.tvmaze.com/shows/'}.get(provider)
    return url if prefix and isinstance(url, str) and url.startswith(prefix) else ''
