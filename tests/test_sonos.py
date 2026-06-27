"""Tests for the Sonos control wrappers (mocked SoCo, no network)."""

from unittest.mock import MagicMock

from houseparty import sonos


def _fake_speaker(name: str) -> MagicMock:
    sp = MagicMock(name=name)
    sp.player_name = name
    sp.group = None  # standalone by default; _form_group skips the drop scan
    return sp


def test_play_groups_onto_coordinator_and_forces_radio():
    coord = _fake_speaker("Kitchen")
    member = _fake_speaker("Office")

    sonos.play([coord, member], title="NTS 1", url="https://example/stream", volume=30)

    # members join the coordinator
    member.join.assert_called_once_with(coord)
    coord.join.assert_not_called()

    # volume set on every speaker
    assert coord.volume == 30
    assert member.volume == 30

    # playback issued once, on the coordinator, with force_radio
    coord.play_uri.assert_called_once_with(
        "https://example/stream", title="NTS 1", force_radio=True
    )
    member.play_uri.assert_not_called()


def test_play_single_speaker_no_grouping():
    sp = _fake_speaker("Kitchen")
    sonos.play([sp], title="Poolside", url="https://example/mixtape4")
    sp.join.assert_not_called()
    sp.play_uri.assert_called_once_with(
        "https://example/mixtape4", title="Poolside", force_radio=True
    )


def test_clamp_volume():
    assert sonos._clamp_volume(150) == 100
    assert sonos._clamp_volume(-5) == 0
    assert sonos._clamp_volume(42) == 42


def _now_coordinator(current_uri, metadata, track):
    c = MagicMock()
    c.group = None
    c.avTransport.GetMediaInfo.return_value = {
        "CurrentURI": current_uri,
        "CurrentURIMetaData": metadata,
    }
    c.get_current_transport_info.return_value = {"current_transport_state": "PLAYING"}
    c.get_current_track_info.return_value = track
    return c


def test_now_playing_includes_spotify_track_from_queue():
    c = _now_coordinator(
        "x-rincon-queue:RINCON_ABC#0",
        "",
        {"title": "Pillars", "artist": "Jack Garratt", "album": "The Tension Between"},
    )
    info = sonos.now_playing(c)
    assert info["transport_state"] == "PLAYING"
    assert info["source_uri"].startswith("x-rincon-queue")
    assert info["track_artist"] == "Jack Garratt"
    assert info["track_title"] == "Pillars"
    assert info["track_album"] == "The Tension Between"


def test_form_group_isolates_targets_and_drops_extras():
    # one group of three; only two are targets, so the third is dropped
    coord = MagicMock(); coord.uid = "C"
    m2 = MagicMock(); m2.uid = "M2"
    extra = MagicMock(); extra.uid = "E"
    group = MagicMock(); group.members = [coord, m2, extra]
    coord.group = m2.group = extra.group = group

    result = sonos._form_group([coord, m2])

    extra.unjoin.assert_called_once()       # non-target dropped (stops)
    coord.unjoin.assert_called_once()       # coordinator detached from old group
    m2.join.assert_called_once_with(coord)  # target regrouped onto coordinator
    assert result is coord


def test_form_group_single_target_leaves_its_group_alone():
    # play on just the bathroom -> kitchen + move (its groupmates) are dropped
    bath = MagicMock(); bath.uid = "B"
    kitchen = MagicMock(); kitchen.uid = "K"
    move = MagicMock(); move.uid = "MV"
    group = MagicMock(); group.members = [kitchen, move, bath]
    bath.group = group

    sonos._form_group([bath])

    kitchen.unjoin.assert_called_once()
    move.unjoin.assert_called_once()


def test_skip_next_issues_one_next_per_group():
    coord = MagicMock()
    coord.uid = "A"
    m1, m2 = MagicMock(), MagicMock()
    m1.group.coordinator = coord
    m2.group.coordinator = coord  # same group as m1

    sonos.skip_next([m1, m2])

    coord.next.assert_called_once()  # de-duped to the shared coordinator


def test_skip_previous_separate_groups():
    c1, c2 = MagicMock(), MagicMock()
    c1.uid, c2.uid = "A", "B"
    s1, s2 = MagicMock(), MagicMock()
    s1.group.coordinator = c1
    s2.group.coordinator = c2

    sonos.skip_previous([s1, s2])

    c1.previous.assert_called_once()
    c2.previous.assert_called_once()


def test_now_playing_parses_embedded_radio_title():
    c = _now_coordinator(
        "x-rincon-mp3radio://stream-mixtape-geo.ntslive.net/mixtape36",
        "<DIDL-Lite><item><dc:title>Otaku</dc:title></item></DIDL-Lite>",
        {"title": "", "artist": "", "album": ""},
    )
    info = sonos.now_playing(c)
    assert info["source_title"] == "Otaku"
