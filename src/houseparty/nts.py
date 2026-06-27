"""NTS Radio API client + content catalog + target resolution.

NTS exposes everything we need without authentication:

* The two live stations are stable, hardcoded MP3 Icecast URLs.
* The infinite mixtapes come from ``GET /api/v2/mixtapes``; each result carries
  an ``audio_stream_endpoint`` MP3 URL plus alias/title/subtitle. The numeric
  ``mixtapeN`` in the URL is *not* sequential and the lineup changes, so we
  always read the catalog from the API (cached with a TTL) rather than
  hardcoding it.
* ``GET /api/v2/live`` gives now-playing metadata for both channels (it carries
  no audio URLs — those stay the hardcoded live URLs).
"""

from __future__ import annotations

import difflib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import config_dir

MIXTAPES_URL = "https://www.nts.live/api/v2/mixtapes"
LIVE_URL = "https://www.nts.live/api/v2/live"

# channel key -> (display title, MP3 Icecast stream URL)
LIVE_STATIONS: dict[str, tuple[str, str]] = {
    "1": ("NTS 1", "https://stream-relay-geo.ntslive.net/stream"),
    "2": ("NTS 2", "https://stream-relay-geo.ntslive.net/stream2"),
}

_CACHE_TTL = 24 * 60 * 60  # 24h
_TIMEOUT = 15.0


class NTSError(RuntimeError):
    """Raised for NTS API/resolution failures with a user-facing message."""


@dataclass(frozen=True)
class Mixtape:
    alias: str
    title: str
    subtitle: str
    stream_url: str


@dataclass(frozen=True)
class Broadcast:
    channel: str
    title: str
    show_name: str
    location: str
    genres: list[str]


def _cache_file() -> Path:
    return config_dir() / "mixtapes.json"


def _parse_mixtapes(payload: dict) -> list[Mixtape]:
    out: list[Mixtape] = []
    for item in payload.get("results", []):
        url = item.get("audio_stream_endpoint")
        alias = item.get("mixtape_alias")
        if not url or not alias:
            continue
        out.append(
            Mixtape(
                alias=alias,
                title=item.get("title", alias),
                subtitle=item.get("subtitle", ""),
                stream_url=url,
            )
        )
    return out


def fetch_mixtapes(force_refresh: bool = False) -> list[Mixtape]:
    """Return the infinite-mixtape catalog, using a 24h on-disk cache.

    Falls back to a stale cache if the network fetch fails.
    """
    cache = _cache_file()
    if not force_refresh and cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < _CACHE_TTL:
            try:
                return _parse_mixtapes(json.loads(cache.read_text()))
            except (ValueError, OSError):
                pass  # fall through to refetch

    try:
        resp = httpx.get(MIXTAPES_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        if cache.exists():  # serve stale rather than fail hard
            try:
                return _parse_mixtapes(json.loads(cache.read_text()))
            except (ValueError, OSError):
                pass
        raise NTSError(f"Could not fetch NTS mixtapes: {exc}") from exc

    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload))
    except OSError:
        pass  # cache is best-effort
    return _parse_mixtapes(payload)


def fetch_now() -> list[Broadcast]:
    """Return the current on-air broadcast for both live channels."""
    try:
        resp = httpx.get(LIVE_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise NTSError(f"Could not fetch NTS now-playing: {exc}") from exc

    out: list[Broadcast] = []
    for result in payload.get("results", []):
        now = result.get("now") or {}
        details = (now.get("embeds") or {}).get("details") or {}
        genres = [g.get("value", "") for g in details.get("genres", []) if g.get("value")]
        out.append(
            Broadcast(
                channel=result.get("channel_name", "?"),
                title=now.get("broadcast_title", "").strip(),
                show_name=details.get("name", "").strip(),
                location=details.get("location_long", "").strip(),
                genres=genres,
            )
        )
    return out


def _normalize(text: str) -> str:
    return text.lower().replace("-", " ").replace("_", " ").strip()


def resolve(target: str, mixtapes: list[Mixtape] | None = None) -> tuple[str, str]:
    """Resolve a target to ``(display_title, stream_url)``.

    ``target`` is ``"1"``/``"2"`` for a live station, or a mixtape alias or title
    (case- and hyphen-insensitive, with a fuzzy fallback). Raises ``NTSError``
    with the available options if nothing matches.
    """
    key = target.strip()
    if key in LIVE_STATIONS:
        return LIVE_STATIONS[key]

    if mixtapes is None:
        mixtapes = fetch_mixtapes()

    norm = _normalize(key)
    # exact match on normalized alias or title
    for mt in mixtapes:
        if norm in (_normalize(mt.alias), _normalize(mt.title)):
            return (mt.title, mt.stream_url)

    # fuzzy fallback across aliases and titles
    candidates: dict[str, Mixtape] = {}
    for mt in mixtapes:
        candidates[_normalize(mt.alias)] = mt
        candidates[_normalize(mt.title)] = mt
    match = difflib.get_close_matches(norm, list(candidates), n=1, cutoff=0.6)
    if match:
        mt = candidates[match[0]]
        return (mt.title, mt.stream_url)

    options = ", ".join(["1", "2", *sorted(mt.alias for mt in mixtapes)])
    raise NTSError(f"Unknown station/mixtape {target!r}. Options: {options}")
