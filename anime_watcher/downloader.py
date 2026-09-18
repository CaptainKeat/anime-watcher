from __future__ import annotations

import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from .organizer import VIDEO_EXTENSIONS, organize_file


MAX_CATALOG_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class CatalogResult:
    title: str
    url: str
    direct_media: bool = False


@dataclass(frozen=True)
class EpisodeResult:
    title: str
    url: str
    direct_open: bool = True


@dataclass(frozen=True)
class _PageLink:
    href: str
    label: str
    attributes: dict[str, str]


class _CatalogLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[_PageLink] = []
        self._href: str | None = None
        self._attributes: dict[str, str] = {}
        self._label = ""
        self._fallback = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        values = {str(key).lower(): (value or "") for key, value in attrs}
        self._href = values.get("href")
        self._attributes = values
        self._fallback = values.get("title") or values.get("aria-label") or ""
        self._label = ""

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._label += f" {data}"

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            label = " ".join((self._label or self._fallback).split())
            self.links.append(_PageLink(self._href, label, self._attributes))
            self._href = None
            self._attributes = {}
            self._label = ""
            self._fallback = ""


def _validated_http_url(url: str) -> str:
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a complete HTTP(S) source URL")
    return url


def _title_from_url(url: str) -> str:
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path).rstrip("/")
    slug = Path(path).stem if path else ""
    return " ".join(re.sub(r"[-_.]+", " ", slug).split())


def _is_direct_media(url: str) -> bool:
    return Path(urllib.parse.urlparse(url).path).suffix.lower() in VIDEO_EXTENSIONS


def _fetch_public_html(url: str) -> tuple[str, str]:
    page_url = _validated_http_url(url)
    request = urllib.request.Request(
        page_url,
        headers={"User-Agent": "AnimeWatcher/1.0", "Accept": "text/html,application/xhtml+xml"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("That address did not return a public HTML page")
        raw = response.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES:
            raise ValueError("The source page is too large to search safely")
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), response.geturl()


def extract_catalog_results(html: str, page_url: str, query: str,
                            max_results: int = 40) -> list[CatalogResult]:
    """Return case-insensitive partial title matches from links in an HTML page."""
    needle = " ".join(query.casefold().split())
    if len(needle) < 2:
        raise ValueError("Type at least two characters to search")
    parser = _CatalogLinkParser()
    parser.feed(html)
    results: list[CatalogResult] = []
    seen: set[str] = set()
    for link in parser.links:
        absolute = urllib.parse.urljoin(page_url, link.href)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        absolute = urllib.parse.urlunparse(parsed._replace(fragment=""))
        title = link.label or _title_from_url(absolute)
        searchable = f"{title} {_title_from_url(absolute)}".casefold()
        if needle not in " ".join(searchable.split()) or absolute in seen:
            continue
        seen.add(absolute)
        results.append(CatalogResult(title=title or absolute, url=absolute,
                                     direct_media=_is_direct_media(absolute)))
        if len(results) >= max_results:
            break
    return results


def extract_episode_results(html: str, page_url: str, max_results: int = 500) -> list[EpisodeResult]:
    """Extract public episode-page links without resolving or inspecting media players."""
    parser = _CatalogLinkParser()
    parser.feed(html)
    episode_pattern = re.compile(r"\b(?:episode|ep\.?)\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)
    results: list[EpisodeResult] = []
    seen: set[tuple[str, str]] = set()
    for link in parser.links:
        match = episode_pattern.search(link.label)
        if not match:
            continue
        absolute = urllib.parse.urljoin(page_url, link.href)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        absolute = urllib.parse.urlunparse(parsed._replace(fragment=""))
        title = f"Episode {match.group(1)}"
        identity = (absolute, title.casefold())
        if identity in seen:
            continue
        seen.add(identity)

        event_code = f"{link.attributes.get('onclick', '')} {link.attributes.get('onmouseover', '')}".casefold()
        cookie_selected = parsed.path.casefold().endswith("/gate.php") and (
            "gatea(" in event_code or "gateh(" in event_code
        )
        results.append(EpisodeResult(title=title, url=absolute, direct_open=not cookie_selected))
        if len(results) >= max_results:
            break
    return results


def load_catalog_episodes(page_url: str, max_results: int = 500) -> list[EpisodeResult]:
    """Read a public anime page and return its episode navigation links.

    Cookie/JavaScript-selected watch pages are marked as non-direct so callers can
    return users to the title page instead of opening an ambiguous shared URL.
    """
    html, resolved_url = _fetch_public_html(page_url)
    return extract_episode_results(html, resolved_url, max_results)


def _search_page_urls(source_url: str, query: str) -> list[str]:
    source_url = _validated_http_url(source_url)
    encoded = urllib.parse.quote_plus(query.strip())
    if "{query}" in source_url:
        return [source_url.replace("{query}", encoded)]
    parsed = urllib.parse.urlparse(source_url)
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    candidates = [
        source_url,
        urllib.parse.urljoin(origin, f"search.php?s={encoded}"),
        urllib.parse.urljoin(origin, f"fastsearch.php?xhr=1&s={encoded}"),
        urllib.parse.urljoin(origin, f"search?q={encoded}"),
        urllib.parse.urljoin(origin, f"search?keyword={encoded}"),
    ]
    separator = "&" if parsed.query else "?"
    candidates.append(f"{source_url}{separator}s={encoded}")
    return list(dict.fromkeys(candidates))


def search_catalog(source_url: str, query: str, max_results: int = 40) -> list[CatalogResult]:
    """Search a supplied catalog page or its common public search endpoints.

    This only reads public HTML and returns links. It does not resolve stream players,
    bypass access controls, or turn protected playback pages into downloads.
    """
    if len(" ".join(query.split())) < 2:
        raise ValueError("Type at least two characters to search")
    last_error: Exception | None = None
    fetched_page = False
    combined: list[CatalogResult] = []
    seen: set[str] = set()
    for page_url in _search_page_urls(source_url, query):
        try:
            html, resolved_url = _fetch_public_html(page_url)
            fetched_page = True
            for result in extract_catalog_results(html, resolved_url, query, max_results):
                if result.url not in seen:
                    seen.add(result.url)
                    combined.append(result)
                    if len(combined) >= max_results:
                        return combined
            if combined:
                return combined
        except Exception as exc:
            last_error = exc
    if last_error and not combined and not fetched_page:
        raise ValueError(f"Could not search that source: {last_error}") from last_error
    return combined


def download_authorized_file(url: str, download_dir: str | Path, library_root: str | Path,
                             progress: Callable[[int, int], None] | None = None):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only HTTP(S) direct file URLs are supported")
    request = urllib.request.Request(url, headers={"User-Agent": "AnimeWatcher/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        disposition = response.headers.get("Content-Disposition", "")
        match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', disposition, re.I)
        name = urllib.parse.unquote(match.group(1)) if match else Path(parsed.path).name
        if Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError("The URL must point directly to a supported video file")
        target_dir = Path(download_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        temp = target_dir / f"{name}.part"
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        with temp.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                if progress:
                    progress(received, total)
        completed = target_dir / name
        temp.replace(completed)
    return organize_file(completed, library_root)
