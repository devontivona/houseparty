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

import html
import re
from dataclasses import dataclass

import soco
from soco import SoCo
from soco.discovery import by_name, scan_network
from soco.exceptions import SoCoException
from soco.music_services import MusicService
from soco.plugins.sharelink import ShareLinkPlugin


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


def _form_group(speakers: list[SoCo]) -> tuple[SoCo, list[str]]:
    """Make ``speakers`` an exclusive group; return (coordinator, skipped names).

    Any speaker currently grouped with a target but NOT in the target list is
    dropped (unjoined, which stops it), so `play ... -s X` means "play on exactly
    X". A member that fails to join (e.g. a wedged speaker returning UPnP 501) is
    skipped rather than aborting the whole operation; the coordinator must work.
    """
    coordinator = speakers[0]
    target_uids = {s.uid for s in speakers}

    # Drop speakers grouped with a target but not themselves a target (best-effort).
    extras: dict[str, SoCo] = {}
    for s in speakers:
        grp = getattr(s, "group", None)
        if grp:
            for m in grp.members:
                if m.uid not in target_uids:
                    extras[m.uid] = m
    for m in extras.values():
        try:
            m.unjoin()
        except SoCoException:
            pass

    # The coordinator must be controllable — fail clearly if not.
    try:
        coordinator.unjoin()
    except SoCoException as exc:
        raise SonosError(
            f"Can't play on {coordinator.player_name!r}: {exc}. "
            "The speaker may need a power-cycle."
        ) from exc

    # Members that fail to join are skipped, not fatal.
    skipped: list[str] = []
    for member in speakers[1:]:
        try:
            member.join(coordinator)
        except SoCoException:
            skipped.append(member.player_name)
    return coordinator, skipped


def play(
    speakers: list[SoCo],
    title: str,
    url: str,
    volume: int | None = None,
) -> list[str]:
    """Play ``url`` on exactly the given speakers; return any that were skipped.

    The listed speakers become an exclusive group; any other speakers that were
    grouped with them are dropped. A speaker that can't join is skipped.
    """
    if not speakers:
        raise SonosError("No speakers to play on.")

    coordinator, skipped = _form_group(speakers)
    _apply_volume(speakers, skipped, volume)

    try:
        coordinator.play_uri(url, title=title, force_radio=True)
    except SoCoException as exc:
        raise SonosError(
            f"Couldn't start playback on {coordinator.player_name!r}: {exc}"
        ) from exc
    return skipped


def spotify_linked(speaker: SoCo | None = None) -> bool:
    """Whether Spotify is available as a music service on this Sonos household.

    SoCo can't link the service — the user must add it in the Sonos app. This is
    a best-effort pre-flight; the deeper "present but no account" case is still
    caught when enqueuing fails. Note SoCo exposes available services, not
    per-account subscription state, so this can't perfectly distinguish the two.
    """
    try:
        names = MusicService.get_all_music_services_names()
    except Exception:  # noqa: BLE001 - any lookup failure -> treat as unknown
        return False
    return any("spotify" in n.lower() for n in names)


def play_spotify(
    speakers: list[SoCo],
    links: list[str],
    label: str = "",
    mode: str = "now",
    volume: int | None = None,
) -> list[str]:
    """Enqueue and play Spotify ``links`` on the given speakers; return skipped.

    Spotify is queue-based (unlike radio streams): each link is added to the
    coordinator's queue via ShareLinkPlugin, then played. ``links`` is normally
    one item, but several for an artist (its top tracks). ``mode``:
    ``now`` clears the queue and starts playback; ``add`` appends; ``next``
    inserts after the current track. Speakers that can't join are skipped.
    """
    if not speakers:
        raise SonosError("No speakers to play on.")
    if not links:
        raise SonosError("Nothing to play.")

    coordinator, skipped = _form_group(speakers)
    _apply_volume(speakers, skipped, volume)

    share = ShareLinkPlugin(coordinator)
    if mode == "now":
        coordinator.clear_queue()

    # Insert position is 1-based; 0 means append to the end of the queue.
    position = 0
    if mode == "next":
        try:
            cur = int(coordinator.get_current_track_info().get("playlist_position") or 0)
            position = cur + 1 if cur else 0
        except (TypeError, ValueError):
            position = 0

    first_idx: int | None = None
    try:
        for offset, link in enumerate(links):
            pos = position + offset if position else 0
            idx = share.add_share_link_to_queue(link, position=pos)
            if first_idx is None:
                first_idx = idx
    except SoCoException as exc:
        # Enqueue failures here are overwhelmingly UPnP 800 = Spotify not usable
        # for this household (not linked / wrong region). Point there, and keep
        # the raw error for debugging.
        raise SonosError(
            "Couldn't add the Spotify item to Sonos. This usually means Spotify "
            "isn't linked in your Sonos app for this household — add it in the "
            f"Sonos app (Settings > Services), then retry. (Sonos said: {exc})"
        ) from exc

    if mode == "now" and first_idx:
        # add_share_link_to_queue returns a 1-based index; play_from_queue is 0-based.
        coordinator.play_from_queue(first_idx - 1)
    return skipped


