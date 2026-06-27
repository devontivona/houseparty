"""Persistent config + a cache directory for houseparty.

Config lives at ``~/.config/houseparty/config.toml`` and holds the user's
default speakers, an optional default volume, a cached name->IP map used as a
fallback when multicast discovery is blocked on the network, and Spotify app
credentials/preferences.
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


def spotify_token_path() -> Path:
    """Path to spotipy's OAuth token cache (managed by spotipy, not us)."""
    return config_dir() / "spotify_token.json"


DEFAULT_REDIRECT_URI = "http://127.0.0.1:8080/callback"
DEFAULT_MARKET = "US"


@dataclass
class SpotifyConfig:
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str = DEFAULT_REDIRECT_URI
    market: str = DEFAULT_MARKET

    def resolved_client_id(self) -> str | None:
        """Config value, else the ``SPOTIFY_CLIENT_ID`` env var."""
        return self.client_id or os.environ.get("SPOTIFY_CLIENT_ID")

    def resolved_client_secret(self) -> str | None:
        return self.client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET")


@dataclass
class Config:
    default_speakers: list[str] = field(default_factory=list)
    default_volume: int | None = None
    speaker_ips: dict[str, str] = field(default_factory=dict)
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        if not path.exists():
            return cls()
        with path.open("rb") as f:
            data = tomllib.load(f)
        sp = data.get("spotify", {})
        return cls(
            default_speakers=list(data.get("default_speakers", [])),
            default_volume=data.get("default_volume"),
            speaker_ips=dict(data.get("speaker_ips", {})),
            spotify=SpotifyConfig(
                client_id=sp.get("client_id"),
                client_secret=sp.get("client_secret"),
                redirect_uri=sp.get("redirect_uri", DEFAULT_REDIRECT_URI),
                market=sp.get("market", DEFAULT_MARKET),
            ),
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

        spotify: dict = {
            "redirect_uri": self.spotify.redirect_uri,
            "market": self.spotify.market,
        }
        if self.spotify.client_id:
            spotify["client_id"] = self.spotify.client_id
        if self.spotify.client_secret:
            spotify["client_secret"] = self.spotify.client_secret
        data["spotify"] = spotify

        with path.open("wb") as f:
            tomli_w.dump(data, f)
        return path
