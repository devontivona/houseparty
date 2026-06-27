"""houseparty CLI — stream NTS Radio and Spotify to Sonos speakers."""

from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import nts, sonos, spotify
from .config import Config

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Stream NTS Radio (live stations + infinite mixtapes) to Sonos speakers.",
)
config_app = typer.Typer(no_args_is_help=True, help="View and edit houseparty config.")
app.add_typer(config_app, name="config")

console = Console()
err = Console(stderr=True)

SpeakerOpt = typer.Option(
    None, "--speaker", "-s", help="Speaker/room name (repeatable). Defaults to config."
)


def _fail(msg: str) -> None:
    err.print(f"[bold red]error:[/] {msg}")
    raise typer.Exit(code=1)


def _resolve_speaker_names(speaker: Optional[list[str]], cfg: Config) -> list[str]:
    names = list(speaker) if speaker else list(cfg.default_speakers)
    if not names:
        _fail("No speaker given. Pass --speaker/-s or set defaults via "
              "`houseparty config set-default <name>...`.")
    return names


@app.command("list")
def list_content(
    refresh: bool = typer.Option(False, "--refresh", help="Force-refresh the mixtape catalog."),
) -> None:
    """List the live stations and current infinite mixtapes."""
    try:
        mixtapes = nts.fetch_mixtapes(force_refresh=refresh)
    except nts.NTSError as exc:
        _fail(str(exc))

    stations = Table(title="Live Stations", show_edge=False, pad_edge=False)
    stations.add_column("key", style="bold cyan")
    stations.add_column("name")
    for key, (name, _url) in nts.LIVE_STATIONS.items():
        stations.add_row(key, name)
    console.print(stations)

    table = Table(title="Infinite Mixtapes", show_edge=False, pad_edge=False)
    table.add_column("alias", style="bold cyan")
    table.add_column("title")
    table.add_column("subtitle", style="dim")
    for mt in sorted(mixtapes, key=lambda m: m.alias):
        table.add_row(mt.alias, mt.title, mt.subtitle)
    console.print(table)


@app.command()
def play(
    target: str = typer.Argument(..., help="Station '1'/'2' or a mixtape alias/name."),
    speaker: Optional[list[str]] = SpeakerOpt,
    volume: Optional[int] = typer.Option(None, "--volume", "-v", help="Set volume (0-100)."),
) -> None:
    """Play a station or mixtape on one or more speakers."""
    cfg = Config.load()
    names = _resolve_speaker_names(speaker, cfg)
    vol = volume if volume is not None else cfg.default_volume

    try:
        title, url = nts.resolve(target)
    except nts.NTSError as exc:
        _fail(str(exc))

    try:
        speakers = sonos.resolve_speakers(names, cfg.speaker_ips)
        sonos.play(speakers, title=title, url=url, volume=vol)
    except sonos.SonosError as exc:
        _fail(str(exc))

    where = ", ".join(names)
    vol_note = f" at volume {vol}" if vol is not None else ""
    console.print(f"[green]▶[/] Playing [bold]{title}[/] on [bold]{where}[/]{vol_note}.")


@app.command()
def stop(speaker: Optional[list[str]] = SpeakerOpt) -> None:
    """Stop playback on one or more speakers."""
    cfg = Config.load()
    names = _resolve_speaker_names(speaker, cfg)
    try:
        speakers = sonos.resolve_speakers(names, cfg.speaker_ips)
        sonos.stop(speakers)
    except sonos.SonosError as exc:
        _fail(str(exc))
    console.print(f"[yellow]■[/] Stopped [bold]{', '.join(names)}[/].")


@app.command()
def volume(
    level: int = typer.Argument(..., help="Volume level 0-100."),
    speaker: Optional[list[str]] = SpeakerOpt,
) -> None:
    """Set the volume on one or more speakers."""
    cfg = Config.load()
    names = _resolve_speaker_names(speaker, cfg)
    try:
        speakers = sonos.resolve_speakers(names, cfg.speaker_ips)
        sonos.set_volume(speakers, level)
    except sonos.SonosError as exc:
        _fail(str(exc))
    console.print(f"[green]♪[/] Set volume {level} on [bold]{', '.join(names)}[/].")


