# AGENTS.md

Guidance for AI agents (and humans) working in the **houseparty** repo. Read
this before making changes.

## What this is

A `uv`-managed Python CLI that streams NTS Radio — the two live stations and the
infinite mixtapes — to Sonos speakers over the local network (via
[SoCo](https://github.com/SoCo/SoCo)). No cloud account, no music-service
registration; everything is local UPnP plus NTS's public API.

## Setup & everyday commands

This project uses **uv for everything** — do not call `pip`, `python -m venv`, or
a bare `python` directly.

```bash
uv sync                       # install deps into .venv from uv.lock
uv run houseparty --help      # run the CLI from the project
uv run pytest -q              # run the test suite
uv add <package>              # add a runtime dependency (updates pyproject + lock)
uv add --dev <package>        # add a dev dependency
uv tool install . --reinstall # refresh the globally-installed `houseparty` command
```

Target runtime is **Python 3.10+** (`requires-python = ">=3.10"`). Keep it
working on 3.10 — see the `tomllib` note below.

## Architecture — where things live

```
src/houseparty/
  cli.py      # Typer app: all commands, arg parsing, Rich output. The ONLY user-facing layer.
  nts.py      # NTS API client: catalog (24h cache), now-playing, resolve(), identify()
  spotify.py  # Spotify Web API (spotipy/OAuth): search(), resolve(), library, SearchResult
  sonos.py    # SoCo wrappers: discovery, grouped playback, volume, now_playing(), play_spotify()
  config.py   # ~/.config/houseparty/config.toml: speakers, volume, cached IPs, [spotify] creds
tests/        # offline, mocked (no network, no hardware)
skills/houseparty/SKILL.md   # agentskills-spec skill (npx skills add devontivona/houseparty)
```

Keep the layering clean: `cli.py` orchestrates; domain logic lives in
`nts.py` / `spotify.py` / `sonos.py`. Errors that should reach the user are
raised as `nts.NTSError` / `spotify.SpotifyError` / `sonos.SonosError` and
rendered by `cli._fail()` — don't print from the domain modules. Read/play
commands should support `--json` for agent consumption (see the `spotify`
subgroup).

## Project-specific gotchas (don't relearn these the hard way)

- **`force_radio=True` is mandatory** when playing. Modern Sonos firmware rejects
  bare `http(s)://` for live radio; SoCo rewrites the scheme to
  `x-rincon-mp3radio://` and attaches DIDL metadata. See `sonos.play()`.
- **Identify streams via `GetMediaInfo`, not `get_current_track_info()`.** The
  track info is blank for radio and exposes only the *post-redirect* edge URL.
  `GetMediaInfo` gives the original `CurrentURI` and the title we embedded.
  `now_playing()` + `nts.identify()` rely on this — don't regress it.
- **Never hardcode the mixtape lineup.** `mixtapeN` numbers are not sequential
  and NTS rotates them. Always read the catalog from `/api/v2/mixtapes`
  (`nts.fetch_mixtapes()`, cached 24h).
- **`tomllib` is 3.11+ only.** On 3.10 we fall back to `tomli`, which is a
  conditional dependency (`tomli ; python_version < "3.11"`). If you touch TOML
  imports, keep that fallback and test under 3.10.
- **Sonos room names often include a suffix** (e.g. "Kitchen Speaker") and are
  case-sensitive. Code and docs should resolve names via discovery, never guess.
- **Stopping a group means unjoin, not coordinator-stop.** On Sonos, stopping a
  group coordinator does NOT reliably stop its slaved members, and a slave can't
  be stopped directly (`SoCoSlaveException`). `sonos.stop()` therefore stops the
  coordinators AND unjoins every target — that's the only reliable way to
  guarantee silence. So `stop` ends the session and ungroups; `pause` is the
  non-destructive variant. Don't "optimize" stop back to coordinator-only.
- **Multi-speaker ops must degrade gracefully.** A wedged player returns UPnP 501
  on join/play/volume. `_form_group` skips members that fail to join, and
  `_apply_volume` DROPS a speaker whose volume can't be set (a player stuck loud
  is worse than silent). Both feed a `skipped` list the CLI surfaces via
  `_warn_skipped`. Never let one bad speaker crash an "everywhere" command, and
  never wrap a raw `SoCoException` traceback to the user — convert to `SonosError`.
- **Spotify is queue-based, not a stream.** `sonos.play_spotify()` uses
  `ShareLinkPlugin.add_share_link_to_queue()` (returns a **1-based** index), then
  `play_from_queue(idx - 1)` (**0-based**) — keep that conversion. Sonos doesn't
  auto-play the queue.
- **ShareLinkPlugin can't queue an artist** — `spotify.resolve()` expands an
  artist to its top-track URIs; `play_spotify` enqueues them all.
- **Spotify failures are usually "not linked."** SoCo can't link the service; a
  UPnP 800 on enqueue means the user must add Spotify in their Sonos app. Surface
  that, don't swallow it.
- **No Spotify playback/Connect scopes** — playback is local via SoCo. Only
  request the read scopes in `spotify.SCOPES`.

## Testing

- Tests are **offline and mocked** — `httpx`/SoCo are never hit for real. Add
  tests in the same style (`tests/test_nts.py`, `tests/test_sonos.py`).
- Always run `uv run pytest -q` before committing.
- For changes that affect live behavior, also smoke-test against the real API
  (`uv run houseparty list`, `uv run houseparty now`) — these are read-only.
- **Playing audio is an action the user hears in their home.** Do NOT run
  `houseparty play`/`stop`/`volume` against real speakers to "verify" unless the
  user has explicitly asked you to. Read-only commands (`list`, `now`,
  `speakers`) are always safe.

## Code style

- Match the surrounding code: type hints, `from __future__ import annotations`,
  small focused functions, module docstrings explaining the *why*.
- Keep dependencies minimal; prefer the stdlib. New runtime deps go through
  `uv add` (so the lockfile updates) and should be justified.

## Release / versioning workflow

We use semantic version tags `vMAJOR.MINOR.PATCH`. **The version lives in two
places and they must stay in sync:**

1. `pyproject.toml` → `[project] version`
2. `skills/houseparty/SKILL.md` → frontmatter `metadata.version`

To cut a release (example: `0.1.1`):

```bash
# 1. Bump BOTH version locations to the new number (e.g. 0.1.1).
#    pyproject.toml: version = "0.1.1"
#    SKILL.md frontmatter: version: "0.1.1"

# 2. Verify green.
uv run pytest -q

# 3. Commit the bump.
git add -A
git commit -m "Release v0.1.1"

# 4. Tag (annotated) and push branch + tag.
git tag -a v0.1.1 -m "houseparty v0.1.1 — <one-line summary>"
git push origin main
git push origin v0.1.1

# 5. Publish the GitHub release with notes.
gh release create v0.1.1 --title "v0.1.1" --notes "<highlights>"

# 6. Refresh the locally-installed command.
uv tool install . --reinstall
```

Versioning guidance: **patch** for fixes, **minor** for new commands/flags
(backward-compatible), **major** for breaking changes to the CLI surface. When a
release changes the CLI surface, update `skills/houseparty/SKILL.md` and
`README.md` in the same change — purely internal fixes don't require skill edits.