def _safe(fn) -> None:
    """Call ``fn`` ignoring Sonos errors (best-effort transport control)."""
    try:
        fn()
    except SoCoException:
        pass


def stop(speakers: list[SoCo]) -> None:
    """Stop playback on the targets and ungroup them.

    Why ungroup: on Sonos, stopping a group coordinator does NOT reliably stop
    its slaved members, and a slave can't be stopped directly
    (``SoCoSlaveException``). The one reliable primitive is **unjoin** — a player
    removed from its group stops. So we stop each coordinator (to halt the
    streams) and unjoin every target (to guarantee members go quiet). This ends
    the listening session and leaves speakers standalone; ``play`` re-forms groups
    from scratch, and ``pause`` is the non-destructive "I'll be right back" option.
    """
    coords: dict[str, SoCo] = {}
    for sp in speakers:
        try:
            c = sp.group.coordinator if sp.group else sp
        except SoCoException:
            c = sp
        coords[c.uid] = c
    for c in coords.values():
        _safe(c.stop)
    for sp in speakers:
        _safe(sp.unjoin)  # guarantees slaved members stop too


def pause(speakers: list[SoCo]) -> None:
    """Pause playback (resumable) on each target's group coordinator."""
    for c in _coordinators(speakers):
        _safe(c.pause)


def resume(speakers: list[SoCo]) -> None:
    """Resume playback on each target's group coordinator."""
    for c in _coordinators(speakers):
        _safe(c.play)


def _coordinators(speakers: list[SoCo]) -> list[SoCo]:
    """De-duplicate speakers down to their group coordinators.

    Skip/transport commands act on the whole group, so issuing one per member
    would over-skip; collapse to one coordinator per group.
    """
    out: dict[str, SoCo] = {}
    for sp in speakers:
        c = sp.group.coordinator if sp.group else sp
        out[c.uid] = c
    return list(out.values())


def skip_next(speakers: list[SoCo]) -> None:
    """Skip to the next track on each speaker's group."""
    for c in _coordinators(speakers):
        c.next()  # SoCoException (e.g. no next track) bubbles up for a clear message


def skip_previous(speakers: list[SoCo]) -> None:
    """Go to the previous track on each speaker's group."""
    for c in _coordinators(speakers):
        c.previous()


def set_volume(speakers: list[SoCo], level: int) -> list[str]:
    """Set volume on each speaker; return any that couldn't be reached."""
    level = _clamp_volume(level)
    skipped: list[str] = []
    for sp in speakers:
        try:
            sp.volume = level
        except SoCoException:
            skipped.append(sp.player_name)
    return skipped


_TITLE_RE = re.compile(r"<dc:title>(.*?)</dc:title>", re.DOTALL)


def now_playing(speaker: SoCo) -> dict[str, str]:
    """Return what a speaker is playing.

    Reads both ``GetMediaInfo`` and the track info, because they're useful for
    different sources:

    * **Radio (NTS):** ``GetMediaInfo`` carries the original, un-redirected
      ``CurrentURI`` and the ``dc:title`` we embed; the track info is blank.
    * **Spotify (queue):** ``CurrentURI`` is just the queue (``x-rincon-queue:``),
      so the real track/artist/album come from ``get_current_track_info()``.
    """
    coordinator = speaker.group.coordinator if speaker.group else speaker
    media = coordinator.avTransport.GetMediaInfo([("InstanceID", 0)])
    state = coordinator.get_current_transport_info().get("current_transport_state", "")
    track = coordinator.get_current_track_info() or {}

    embedded = _TITLE_RE.search(media.get("CurrentURIMetaData") or "")
    return {
        "transport_state": state,
        "source_uri": media.get("CurrentURI", ""),
        "source_title": html.unescape(embedded.group(1)) if embedded else "",
        "track_title": track.get("title", ""),
        "track_artist": track.get("artist", ""),
        "track_album": track.get("album", ""),
    }


def _clamp_volume(level: int) -> int:
    return max(0, min(100, int(level)))


def _apply_volume(speakers: list[SoCo], skipped: list[str], volume: int | None) -> None:
    """Set ``volume`` on each non-skipped speaker before playback.

    If a speaker rejects the volume command (e.g. a wedged player returning UPnP
    501), DROP it from the group rather than letting it play at an unknown level —
    a speaker stuck loud is worse than one that's silent. Dropped speakers are
    appended to ``skipped`` so the caller can report them.
    """
    if volume is None:
        return
    skip = set(skipped)
    level = _clamp_volume(volume)
    for sp in speakers:
        if sp.player_name in skip:
            continue
        try:
            sp.volume = level
        except SoCoException:
            try:
                sp.unjoin()  # can't control it -> don't let it blast
            except SoCoException:
                pass
            skipped.append(sp.player_name)
            skip.add(sp.player_name)
