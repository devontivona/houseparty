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
            "audio_stream_endpoint_hls_aac": "https://streams.radiomast.io/x/hls.m3u8",
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
