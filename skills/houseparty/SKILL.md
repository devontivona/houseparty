---
name: houseparty
description: Streams NTS Radio live stations and infinite mixtapes to Sonos speakers using the houseparty CLI. Use when the user wants to play, switch, stop, or control NTS Radio on their Sonos, choose which speaker or room, group multiple speakers, set volume, or see what is currently on air.
license: MIT
metadata:
  homepage: https://github.com/devontivona/houseparty
  version: "0.1.0"
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
