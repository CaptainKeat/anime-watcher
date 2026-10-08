from __future__ import annotations

import argparse
import json
import marshal
import os
import re
import subprocess
import tempfile
import types
import zipfile
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parent
TEXT_SUFFIXES = {".bat", ".css", ".html", ".ini", ".js", ".json", ".md", ".ps1", ".py", ".toml", ".txt", ".yaml", ".yml"}
BANNED_SUFFIXES = {
    ".3gp", ".avi", ".cookie", ".cookies", ".db", ".flv", ".m2ts", ".m4v",
    ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ogv", ".p12", ".pem",
    ".pfx", ".sqlite", ".sqlite3", ".ts", ".webm", ".wmv",
}
BANNED_NAMES = {
    ".env", "cookies.txt", "crash.log", "download-queue.json", "profiles.json",
}
BANNED_PARTS = {".venv", "build", "downloads", "posters", "previews", "release", "vendor"}
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
USER_PATH_PATTERN = re.compile(r"(?i)\b[A-Z]:[\\/]Users[\\/][^\\/\s`\"']+")
SECRET_PATTERNS = {
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
}


def _identity_values() -> set[str]:
    values = {
        os.environ.get("USERNAME", ""),
        os.environ.get("COMPUTERNAME", ""),
        os.environ.get("USERPROFILE", ""),
    }
    profile = os.environ.get("USERPROFILE")
    if profile:
        values.add(Path(profile).name)
    return {value for value in values if len(value.strip()) >= 4}


def _scan_text(
    label: str,
    text: str,
    identities: set[str] | None = None,
    *,
    scan_email: bool = True,
) -> list[str]:
    findings: list[str] = []
    if scan_email:
        for match in EMAIL_PATTERN.finditer(text):
            email = match.group(0)
            if not email.casefold().endswith("@users.noreply.github.com"):
                findings.append(f"{label}: email address {email!r}")
    for match in USER_PATH_PATTERN.finditer(text):
        findings.append(f"{label}: Windows user path {match.group(0)!r}")
    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            findings.append(f"{label}: possible {name}")
    for identity in identities if identities is not None else _identity_values():
        if identity.casefold() in text.casefold():
            findings.append(f"{label}: local identity value {identity!r}")
    return findings


def _prospective_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=True,
    )
    return [root / os.fsdecode(value) for value in result.stdout.split(b"\0") if value]


def audit_source(root: Path = PROJECT_ROOT) -> dict:
    findings: list[str] = []
    files = _prospective_files(root)
    identities = _identity_values()
    scanned_text = 0
    for path in files:
        relative = path.relative_to(root)
        parts = {part.casefold() for part in relative.parts}
        suffix = path.suffix.casefold()
        if parts & BANNED_PARTS:
            findings.append(f"{relative}: release-excluded directory is tracked")
        if suffix in BANNED_SUFFIXES or path.name.casefold() in BANNED_NAMES:
            findings.append(f"{relative}: private/runtime/media file type is not release-safe")
        if path.is_file() and suffix in TEXT_SUFFIXES and "third_party" not in parts:
            scanned_text += 1
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                findings.append(f"{relative}: expected UTF-8 text could not be audited")
                continue
            findings.extend(_scan_text(str(relative), text, identities))
    return {
        "kind": "source",
        "status": "clean" if not findings else "failed",
        "files": len(files),
        "text_files": scanned_text,
        "findings": sorted(set(findings)),
    }


def _code_strings(code: types.CodeType):
    yield code.co_filename
    for value in code.co_consts:
        if isinstance(value, str):
            yield value
        elif isinstance(value, types.CodeType):
            yield from _code_strings(value)


def _audit_embedded_app(executable: Path, identities: set[str]) -> tuple[list[str], int]:
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError as exc:
        return [f"{executable.name}: PyInstaller archive reader is unavailable: {exc}"], 0
    findings: list[str] = []
    archive = CArchiveReader(str(executable))
    modules = 0
    if "app" not in archive.toc or "PYZ.pyz" not in archive.toc:
        return [f"{executable.name}: required PyInstaller app/PYZ entries are missing"], 0
    app_code = marshal.loads(archive.extract("app"))
    findings.extend(_scan_text("embedded app", "\n".join(_code_strings(app_code)), identities))
    modules += 1
    pyz = archive.open_embedded_archive("PYZ.pyz")
    names = sorted(name for name in pyz.toc if name == "anime_watcher" or name.startswith("anime_watcher."))
    if "anime_watcher.updater" not in names:
        findings.append(f"{executable.name}: anime_watcher.updater is not embedded")
    for name in names:
        code = pyz.extract(name)
        if isinstance(code, types.CodeType):
            findings.extend(_scan_text(f"embedded {name}", "\n".join(_code_strings(code)), identities))
            modules += 1
    return findings, modules


def audit_archive(archive_path: Path) -> dict:
    findings: list[str] = []
    identities = _identity_values()
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        for item in entries:
            pure = PurePosixPath(item.filename)
            if pure.is_absolute() or ".." in pure.parts or not pure.parts or pure.parts[0] != "Anime Watcher":
                findings.append(f"archive entry {item.filename!r}: unsafe or incorrect root")
            is_certifi_ca_bundle = item.filename == "Anime Watcher/_internal/certifi/cacert.pem"
            if (
                pure.suffix.casefold() in BANNED_SUFFIXES
                and not is_certifi_ca_bundle
            ) or pure.name.casefold() in BANNED_NAMES:
                findings.append(f"archive entry {item.filename!r}: private/runtime/media file type")
            # Qt high-DPI asset names use an at-sign before 2x and resemble email
            # addresses, so archive paths receive identity/secret/path checks only.
            # App-owned code and strings still receive the full email scan below.
            findings.extend(_scan_text(
                f"archive name {item.filename}", item.filename, identities,
                scan_email=False,
            ))
        executable_entry = next((item for item in entries if item.filename == "Anime Watcher/Anime Watcher.exe"), None)
        if executable_entry is None:
            findings.append("archive: Anime Watcher/Anime Watcher.exe is missing")
            modules = 0
        else:
            with tempfile.TemporaryDirectory() as directory:
                executable = Path(directory) / "Anime Watcher.exe"
                executable.write_bytes(archive.read(executable_entry))
                embedded_findings, modules = _audit_embedded_app(executable, identities)
                findings.extend(embedded_findings)
    return {
        "kind": "archive",
        "status": "clean" if not findings else "failed",
        "archive": archive_path.name,
        "entries": len(entries),
        "app_modules": modules,
        "findings": sorted(set(findings)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Anime Watcher release inputs and packages for privacy leaks.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", action="store_true")
    group.add_argument("--archive", type=Path)
    args = parser.parse_args()
    result = audit_source() if args.source else audit_archive(args.archive.resolve())
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "clean" else 1


if __name__ == "__main__":
    raise SystemExit(main())
