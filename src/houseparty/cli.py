"""houseparty CLI — stream NTS Radio to Sonos speakers."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import nts, sonos
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


if __name__ == "__main__":
    app()
