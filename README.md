# houseparty

Stream [NTS Radio](https://www.nts.live) — both live stations **and** the
infinite mixtapes — to Sonos speakers from the command line.

It talks to Sonos locally over UPnP (via [SoCo](https://github.com/SoCo/SoCo)),
so there's no cloud account, OAuth, or music-service registration. NTS content
comes straight from NTS's public API; the mixtape catalog is fetched live (and
cached for a day) so it stays current as the lineup changes.

## Install

Requires [uv](https://docs.astral.sh/uv/).

```bash
# run from a checkout during development
uv run houseparty --help

# or install the `houseparty` command globally
uv tool install ~/projects/houseparty
```

## Usage

```bash
houseparty list                              # live stations + current mixtapes
houseparty speakers --cache                  # discover speakers, cache their IPs
houseparty play 1 -s "Kitchen Speaker"       # NTS 1 in the kitchen
houseparty play poolside -s "Living Room"    # an infinite mixtape
houseparty play "slow focus" -s Office -s "Rec Room"   # grouped, fuzzy name
houseparty volume 25 -s "Kitchen Speaker"
houseparty now                               # what's on air on NTS right now
houseparty now -s "Kitchen Speaker"          # ...plus what the speaker is playing
houseparty stop -s "Kitchen Speaker"
```

`TARGET` is `1` or `2` for the live stations, or a mixtape alias/name
(case- and hyphen-insensitive, with fuzzy matching — `"slow focus"` finds
`slow-focus`). Run `houseparty list` to see the options.

### Defaults

Set default speakers (and an optional default volume) so you can omit `-s`:

```bash
houseparty config set-default "Kitchen Speaker" "Living Room"
houseparty config set-volume 25
houseparty config show
```

## Config

Stored at `~/.config/houseparty/config.toml`:

```toml
default_speakers = ["Kitchen Speaker"]
default_volume = 25
[speaker_ips]            # cached name -> IP, used if multicast discovery fails
"Kitchen Speaker" = "192.168.1.161"
```

The cached IPs (`houseparty speakers --cache`) are a fallback for networks where
Sonos's multicast discovery is blocked (common on segmented/VLAN'd Wi-Fi).

## How it works

- **Live stations** are stable MP3 Icecast URLs (`stream-relay-geo.ntslive.net`).
- **Mixtapes** come from `GET https://www.nts.live/api/v2/mixtapes`
  (`audio_stream_endpoint` per mixtape).
- **Now playing** comes from `GET https://www.nts.live/api/v2/live`.
- Playback uses SoCo's `play_uri(..., force_radio=True)`, which Sonos firmware
  requires for live radio (it rewrites the scheme to `x-rincon-mp3radio://` and
  attaches metadata so the station name shows in the app).

## Development

```bash
uv run pytest        # offline unit tests (mocked NTS + Sonos)
```

See [AGENTS.md](AGENTS.md) for the architecture, project-specific gotchas, and
the release/versioning workflow.
