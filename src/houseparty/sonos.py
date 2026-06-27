"""Sonos control via SoCo (local UPnP).

We use local control rather than the Sonos cloud Control API: the cloud path
needs OAuth + a registered music service and can't easily play arbitrary URLs,
whereas SoCo talks straight to the players on the LAN and accepts any reachable
stream URL.

The one non-obvious detail is ``play_uri(..., force_radio=True)``: modern Sonos
firmware rejects bare ``http(s)://`` URIs for live radio, so SoCo rewrites the
scheme to ``x-rincon-mp3radio://`` and generates DIDL metadata so the station
name shows in the app.
"""

from __future__ import annotations

from dataclasses import dataclass

import soco
from soco import SoCo
from soco.discovery import by_name, scan_network


class SonosError(RuntimeError):
    """Raised for speaker discovery/control failures with a user-facing message."""


@dataclass(frozen=True)
class SpeakerInfo:
    name: str
    ip: str


def _all_zones() -> list[SoCo]:
    zones = soco.discover() or set()
    return sorted(zones, key=lambda z: z.player_name or "")


def list_speakers() -> list[SpeakerInfo]:
    """Discover all visible speakers on the network."""
    return [SpeakerInfo(z.player_name, z.ip_address) for z in _all_zones()]


def _find_one(name: str, speaker_ips: dict[str, str]) -> SoCo:
    """Resolve a single speaker by room name, with fallbacks for flaky multicast.

    Order: SoCo's ``by_name`` (multicast) -> cached IP from config ->
    full-network scan.
    """
    zone = by_name(name)
    if zone is not None:
        return zone

    ip = speaker_ips.get(name)
    if ip:
        try:
            candidate = SoCo(ip)
            if candidate.player_name:  # reachable
                return candidate
        except Exception:  # noqa: BLE001 - any network error -> keep falling back
            pass

    zones = scan_network(include_invisible=False) or set()
    for z in zones:
        if z.player_name == name:
            return z

    available = ", ".join(s.name for s in list_speakers()) or "(none found)"
    raise SonosError(f"Speaker {name!r} not found. Available: {available}")


def resolve_speakers(names: list[str], speaker_ips: dict[str, str] | None = None) -> list[SoCo]:
    if not names:
        raise SonosError("No speaker specified (pass --speaker or set a default).")
    speaker_ips = speaker_ips or {}
    return [_find_one(n, speaker_ips) for n in names]


def play(
    speakers: list[SoCo],
    title: str,
    url: str,
    volume: int | None = None,
) -> None:
    """Play ``url`` on the given speakers, grouping them if more than one.

    Playback is sent to the first speaker (the group coordinator); any others
    join its group and follow along.
    """
    if not speakers:
        raise SonosError("No speakers to play on.")

    coordinator = speakers[0]
    for member in speakers[1:]:
        member.join(coordinator)

    if volume is not None:
        for sp in speakers:
            sp.volume = _clamp_volume(volume)

    coordinator.play_uri(url, title=title, force_radio=True)


def stop(speakers: list[SoCo]) -> None:
    for sp in speakers:
        # commands must go to the group coordinator
        (sp.group.coordinator if sp.group else sp).stop()


def set_volume(speakers: list[SoCo], level: int) -> None:
    level = _clamp_volume(level)
    for sp in speakers:
        sp.volume = level


def now_playing(speaker: SoCo) -> dict[str, str]:
    """Return the speaker's current track info (title/artist/uri/state)."""
    coordinator = speaker.group.coordinator if speaker.group else speaker
    info = coordinator.get_current_track_info()
    info["transport_state"] = coordinator.get_current_transport_info().get(
        "current_transport_state", ""
    )
    return info


def _clamp_volume(level: int) -> int:
    return max(0, min(100, int(level)))
