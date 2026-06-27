"""Spotify Web API client: search, library, and play-target resolution.

Uses spotipy with the Authorization Code flow (``SpotifyOAuth``), which reaches
the user's own library (private playlists, liked songs) in addition to the
public catalog. spotipy owns the OAuth token lifecycle — the browser callback,
the on-disk token cache, and refresh — which is why this module takes the one
dependency the rest of the project avoids.

Playback is NOT done here; this module only produces playable identifiers
(``spotify:`` URIs / open.spotify.com links) that ``sonos.play_spotify`` enqueues
via SoCo's ShareLinkPlugin. So no playback/Connect scopes are requested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from .config import Config, spotify_token_path

# Read-only scopes for catalog search + the user's own library. No playback
# scopes: Sonos plays locally, not via Spotify Connect.
SCOPES = "playlist-read-private playlist-read-collaborative user-library-read"

KINDS = ("track", "album", "artist", "playlist")

# ShareLinkPlugin supports these Spotify content types directly; an artist must
# be expanded to its top tracks (see resolve()).
_SHARELINK_KINDS = ("track", "album", "playlist")

_URI_RE = re.compile(r"spotify:(track|album|artist|playlist):([A-Za-z0-9]+)")
_LINK_RE = re.compile(r"open\.spotify\.com/(track|album|artist|playlist)/([A-Za-z0-9]+)")


class SpotifyError(RuntimeError):
    """User-facing Spotify failures (missing creds, no results, etc.)."""


@dataclass(frozen=True)
class SearchResult:
    kind: str  # track | album | artist | playlist
    name: str
    detail: str  # artist names / album / owner — human context
    uri: str  # spotify:track:...
    url: str  # https://open.spotify.com/...
    id: str

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "detail": self.detail,
            "uri": self.uri,
            "url": self.url,
            "id": self.id,
        }


@dataclass(frozen=True)
class PlayTarget:
    label: str  # what we tell the user is playing
    kind: str
    links: tuple[str, ...] = field(default_factory=tuple)  # 1 normally, N for an artist

    def as_dict(self) -> dict:
        return {"label": self.label, "kind": self.kind, "links": list(self.links)}


def _auth_manager(
    cfg: Config, open_browser: bool = True, redirect_uri: str | None = None
) -> SpotifyOAuth:
    sp_cfg = cfg.spotify
    client_id = sp_cfg.resolved_client_id()
    client_secret = sp_cfg.resolved_client_secret()
    if not client_id or not client_secret:
        raise SpotifyError(
            "Spotify is not configured. Set credentials with "
            "`houseparty spotify set-client <id> <secret>` "
            "(or the SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET env vars)."
        )
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri or sp_cfg.redirect_uri,
        scope=SCOPES,
        cache_path=str(spotify_token_path()),
        open_browser=open_browser,
    )


def client(
    cfg: Config | None = None, open_browser: bool = True, redirect_uri: str | None = None
) -> spotipy.Spotify:
    """Return an authenticated spotipy client (triggers login if needed).

    ``redirect_uri`` overrides the configured callback for this call (used by
    ``spotify auth`` to log in from a different host than the default).
    """
    cfg = cfg or Config.load()
    return spotipy.Spotify(
        auth_manager=_auth_manager(cfg, open_browser=open_browser, redirect_uri=redirect_uri)
    )


def authenticate(
    cfg: Config | None = None, open_browser: bool = True, redirect_uri: str | None = None
) -> dict:
    """Force the OAuth flow to complete and return the logged-in user's profile."""
    sp = client(cfg, open_browser=open_browser, redirect_uri=redirect_uri)
    try:
        return sp.me()
    except spotipy.SpotifyException as exc:  # pragma: no cover - network
        raise SpotifyError(f"Spotify authentication failed: {exc}") from exc


def auth_url(cfg: Config | None = None, redirect_uri: str | None = None) -> str:
    """The Spotify authorize URL to open in a browser (step 1 of headless login)."""
    cfg = cfg or Config.load()
    return _auth_manager(cfg, open_browser=False, redirect_uri=redirect_uri).get_authorize_url()


def complete_auth(
    redirect_response: str, cfg: Config | None = None, redirect_uri: str | None = None
) -> dict:
    """Exchange the redirected URL (or bare code) for a token (step 2).

    Non-interactive: takes the URL the browser landed on, pulls out the ``code``,
    swaps it for an access/refresh token (cached to disk), and returns the user
    profile. Lets a headless box complete login without a live stdin prompt.
    """
    cfg = cfg or Config.load()
    am = _auth_manager(cfg, open_browser=False, redirect_uri=redirect_uri)
    text = redirect_response.strip()
    if not text:
        raise SpotifyError(
            "Paste the full URL you were redirected to (containing `?code=...`), "
            "or just the code itself."
        )
    # For a full redirect URL this returns the code; for a bare code, the code.
    code = am.parse_response_code(text)
    try:
        am.get_access_token(code, as_dict=False, check_cache=False)
        return spotipy.Spotify(auth_manager=am).me()
    except spotipy.SpotifyException as exc:  # pragma: no cover - network
        raise SpotifyError(f"Spotify authentication failed: {exc}") from exc


# --- parsing helpers -------------------------------------------------------

def _names(artists: list | None) -> str:
    return ", ".join(a.get("name", "") for a in (artists or []) if a)


