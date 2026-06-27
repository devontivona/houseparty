"""Tests for the NTS catalog parsing and target resolution (offline)."""

import pytest

from houseparty import nts
from houseparty.nts import Mixtape

SAMPLE = {
    "results": [
        {
            "mixtape_alias": "poolside",
            "title": "Poolside",
            "subtitle": "Sun-soaked and degraded",
            "audio_stream_endpoint": "https://stream-mixtape-geo.ntslive.net/mixtape4",
            "audio_stream_endpoint_hls_aac": "https://streams.radiomast.io/e7bc1d1a-da3a-492f-8ecd-d5b4d503799f/hls.m3u8",
            "audio_stream_endpoint_hls_mp3": "https://streams.radiomast.io/052d2e3c-389c-44cf-a91a-8f5e1854f4c6/hls.m3u8",
        },
        {
            "mixtape_alias": "slow-focus",
            "title": "Slow Focus",
            "subtitle": "Meditative and mid-tempo",
            "audio_stream_endpoint": "https://stream-mixtape-geo.ntslive.net/mixtape",
        },
        {
            # malformed entry (no stream url) should be skipped
            "mixtape_alias": "broken",
            "title": "Broken",
        },
    ]
}


def test_parse_mixtapes_skips_malformed():
    mixtapes = nts._parse_mixtapes(SAMPLE)
    assert [m.alias for m in mixtapes] == ["poolside", "slow-focus"]
    poolside = mixtapes[0]
    assert poolside.title == "Poolside"
    assert poolside.stream_url.endswith("/mixtape4")


def _catalog():
    return nts._parse_mixtapes(SAMPLE)


def test_resolve_live_stations():
    assert nts.resolve("1")[1] == nts.LIVE_STATIONS["1"][1]
    assert nts.resolve("2")[0] == "NTS 2"


def test_resolve_exact_alias():
    title, url = nts.resolve("poolside", mixtapes=_catalog())
    assert title == "Poolside"
    assert url.endswith("/mixtape4")


def test_resolve_fuzzy_and_spacing():
    # space instead of hyphen, different case
    title, _ = nts.resolve("slow focus", mixtapes=_catalog())
    assert title == "Slow Focus"
    # fuzzy typo
    title, _ = nts.resolve("poolsied", mixtapes=_catalog())
    assert title == "Poolside"


def test_resolve_unknown_raises_with_options():
    with pytest.raises(nts.NTSError) as exc:
        nts.resolve("definitely-not-a-channel", mixtapes=_catalog())
    msg = str(exc.value)
    assert "poolside" in msg and "slow-focus" in msg


def test_parse_mixtapes_extracts_uuids():
    poolside = nts._parse_mixtapes(SAMPLE)[0]
    assert "052d2e3c-389c-44cf-a91a-8f5e1854f4c6" in poolside.uuids
    assert "e7bc1d1a-da3a-492f-8ecd-d5b4d503799f" in poolside.uuids


def test_identify_live_station():
    # un-redirected CurrentURI as Sonos reports it via GetMediaInfo
    assert nts.identify("x-rincon-mp3radio://stream-relay-geo.ntslive.net/stream") == "NTS 1"
    assert nts.identify("x-rincon-mp3radio://stream-relay-geo.ntslive.net/stream2") == "NTS 2"


def test_identify_mixtape_by_path():
    # the un-redirected mixtape URI (host/path)
    uri = "x-rincon-mp3radio://stream-mixtape-geo.ntslive.net/mixtape4"
    assert nts.identify(uri, mixtapes=_catalog()) == "Poolside"


def test_identify_mixtape_by_redirected_uuid():
    # the redirected radiomast edge URL, identified via its UUID
    uri = "x-rincon-mp3radio://https://audio-edge-4ev3b.lax.g.radiomast.io/052d2e3c-389c-44cf-a91a-8f5e1854f4c6"
    assert nts.identify(uri, mixtapes=_catalog()) == "Poolside"


def test_identify_unknown_returns_none():
    assert nts.identify("", mixtapes=_catalog()) is None
    assert nts.identify("x-rincon-mp3radio://example.com/whatever", mixtapes=_catalog()) is None
