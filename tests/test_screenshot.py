"""Unit tests for screenshot action validation and capture metadata."""

import pytest

from dataviz_mcp.screenshot import _MAX_META_BYTES
from dataviz_mcp.screenshot import ActionError
from dataviz_mcp.screenshot import Capture
from dataviz_mcp.screenshot import apply_meta
from dataviz_mcp.screenshot import check_actions
from dataviz_mcp.screenshot import decode_meta
from dataviz_mcp.screenshot import encode_meta
from dataviz_mcp.screenshot import tile_label


def test_actions_accept_supported_steps():
    steps = [
        {"click": "Reports", "nth": 1},
        {"select": "Region", "value": "West"},
        {"fill": "Search", "value": "acme"},
        {"key": "Enter"},
        {"drag": [10, 20, 300, 400]},
        {"wait": 200},
    ]
    assert check_actions(steps) == steps


@pytest.mark.parametrize(
    ("steps", "match"),
    [
        ("click Reports", "must be a list"),
        ([{"scroll": "down"}], "Valid steps are"),
        ([{"click": "A", "fill": "B", "value": "x"}], "names 2 actions"),
        ([{"select": "Region"}], "needs a string 'value'"),
        ([{"drag": [True, 0, 1, 1]}], "needs exactly four numbers"),
        ([{"wait": -1}], "non-negative"),
    ],
)
def test_actions_reject_invalid_steps(steps, match):
    with pytest.raises(ActionError, match=match):
        check_actions(steps)


def test_action_limit_is_enforced():
    with pytest.raises(ActionError, match="at most 2"):
        check_actions([{"click": "A"}, {"click": "B"}, {"click": "C"}], limit=2)


def test_tiles_are_labelled_for_a_multi_screen_capture():
    assert tile_label(0, 1) == ""
    assert tile_label(1, 3) == "screen 2 of 3"


def test_capture_metadata_round_trip_and_stays_bounded():
    original = Capture(controls=["Overview", "Sales", "Costs"], total_tiles=5, captured_tiles=4)
    restored = apply_meta(Capture(), decode_meta(encode_meta(original)))
    assert restored.controls == original.controls
    assert (restored.total_tiles, restored.captured_tiles) == (5, 4)
    assert len(encode_meta(Capture(controls=["x" * 50_000] * 20))) <= _MAX_META_BYTES


def test_malformed_metadata_does_not_discard_the_capture():
    restored = apply_meta(Capture(images=[("", b"PNG")]), decode_meta("not-base64!!"))
    assert restored.png == b"PNG"
    assert restored.controls == []