@app.command()
def now(speaker: Optional[list[str]] = SpeakerOpt) -> None:
    """Show what's on air on NTS (and, if given, what a speaker is playing)."""
    try:
        broadcasts = nts.fetch_now()
    except nts.NTSError as exc:
        _fail(str(exc))

    table = Table(title="NTS — On Air Now", show_edge=False, pad_edge=False)
    table.add_column("ch", style="bold cyan")
    table.add_column("now playing")
    table.add_column("location", style="dim")
    table.add_column("genres", style="dim")
    for b in broadcasts:
        title = b.title or b.show_name or "—"
        table.add_row(b.channel, title, b.location, ", ".join(b.genres))
    console.print(table)

    if speaker:
        cfg = Config.load()
        try:
            speakers = sonos.resolve_speakers(list(speaker), cfg.speaker_ips)
            mixtapes = nts.fetch_mixtapes()
        except (sonos.SonosError, nts.NTSError) as exc:
            _fail(str(exc))
        for sp, name in zip(speakers, speaker):
            info = sonos.now_playing(sp)
            state = info.get("transport_state", "")
            # Identify against the live catalog first (ground truth, survives NTS
            # relabeling a slug), then fall back to the title Sonos has embedded.
            label = (
                nts.identify(info.get("source_uri", ""), mixtapes)
                or info.get("source_title")
                or info.get("source_uri")
                or "—"
            )
            console.print(f"[bold]{name}[/] [{state}]: {label}")


@app.command()
def speakers(
    cache: bool = typer.Option(False, "--cache", help="Save discovered name->IP to config."),
) -> None:
    """Discover and list Sonos speakers on the network."""
    found = sonos.list_speakers()
    if not found:
        _fail("No Sonos speakers found. Check the network, or cache IPs in config.")

    table = Table(title="Sonos Speakers", show_edge=False, pad_edge=False)
    table.add_column("name", style="bold cyan")
    table.add_column("ip")
    for sp in found:
        table.add_row(sp.name, sp.ip)
    console.print(table)

    if cache:
        cfg = Config.load()
        cfg.speaker_ips.update({sp.name: sp.ip for sp in found})
        path = cfg.save()
        console.print(f"[green]✓[/] Cached {len(found)} speaker IP(s) to {path}.")


@config_app.command("show")
def config_show() -> None:
    """Print the current config."""
    cfg = Config.load()
    console.print(f"default_speakers = {cfg.default_speakers}")
    console.print(f"default_volume   = {cfg.default_volume}")
    console.print(f"speaker_ips      = {cfg.speaker_ips}")
    sp = cfg.spotify
    have_creds = bool(sp.resolved_client_id() and sp.resolved_client_secret())
    console.print(f"spotify.client   = {'configured' if have_creds else 'not set'}")
    console.print(f"spotify.market   = {sp.market}")
    console.print(f"spotify.redirect = {sp.redirect_uri}")


@config_app.command("set-default")
def config_set_default(
    names: list[str] = typer.Argument(..., help="Speaker name(s) to use by default."),
) -> None:
    """Set the default speaker(s) used when --speaker is omitted."""
    cfg = Config.load()
    cfg.default_speakers = list(names)
    path = cfg.save()
    console.print(f"[green]✓[/] default_speakers = {names} ({path})")


@config_app.command("set-volume")
def config_set_volume(
    level: int = typer.Argument(..., help="Default volume 0-100 (applied on play)."),
) -> None:
    """Set a default volume applied on play."""
    cfg = Config.load()
    cfg.default_volume = max(0, min(100, level))
    path = cfg.save()
    console.print(f"[green]✓[/] default_volume = {cfg.default_volume} ({path})")


spotify_app = typer.Typer(no_args_is_help=True, help="Search and play Spotify on Sonos.")
app.add_typer(spotify_app, name="spotify")


def _emit_json(data) -> None:
    """Print plain JSON to stdout (for agent/script consumption)."""
    typer.echo(json.dumps(data, indent=2))


def _results_table(title: str, results: list[spotify.SearchResult]) -> Table:
    table = Table(title=title, show_edge=False, pad_edge=False)
    table.add_column("#", style="dim")
    table.add_column("kind", style="cyan")
    table.add_column("name")
    table.add_column("detail", style="dim")
    table.add_column("uri", style="dim")
    for i, r in enumerate(results, 1):
        table.add_row(str(i), r.kind, r.name, r.detail, r.uri)
    return table


@spotify_app.command("auth")
def spotify_auth(
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Print the login URL to open manually (headless/SSH)."
    ),
) -> None:
    """Authenticate with Spotify (one-time browser login)."""
    cfg = Config.load()
    try:
        me = spotify.authenticate(cfg, open_browser=not no_browser)
    except spotify.SpotifyError as exc:
        _fail(str(exc))
    who = me.get("display_name") or me.get("id") or "unknown"
    console.print(f"[green]✓[/] Authenticated with Spotify as [bold]{who}[/].")


