"""Regression tests for streamer Icecast source recovery (Issue #49).

The GStreamer API is replaced by minimal test doubles because CI does not install
PyGObject/GStreamer. These tests check Python control flow, not actual decoding,
mixing, or MPEG-TS playback; the latter needs a separate integration test.
"""

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call

import pytest


@pytest.fixture
def streamer(monkeypatch):
    """Import the real streamer with only its GObject bindings stubbed out."""
    gst = SimpleNamespace(
        SECOND=1_000_000_000,
        State=SimpleNamespace(NULL="NULL"),
        PadLinkReturn=SimpleNamespace(OK="OK"),
        MessageType=SimpleNamespace(ERROR="ERROR", EOS="EOS", WARNING="WARNING"),
        ElementFactory=SimpleNamespace(make=Mock()),
        init=Mock(),
    )
    glib = SimpleNamespace(timeout_add_seconds=Mock(return_value=101))
    gst_app = SimpleNamespace()

    gi = ModuleType("gi")
    gi.require_version = Mock()
    repository = ModuleType("gi.repository")
    repository.Gst = gst
    repository.GLib = glib
    repository.GstApp = gst_app
    gi.repository = repository
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)

    path = Path(__file__).resolve().parents[1] / "streamer.py"
    spec = importlib.util.spec_from_file_location("_streamer_recovery_test", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    module.logger = logging.getLogger("test_streamer_recovery")
    module.audio_failed = False
    module.audio_reconnecting = False
    module.reconnect_source_id = None
    module.ICECAST_URL = "http://example.invalid/test.aac"
    module.pipeline = Mock()
    module.main_loop = Mock()
    module.GLib = glib
    module.Gst = gst
    return module


def audio_pad(streamer, link_result=None):
    """Create a decoded audio pad and an unlinked audioconvert input."""
    pad = Mock()
    caps = Mock()
    caps.get_structure.return_value.get_name.return_value = "audio/x-raw"
    pad.get_current_caps.return_value = caps
    pad.link.return_value = (
        streamer.Gst.PadLinkReturn.OK if link_result is None else link_result
    )
    sink = Mock()
    sink.is_linked.return_value = False
    converter = Mock()
    converter.get_static_pad.return_value = sink
    return pad, sink, converter


def clock_at(streamer, now_seconds, base_seconds=0):
    clock = Mock()
    clock.get_time.return_value = now_seconds * streamer.Gst.SECOND
    streamer.pipeline.get_clock.return_value = clock
    streamer.pipeline.get_base_time.return_value = base_seconds * streamer.Gst.SECOND
    return clock


def test_initial_audio_link_does_not_apply_reconnection_offset(streamer):
    pad, sink, converter = audio_pad(streamer)
    clock_at(streamer, 60, 10)

    streamer.on_audio_pad_added(Mock(), pad, converter)

    pad.link.assert_called_once_with(sink)
    pad.set_offset.assert_not_called()
    assert streamer.audio_failed is False
    assert streamer.audio_reconnecting is False


def test_reconnected_audio_uses_pipeline_running_time(streamer):
    streamer.audio_failed = True
    streamer.audio_reconnecting = True
    clock_at(streamer, 150, 40)
    pad, sink, converter = audio_pad(streamer)

    streamer.on_audio_pad_added(Mock(), pad, converter)

    pad.set_offset.assert_called_once_with(110 * streamer.Gst.SECOND)
    pad.link.assert_called_once_with(sink)
    assert pad.mock_calls.index(call.set_offset(110 * streamer.Gst.SECOND)) < pad.mock_calls.index(
        call.link(sink)
    )
    assert streamer.audio_failed is False
    assert streamer.audio_reconnecting is False


def test_reconnection_without_clock_does_not_link_audio(streamer):
    """Do not link recovered audio without a valid pipeline clock."""
    streamer.audio_failed = True
    streamer.pipeline = Mock()
    streamer.pipeline.get_clock.return_value = None

    pad, _sink, converter = audio_pad(streamer)

    streamer.on_audio_pad_added(Mock(), pad, converter)

    pad.set_offset.assert_not_called()
    pad.link.assert_not_called()

    assert streamer.audio_failed is True


def test_each_reconnection_gets_fresh_non_accumulating_offset(streamer):
    for running_time in (105, 184):
        streamer.audio_failed = True
        clock_at(streamer, running_time + 30, 30)
        pad, _sink, converter = audio_pad(streamer)

        streamer.on_audio_pad_added(Mock(), pad, converter)

        pad.set_offset.assert_called_once_with(running_time * streamer.Gst.SECOND)
        assert streamer.audio_failed is False


def test_failed_audio_link_does_not_clear_failure_state(streamer, caplog):
    streamer.audio_failed = True
    clock_at(streamer, 80)
    pad, _sink, converter = audio_pad(streamer, link_result="WRONG_HIERARCHY")

    with caplog.at_level(logging.ERROR):
        streamer.on_audio_pad_added(Mock(), pad, converter)

    assert "Unable to link Icecast audio" in caplog.text
    assert streamer.audio_failed is True


def test_reconnect_replaces_source_and_does_not_restart_pipeline(streamer):
    old_source = Mock()
    new_source = Mock()
    streamer.icecast_source = old_source
    streamer.audio_convert = Mock()
    streamer.Gst.ElementFactory.make.return_value = new_source

    result = streamer.reconnect_audio_source()

    assert result is False  # GLib timeout runs once, not repeatedly.
    old_source.set_state.assert_called_once_with(streamer.Gst.State.NULL)
    streamer.pipeline.remove.assert_called_once_with(old_source)
    streamer.pipeline.add.assert_called_once_with(new_source)
    new_source.set_property.assert_called_once_with("uri", streamer.ICECAST_URL)
    new_source.connect.assert_called_once_with(
        "pad-added", streamer.on_audio_pad_added, streamer.audio_convert
    )
    new_source.sync_state_with_parent.assert_called_once_with()
    assert streamer.icecast_source is new_source
    assert streamer.audio_reconnecting is False
    assert streamer.reconnect_source_id is None
    streamer.pipeline.set_state.assert_not_called()


def test_source_creation_failure_does_not_claim_success(streamer, caplog):
    streamer.icecast_source = None
    streamer.Gst.ElementFactory.make.return_value = None

    with caplog.at_level(logging.ERROR):
        result = streamer.reconnect_audio_source()

    assert result is False
    assert "Unable to create new Icecast source" in caplog.text
    assert streamer.audio_reconnecting is False
    assert streamer.reconnect_source_id is None


def error_message(streamer, source):
    message = Mock()
    message.type = streamer.Gst.MessageType.ERROR
    message.src = source
    message.parse_error.return_value = (RuntimeError("connection lost"), "debug detail")
    return message


def test_audio_error_schedules_one_reconnect_timer(streamer):
    icecast = Mock()
    source = Mock()
    source.get_name.return_value = "souphttpsrc0"
    source.get_parent.return_value = icecast
    streamer.pipeline.get_by_name.return_value = icecast
    message = error_message(streamer, source)

    assert streamer.on_message(None, message) is True
    assert streamer.on_message(None, message) is True

    assert streamer.audio_failed is True
    assert streamer.reconnect_source_id == 101
    streamer.GLib.timeout_add_seconds.assert_called_once_with(
        5, streamer.reconnect_audio_source
    )
    streamer.main_loop.quit.assert_not_called()


def test_unrelated_gstreamer_error_stops_main_loop(streamer):
    icecast = Mock()
    source = Mock()
    source.get_name.return_value = "video-encoder"
    source.get_parent.return_value = None
    streamer.pipeline.get_by_name.return_value = icecast

    streamer.on_message(None, error_message(streamer, source))

    streamer.main_loop.quit.assert_called_once_with()
    streamer.GLib.timeout_add_seconds.assert_not_called()
