"""Tests for CLI helpers (no Typer invocation needed)."""

from houseparty import cli


def test_now_label_spotify_track():
    info = {
        "source_uri": "x-rincon-queue:RINCON_ABC#0",
        "track_artist": "Jack Garratt",
        "track_title": "Pillars",
        "track_album": "The Tension Between",
    }
    assert cli._now_label(info, []) == "Jack Garratt — Pillars · The Tension Between"


def test_now_label_spotify_single_no_redundant_album():
    info = {
        "source_uri": "x-rincon-queue:RINCON_ABC#0",
        "track_artist": "Someone",
        "track_title": "A Song",
        "track_album": "A Song",  # single: album == title -> not repeated
    }
    assert cli._now_label(info, []) == "Someone — A Song"


def test_now_label_radio_identified_by_uri():
    info = {
        "source_uri": "x-rincon-mp3radio://stream-relay-geo.ntslive.net/stream",
        "track_artist": "",
        "track_title": "",
        "source_title": "",
    }
    assert cli._now_label(info, []) == "NTS 1"


def test_now_label_falls_back_to_source_title():
    info = {"source_uri": "x-rincon-mp3radio://unknown/host", "source_title": "Some Station"}
    assert cli._now_label(info, []) == "Some Station"
