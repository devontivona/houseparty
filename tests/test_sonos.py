"""Tests for the Sonos control wrappers (mocked SoCo, no network)."""

from unittest.mock import MagicMock

from houseparty import sonos


def _fake_speaker(name: str) -> MagicMock:
    sp = MagicMock(name=name)
    sp.player_name = name
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
