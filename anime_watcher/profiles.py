from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_PROFILE_ID = "default"


@dataclass(frozen=True)
class Profile:
    id: str
    name: str


class ProfileManager:
    """Small profile registry; each profile receives an isolated database."""

    def __init__(self, data_root: str | Path):
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.data_root / "profiles.json"
        self._profiles: list[Profile] = []
        self._active_id = DEFAULT_PROFILE_ID
        self._portable = {}
        self._load()

    def _load(self) -> None:
        payload: dict = {}
        if self.registry_path.is_file():
            try:
                payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
        entries = payload.get("profiles") if isinstance(payload, dict) else None
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                profile_id = str(entry.get("id", "")).strip()
                name = str(entry.get("name", "")).strip()
                if profile_id and name and not any(item.id == profile_id for item in self._profiles):
                    self._profiles.append(Profile(profile_id, name))
        if not self._profiles:
            self._profiles = [Profile(DEFAULT_PROFILE_ID, "Default")]
        requested = str(payload.get("active", DEFAULT_PROFILE_ID)) if isinstance(payload, dict) else DEFAULT_PROFILE_ID
        portable = payload.get('portable', {}) if isinstance(payload, dict) else {}
        self._portable = {key:row for key,row in portable.items() if isinstance(row,dict)
                          and all(isinstance(row.get(field),str) for field in ('identity','profile','root'))
                          and key in {profile.id for profile in self._profiles}} if isinstance(portable, dict) else {}
        self._active_id = requested if any(item.id == requested for item in self._profiles) else self._profiles[0].id
        self._save()

    def _save(self) -> None:
        payload = {"active": self._active_id, "profiles": [asdict(item) for item in self._profiles], 'portable':self._portable}
        temporary = self.registry_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.registry_path)

    def profiles(self) -> tuple[Profile, ...]:
        return tuple(self._profiles)

    @property
    def active(self) -> Profile:
        return next(item for item in self._profiles if item.id == self._active_id)

    def create(self, name: str) -> Profile:
        clean_name = " ".join(name.strip().split())
        if not clean_name:
            raise ValueError("Enter a profile name")
        if any(item.name.casefold() == clean_name.casefold() for item in self._profiles):
            raise ValueError("A profile already uses that name")
        profile = Profile(uuid.uuid4().hex[:12], clean_name)
        self._profiles.append(profile)
        self._save()
        return profile

    def rename(self, profile_id: str, name: str) -> Profile:
        clean_name = " ".join(name.strip().split())
        if not clean_name:
            raise ValueError("Enter a profile name")
        if any(item.id != profile_id and item.name.casefold() == clean_name.casefold() for item in self._profiles):
            raise ValueError("A profile already uses that name")
        for index, profile in enumerate(self._profiles):
            if profile.id == profile_id:
                updated = Profile(profile.id, clean_name)
                self._profiles[index] = updated
                self._save()
                return updated
        raise ValueError("Profile not found")

    def set_active(self, profile_id: str) -> Profile:
        profile = next((item for item in self._profiles if item.id == profile_id), None)
        if profile is None:
            raise ValueError("Profile not found")
        self._active_id = profile.id
        self._save()
        return profile

    def database_path(self, profile_id: str | None = None) -> Path:
        target = profile_id or self._active_id
        if target == DEFAULT_PROFILE_ID:
            # Preserve every existing user's library and progress in place.
            return self.data_root / "library.db"
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", target)
        return self.data_root / "profiles" / safe_id / "library.db"

    def portable(self, profile_id=None):
        return self._portable.get(profile_id or self._active_id)

    def attach_portable(self, record, profile_id=None):
        key = profile_id or self._active_id
        if record is None: self._portable.pop(key, None)
        else: self._portable[key] = dict(record)
        self._save()
