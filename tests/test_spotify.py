"""Tests for Spotify search/resolve and Sonos Spotify playback (mocked)."""

import itertools
from unittest.mock import MagicMock, patch

import pytest
from soco.exceptions import SoCoException

from houseparty import sonos, spotify


# --- fake spotipy client ---------------------------------------------------

def _search_response():
    """A /v1/search-shaped response covering all four types, incl. a null."""
    return {
        "tracks": {"items": [
            {"id": "t1", "name": "Karma Police", "uri": "spotify:track:t1",
             "external_urls": {"spotify": "https://open.spotify.com/track/t1"},
             "artists": [{"name": "Radiohead"}], "album": {"name": "OK Computer"}},
        ]},
        "albums": {"items": [
            {"id": "al1", "name": "OK Computer", "uri": "spotify:album:al1",
             "external_urls": {"spotify": "https://open.spotify.com/album/al1"},
             "artists": [{"name": "Radiohead"}]},
        ]},
        "artists": {"items": [
            {"id": "ar1", "name": "Radiohead", "uri": "spotify:artist:ar1",
             "external_urls": {"spotify": "https://open.spotify.com/artist/ar1"},
             "genres": ["alt rock"]},
        ]},
        "playlists": {"items": [
            None,  # Spotify can return null playlist entries — must be skipped
            {"id": "pl1", "name": "Chill Mix", "uri": "spotify:playlist:pl1",
             "external_urls": {"spotify": "https://open.spotify.com/playlist/pl1"},
             "owner": {"display_name": "devon"}},
        ]},
    }


def _fake_sp(search=None):
    sp = MagicMock()
    sp.search.return_value = search if search is not None else _search_response()
    sp.artist_top_tracks.return_value = {"tracks": [
        {"uri": "spotify:track:tt1"}, {"uri": "spotify:track:tt2"}, None,
    ]}
    sp.artist.return_value = {"name": "Radiohead"}
    return sp


# --- search ----------------------------------------------------------------

def test_search_parses_all_kinds_and_skips_null():
    results = spotify.search("radiohead", sp=_fake_sp())
    kinds = [r.kind for r in results]
    assert kinds == ["track", "album", "artist", "playlist"]  # null playlist dropped
    track = results[0]
    assert track.name == "Karma Police"
    assert track.detail == "Radiohead"
    assert track.uri == "spotify:track:t1"
    playlist = results[-1]
    assert playlist.detail == "devon"  # owner display name


def test_search_rejects_unknown_type():
    with pytest.raises(spotify.SpotifyError):
        spotify.search("x", kinds=["bogus"], sp=_fake_sp())


def test_searchresult_as_dict_shape():
    r = spotify.search("radiohead", kinds=["track"], sp=_fake_sp())[0]
    assert set(r.as_dict()) == {"kind", "name", "detail", "uri", "url", "id"}


# --- resolve ---------------------------------------------------------------

def test_resolve_uri_passthrough():
    pt = spotify.resolve("spotify:track:abc123", sp=_fake_sp())
    assert pt.kind == "track"
    assert pt.links == ("spotify:track:abc123",)


def test_resolve_open_link():
    pt = spotify.resolve(
        "https://open.spotify.com/album/al9?si=xyz", sp=_fake_sp()
    )
    assert pt.kind == "album"
    assert pt.links == ("spotify:album:al9",)


def test_resolve_query_top_hit():
    # default kind is track; search returns only a track bucket
    sp = _fake_sp(search={"tracks": {"items": [
        {"id": "t1", "name": "Karma Police", "uri": "spotify:track:t1",
         "external_urls": {"spotify": "u"}, "artists": [{"name": "Radiohead"}]},
    ]}})
    pt = spotify.resolve("karma police", sp=sp)
    assert pt.kind == "track"
    assert pt.links == ("spotify:track:t1",)
    assert "Karma Police" in pt.label


def test_resolve_artist_uri_expands_to_top_tracks():
    pt = spotify.resolve("spotify:artist:ar1", sp=_fake_sp())
    assert pt.kind == "artist"
    # null track skipped; two playable top tracks
    assert pt.links == ("spotify:track:tt1", "spotify:track:tt2")
    assert "top tracks" in pt.label


# --- Sonos playback --------------------------------------------------------

def _coordinator():
    sp = MagicMock()
    sp.player_name = "Kitchen"
    return sp


@patch.object(sonos, "ShareLinkPlugin")
def test_play_spotify_now_clears_queue_and_plays_first(share_cls):
    share = share_cls.return_value
    share.add_share_link_to_queue.side_effect = itertools.count(1)  # 1-based
    coord = _coordinator()

    sonos.play_spotify([coord], ["spotify:track:t1"], label="Karma Police", mode="now")

    coord.clear_queue.assert_called_once()
    share.add_share_link_to_queue.assert_called_once()
    # 1-based enqueue index (1) -> 0-based play_from_queue (0)
    coord.play_from_queue.assert_called_once_with(0)


@patch.object(sonos, "ShareLinkPlugin")
def test_play_spotify_artist_enqueues_all_and_plays_first(share_cls):
    share = share_cls.return_value
    share.add_share_link_to_queue.side_effect = itertools.count(1)
    coord = _coordinator()

    links = ["spotify:track:a", "spotify:track:b", "spotify:track:c"]
    sonos.play_spotify([coord], links, label="Radiohead (top tracks)", mode="now")

    assert share.add_share_link_to_queue.call_count == 3
    coord.play_from_queue.assert_called_once_with(0)


@patch.object(sonos, "ShareLinkPlugin")
def test_play_spotify_add_mode_does_not_start_playback(share_cls):
    share = share_cls.return_value
    share.add_share_link_to_queue.side_effect = itertools.count(1)
    coord = _coordinator()

    sonos.play_spotify([coord], ["spotify:track:t1"], mode="add")

    coord.clear_queue.assert_not_called()
    coord.play_from_queue.assert_not_called()


@patch.object(sonos, "ShareLinkPlugin")
def test_play_spotify_enqueue_failure_raises_friendly_error(share_cls):
    share = share_cls.return_value
    share.add_share_link_to_queue.side_effect = SoCoException("UPnP Error 800")
    coord = _coordinator()

    with pytest.raises(sonos.SonosError) as exc:
        sonos.play_spotify([coord], ["spotify:track:t1"], mode="now")
    msg = str(exc.value).lower()
    assert "linked" in msg and "800" in msg  # friendly hint + raw error


def test_complete_auth_rejects_empty_input():
    with pytest.raises(spotify.SpotifyError):
        spotify.complete_auth("   ")


@patch.object(spotify, "_auth_manager")
def test_complete_auth_exchanges_code(am_factory):
    am = am_factory.return_value
    am.parse_response_code.return_value = "AUTHCODE123"
    with patch.object(spotify.spotipy, "Spotify") as spotify_cls:
        spotify_cls.return_value.me.return_value = {"id": "devon"}
        me = spotify.complete_auth("http://127.0.0.1:51777/callback?code=AUTHCODE123")
    am.get_access_token.assert_called_once()
    # the parsed code, not the raw URL, is exchanged
    assert am.get_access_token.call_args.args[0] == "AUTHCODE123"
    assert me["id"] == "devon"


@patch.object(sonos.MusicService, "get_all_music_services_names")
def test_spotify_linked(names_mock):
    names_mock.return_value = ["Spotify", "TuneIn"]
    assert sonos.spotify_linked() is True
    names_mock.return_value = ["TuneIn"]
    assert sonos.spotify_linked() is False
    names_mock.side_effect = RuntimeError("boom")
    assert sonos.spotify_linked() is False
