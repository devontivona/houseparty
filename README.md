# houseparty

Stream [NTS Radio](https://www.nts.live) — both live stations **and** the
infinite mixtapes — and **Spotify** to Sonos speakers from the command line.

It talks to Sonos locally over UPnP (via [SoCo](https://github.com/SoCo/SoCo)),
so there's no cloud account needed for control. NTS content comes straight from
NTS's public API (the mixtape catalog is fetched live and cached for a day, so it
stays current). Spotify search uses the Spotify Web API; playback is enqueued on
Sonos via SoCo's ShareLinkPlugin.

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
houseparty next -s "Kitchen Speaker"         # skip track (Spotify queue playback)
houseparty volume 25 -s "Kitchen Speaker"
houseparty now                               # what's on air on NTS right now
houseparty now -s "Kitchen Speaker"          # ...plus what the speaker is playing
houseparty pause -s "Kitchen Speaker"        # pause (keeps the group, resumable)
houseparty resume -s "Kitchen Speaker"
houseparty stop -s "Kitchen Speaker"         # stop + ungroup (reliably silences)
```

`TARGET` is `1` or `2` for the live stations, or a mixtape alias/name
(case- and hyphen-insensitive, with fuzzy matching — `"slow focus"` finds
`slow-focus`). Run `houseparty list` to see the options.

## Spotify

houseparty can search Spotify (including your own library) and play results on
Sonos.

**One-time setup:**

1. You need **Spotify Premium**, and Spotify must be **linked in your Sonos app**
   (Settings → Services). houseparty can't link it for you.
2. Create an app at [developer.spotify.com](https://developer.spotify.com/dashboard)
   → copy the client ID + secret, and add a **loopback** redirect URI like
   `http://127.0.0.1:8080/callback`. Spotify only permits plain `http` for the
   loopback literals `127.0.0.1` / `[::1]` (not `localhost`, not a LAN
   hostname/IP). Register the exact host **and** port.
3. Save credentials and log in:

   ```bash
   houseparty spotify set-client <CLIENT_ID> <CLIENT_SECRET> \
     --redirect-uri http://127.0.0.1:8080/callback   # match your registered URI

   houseparty spotify auth                            # step 1: prints an authorize URL
   # open the URL, approve, copy the callback URL you land on, then:
   houseparty spotify auth --response "http://127.0.0.1:8080/callback?code=..."  # step 2
   ```

   Authentication is two non-interactive steps, so it works on a **headless box
   with the browser on another machine**: the `http://127.0.0.1:PORT/callback`
   URL never has to load (a "can't connect" page is expected) — only the `code`
   in it matters. `set-client --redirect-uri` sets the default callback;
   `spotify auth --redirect-uri URL` overrides it for one login.

**Usage:**

```bash
houseparty spotify search "radiohead" --type artist,track   # search the catalog
houseparty spotify play "karma police" -s "Kitchen Speaker" # play the top match
houseparty spotify play spotify:album:6dVIqQ8qmQ5GBnJ9shOYGE -s "Living Room"
houseparty spotify play "radiohead" --type artist -s Office # an artist's top tracks
houseparty spotify playlists                                # your playlists
houseparty spotify liked                                    # your saved songs
houseparty spotify search "lo-fi" --json                    # structured output
```

`TARGET` for `spotify play` is a free-text query (plays the top match), a
`spotify:` URI, or an open.spotify.com link. Tracks/albums/playlists play
directly; an **artist** plays their top tracks. `--add` appends to the queue and
`--next` plays after the current track. Every command supports `--json`.

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
- NTS playback uses SoCo's `play_uri(..., force_radio=True)`, which Sonos
  firmware requires for live radio (it rewrites the scheme to
  `x-rincon-mp3radio://` and attaches metadata so the station name shows).
- **Spotify** search/library uses the Spotify Web API (via `spotipy`, OAuth
  Authorization Code). Playback is enqueued locally with SoCo's
  `ShareLinkPlugin` — no Spotify Connect, and no playback scopes requested.
  Artists are expanded to their top tracks (the plugin can't queue an artist).

## Development

```bash
uv run pytest        # offline unit tests (mocked NTS + Sonos)
```

See [AGENTS.md](AGENTS.md) for the architecture, project-specific gotchas, and
the release/versioning workflow.
