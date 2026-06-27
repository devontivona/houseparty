---
name: houseparty
description: Streams NTS Radio (live stations + infinite mixtapes) and Spotify (search/play tracks, albums, playlists, artists, and the user's library) to Sonos speakers using the houseparty CLI. Use when the user wants to play, switch, stop, or control NTS Radio or Spotify on their Sonos, search for music, choose which speaker or room, group speakers, set volume, or see what is currently on air.
license: MIT
metadata:
  homepage: https://github.com/devontivona/houseparty
  version: "0.2.5"
compatibility: Requires Python 3.10+, the uv tool, and a Sonos system reachable on the local network.
allowed-tools: Bash(houseparty:*) Bash(uv:*)
---

# houseparty: NTS Radio on Sonos

`houseparty` is a command-line tool that streams NTS Radio — both live stations
(NTS 1 / NTS 2) and the always-on "infinite mixtapes" — to Sonos speakers on the
local network. It controls Sonos directly over the LAN (no cloud account), and
pulls the NTS catalog live so the mixtape lineup is always current.

## Install

If the `houseparty` command is not already on PATH, install it once with uv:

```
uv tool install git+https://github.com/devontivona/houseparty
```

Check it is available with `houseparty --help`.

## Core workflow

1. **Find the exact speaker names.** Sonos room names are case-sensitive and
   often include a suffix like "Speaker" (e.g. "Kitchen Speaker"). List them:

   ```
   houseparty speakers
   ```

   Add `--cache` to save the discovered name-to-IP map to config, which makes
   later lookups reliable on networks where multicast discovery is flaky:

   ```
   houseparty speakers --cache
   ```

2. **Find what to play.** List the live stations and current mixtapes:

   ```
   houseparty list
   ```

3. **Play it** on one or more speakers with repeated `-s` flags:

   ```
   houseparty play poolside -s "Kitchen Speaker"
   houseparty play 1 -s "Living Room" -s "Office"
   ```

4. **Confirm** it is playing:

   ```
   houseparty now -s "Kitchen Speaker"
   ```

## Command reference

- `houseparty list` — show live stations and the current infinite mixtapes.
  Add `--refresh` to force-refresh the cached catalog.
- `houseparty play TARGET -s NAME [-s NAME ...] [--volume N]` — play a station
  or mixtape. TARGET is `1` or `2` for the live stations, or a mixtape alias or
  title. Matching is case- and hyphen-insensitive with a fuzzy fallback, so
  `"slow focus"` resolves to `slow-focus`. Passing multiple `-s` flags groups
  those speakers and plays in sync.
- `houseparty stop -s NAME` — stop playback (stopping any speaker in a group
  stops the whole group).
- `houseparty volume N -s NAME` — set volume (0-100) on the given speakers.
- `houseparty now [-s NAME]` — show what is on air on NTS now; with `-s`, also
  show what each speaker is currently playing.
- `houseparty speakers [--cache]` — discover Sonos speakers; `--cache` saves
  their IPs to config.
- `houseparty config show` — print current config.
- `houseparty config set-default NAME [NAME ...]` — set default speakers used
  when `-s` is omitted.
- `houseparty config set-volume N` — set a default volume applied on play.

## Spotify

houseparty can also search Spotify and play results on Sonos. The search, play,
and library commands take `--json` for structured, agent-friendly output.

One-time setup (required before any Spotify command works):

1. The user needs **Spotify Premium** and must have **linked Spotify in their
   Sonos app** (Settings > Services). houseparty cannot link it.
2. Create a Spotify developer app at developer.spotify.com → get a client ID and
   secret, and register a **loopback** redirect URI like
   `http://127.0.0.1:8080/callback`. Spotify only allows plain `http` for the
   loopback literals `127.0.0.1` / `[::1]` — not `localhost`, and not a LAN
   hostname or IP (those would need `https`). Register the exact host **and**
   port.
3. Store credentials: `houseparty spotify set-client <CLIENT_ID> <CLIENT_SECRET>
   [--redirect-uri URL]` (or set `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`).
4. Authenticate (two-step, non-interactive):
   - `houseparty spotify auth` prints an authorize URL. Open it in a browser and
     approve.
   - The browser lands on `http://127.0.0.1:PORT/callback?code=...` (a "can't
     connect" page is expected on a headless box — nothing is served there).
   - `houseparty spotify auth --response "<that whole URL>"` completes login.

   This works when the browser is on a different machine than the headless box:
   the callback never has to load; only the `code` in the URL matters. Use
   `--redirect-uri URL` on either step to override the configured callback.

Spotify commands:

- `houseparty spotify auth [--response URL] [--redirect-uri URL]` — log in
  (two-step, non-interactive; see setup above). Run once.
- `houseparty spotify search QUERY [--type artist,album,playlist,track] [--limit N] [--json]`
  — search the catalog. Returns each result's `kind`, `name`, `detail`, `uri`,
  and `url`.
- `houseparty spotify play TARGET -s NAME [--type T] [--add|--next] [--volume N] [--json]`
  — TARGET is a free-text query (plays the top match), a `spotify:` URI, or an
  open.spotify.com link. Tracks/albums/playlists play directly; an **artist**
  plays their top tracks. `--add` appends to the queue, `--next` plays after the
  current track.
- `houseparty spotify playlists [--json]` — the user's own playlists.
- `houseparty spotify liked [--json]` — the user's liked/saved songs.
- `houseparty spotify set-client ID SECRET [--market US] [--redirect-uri URL]` —
  store credentials/settings.

Spotify tips for agents:

- Prefer `spotify search QUERY --json` to find the exact item, then
  `spotify play <uri>` with the chosen `uri` for precise playback, rather than
  relying on the free-text top match.
- If a play command errors that Spotify "isn't linked," the user must add
  Spotify in their Sonos app first — this cannot be fixed from the CLI.
- Spotify playback uses the Sonos queue (not a radio stream), so
  `houseparty now` shows the current track title.

## Tips for agents

- Always run `houseparty speakers` first to get the user's exact room names
  before constructing a `play` command; do not guess names.
- Quote speaker names that contain spaces, e.g. `-s "Living Room"`.
- To switch stations, just run another `play` on the same speaker(s); it
  replaces what is playing.
- If the user sets defaults via `config set-default`, the `-s` flag can be
  omitted and the tool uses the configured speakers.
- Playing audio is an action the user hears in their home — confirm the target
  speaker(s) before starting playback unless the user has clearly asked you to
  just play something.