def _parse_item(kind: str, item: dict | None) -> SearchResult | None:
    """Build a SearchResult from a raw API item, tolerating nulls/missing fields."""
    if not item:  # Spotify can return null entries, esp. in playlist results
        return None
    ext = (item.get("external_urls") or {}).get("spotify", "")
    base = dict(
        kind=kind,
        name=item.get("name", ""),
        uri=item.get("uri", ""),
        url=ext,
        id=item.get("id", ""),
    )
    if not base["uri"] or not base["name"]:
        return None
    if kind == "track":
        detail = _names(item.get("artists"))
    elif kind == "album":
        detail = _names(item.get("artists"))
    elif kind == "playlist":
        detail = (item.get("owner") or {}).get("display_name", "")
    else:  # artist
        detail = ", ".join(item.get("genres", []) or [])
    return SearchResult(detail=detail, **base)


# --- public API ------------------------------------------------------------

def search(
    query: str,
    kinds: list[str] | None = None,
    limit: int = 5,
    market: str = "US",
    sp: spotipy.Spotify | None = None,
    cfg: Config | None = None,
) -> list[SearchResult]:
    """Search the catalog; returns results grouped by the requested kinds."""
    kinds = kinds or list(KINDS)
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise SpotifyError(f"Unknown search type(s): {', '.join(bad)}. Use: {', '.join(KINDS)}")
    sp = sp or client(cfg)
    try:
        raw = sp.search(q=query, type=",".join(kinds), limit=limit, market=market)
    except spotipy.SpotifyException as exc:  # pragma: no cover - network
        raise SpotifyError(f"Spotify search failed: {exc}") from exc

    out: list[SearchResult] = []
    for kind in kinds:
        bucket = (raw or {}).get(f"{kind}s") or {}
        for item in bucket.get("items", []) or []:
            res = _parse_item(kind, item)
            if res:
                out.append(res)
    return out


def _parse_target(target: str) -> tuple[str, str] | None:
    """Return (kind, id) if target is a spotify URI or open.spotify.com link."""
    m = _URI_RE.search(target) or _LINK_RE.search(target)
    return (m.group(1), m.group(2)) if m else None


def _artist_top_track_uris(sp: spotipy.Spotify, artist_id: str, market: str) -> list[str]:
    try:
        data = sp.artist_top_tracks(artist_id, country=market)
    except spotipy.SpotifyException as exc:  # pragma: no cover - network
        raise SpotifyError(f"Could not fetch artist top tracks: {exc}") from exc
    uris = [t.get("uri") for t in (data.get("tracks") or []) if t and t.get("uri")]
    if not uris:
        raise SpotifyError("That artist has no playable top tracks.")
    return uris


def resolve(
    target: str,
    market: str = "US",
    kind: str | None = None,
    sp: spotipy.Spotify | None = None,
    cfg: Config | None = None,
) -> PlayTarget:
    """Resolve ``target`` into one or more playable links.

    ``target`` may be a ``spotify:`` URI, an open.spotify.com link, or free text.
    Artists are expanded to their top tracks (ShareLinkPlugin can't queue an
    artist). For free text, the top matching item of ``kind`` (default track) is
    used.
    """
    sp = sp or client(cfg)

    parsed = _parse_target(target)
    if parsed:
        item_kind, item_id = parsed
        if item_kind == "artist":
            uris = _artist_top_track_uris(sp, item_id, market)
            try:
                name = sp.artist(item_id).get("name", "artist")
            except spotipy.SpotifyException:  # pragma: no cover - network
                name = "artist"
            return PlayTarget(label=f"{name} (top tracks)", kind="artist", links=tuple(uris))
        return PlayTarget(label=target, kind=item_kind, links=(f"spotify:{item_kind}:{item_id}",))

    # free-text query -> top hit of the requested kind
    want = kind or "track"
    results = search(target, kinds=[want], limit=1, market=market, sp=sp)
    if not results:
        raise SpotifyError(f"No Spotify {want} found for {target!r}.")
    top = results[0]
    if top.kind == "artist":
        uris = _artist_top_track_uris(sp, top.id, market)
        return PlayTarget(label=f"{top.name} (top tracks)", kind="artist", links=tuple(uris))
    label = f"{top.name} — {top.detail}" if top.detail else top.name
    return PlayTarget(label=label, kind=top.kind, links=(top.uri,))


def my_playlists(
    limit: int = 50, sp: spotipy.Spotify | None = None, cfg: Config | None = None
) -> list[SearchResult]:
    """The current user's playlists (requires OAuth login)."""
    sp = sp or client(cfg)
    try:
        data = sp.current_user_playlists(limit=limit)
    except spotipy.SpotifyException as exc:  # pragma: no cover - network
        raise SpotifyError(f"Could not list your playlists: {exc}") from exc
    return [r for r in (_parse_item("playlist", i) for i in (data.get("items") or [])) if r]


def my_saved_tracks(
    limit: int = 50, sp: spotipy.Spotify | None = None, cfg: Config | None = None
) -> list[SearchResult]:
    """The current user's liked/saved tracks (requires OAuth login)."""
    sp = sp or client(cfg)
    try:
        data = sp.current_user_saved_tracks(limit=limit)
    except spotipy.SpotifyException as exc:  # pragma: no cover - network
        raise SpotifyError(f"Could not list your liked songs: {exc}") from exc
    out: list[SearchResult] = []
    for entry in data.get("items") or []:
        res = _parse_item("track", (entry or {}).get("track"))
        if res:
            out.append(res)
    return out