@spotify_app.command("search")
def spotify_search(
    query: str = typer.Argument(..., help="Search text."),
    type_: Optional[str] = typer.Option(
        None, "--type", "-t", help="Comma-separated: artist,album,playlist,track."
    ),
    limit: int = typer.Option(5, "--limit", "-n", help="Results per type."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON for scripting."),
) -> None:
    """Search Spotify for artists, albums, playlists, and tracks."""
    cfg = Config.load()
    kinds = [k.strip() for k in type_.split(",")] if type_ else None
    try:
        results = spotify.search(query, kinds=kinds, limit=limit, market=cfg.spotify.market)
    except spotify.SpotifyError as exc:
        _fail(str(exc))
    if json_out:
        _emit_json([r.as_dict() for r in results])
        return
    if not results:
        console.print("No results.")
        return
    console.print(_results_table(f"Spotify: {query}", results))


@spotify_app.command("play")
def spotify_play(
    target: str = typer.Argument(..., help="Query, spotify: URI, or open.spotify.com link."),
    speaker: Optional[list[str]] = SpeakerOpt,
    type_: Optional[str] = typer.Option(
        None, "--type", "-t", help="For a text query: artist|album|playlist|track (default track)."
    ),
    add: bool = typer.Option(False, "--add", help="Append to the queue instead of playing now."),
    next_: bool = typer.Option(False, "--next", help="Insert after the current track."),
    volume: Optional[int] = typer.Option(None, "--volume", "-v", help="Set volume (0-100)."),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON for scripting."),
) -> None:
    """Play a Spotify track/album/playlist/artist on one or more speakers."""
    cfg = Config.load()
    names = _resolve_speaker_names(speaker, cfg)
    mode = "add" if add else "next" if next_ else "now"
    vol = volume if volume is not None else cfg.default_volume
    try:
        target_info = spotify.resolve(target, market=cfg.spotify.market, kind=type_)
    except spotify.SpotifyError as exc:
        _fail(str(exc))
    try:
        speakers = sonos.resolve_speakers(names, cfg.speaker_ips)
        sonos.play_spotify(
            speakers, list(target_info.links), label=target_info.label, mode=mode, volume=vol
        )
    except sonos.SonosError as exc:
        _fail(str(exc))
    if json_out:
        _emit_json({"played": target_info.as_dict(), "speakers": names, "mode": mode})
        return
    verb = {"now": "Playing", "add": "Queued", "next": "Up next"}[mode]
    console.print(f"[green]▶[/] {verb} [bold]{target_info.label}[/] on [bold]{', '.join(names)}[/].")


@spotify_app.command("playlists")
def spotify_playlists(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON for scripting."),
) -> None:
    """List your Spotify playlists (requires `spotify auth`)."""
    try:
        results = spotify.my_playlists()
    except spotify.SpotifyError as exc:
        _fail(str(exc))
    if json_out:
        _emit_json([r.as_dict() for r in results])
        return
    console.print(_results_table("Your Playlists", results))


@spotify_app.command("liked")
def spotify_liked(
    json_out: bool = typer.Option(False, "--json", help="Emit JSON for scripting."),
) -> None:
    """List your liked/saved songs (requires `spotify auth`)."""
    try:
        results = spotify.my_saved_tracks()
    except spotify.SpotifyError as exc:
        _fail(str(exc))
    if json_out:
        _emit_json([r.as_dict() for r in results])
        return
    console.print(_results_table("Your Liked Songs", results))


@spotify_app.command("set-client")
def spotify_set_client(
    client_id: str = typer.Argument(..., help="Spotify app client ID."),
    client_secret: str = typer.Argument(..., help="Spotify app client secret."),
    market: Optional[str] = typer.Option(None, "--market", help="Default market, e.g. US, GB."),
    redirect_uri: Optional[str] = typer.Option(None, "--redirect-uri", help="OAuth redirect URI."),
) -> None:
    """Store Spotify app credentials in config."""
    cfg = Config.load()
    cfg.spotify.client_id = client_id
    cfg.spotify.client_secret = client_secret
    if market:
        cfg.spotify.market = market
    if redirect_uri:
        cfg.spotify.redirect_uri = redirect_uri
    path = cfg.save()
    console.print(f"[green]✓[/] Saved Spotify credentials ({path}).")
    console.print(
        f"Register this redirect URI in your Spotify app dashboard: "
        f"[bold]{cfg.spotify.redirect_uri}[/]"
    )


if __name__ == "__main__":
    app()
