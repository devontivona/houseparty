"""Persistent config + a cache directory for houseparty.

Config lives at ``~/.config/houseparty/config.toml`` and holds the user's
default speakers, an optional default volume, and a cached name->IP map used as
a fallback when multicast discovery is blocked on the network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w


def config_dir() -> Path:
    """Return the houseparty config/cache directory, honoring ``XDG_CONFIG_HOME``."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "houseparty"


def config_path() -> Path:
    return config_dir() / "config.toml"


@dataclass
class Config:
    default_speakers: list[str] = field(default_factory=list)
    default_volume: int | None = None
    speaker_ips: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        if not path.exists():
            return cls()
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls(
            default_speakers=list(data.get("default_speakers", [])),
            default_volume=data.get("default_volume"),
            speaker_ips=dict(data.get("speaker_ips", {})),
        )

    def save(self) -> Path:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {
            "default_speakers": self.default_speakers,
            "speaker_ips": self.speaker_ips,
        }
        if self.default_volume is not None:
            data["default_volume"] = self.default_volume
        with path.open("wb") as f:
            tomli_w.dump(data, f)
        return path
