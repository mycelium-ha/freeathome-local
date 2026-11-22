"""ID parsing, event decoding and binary sensor behaviour."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from mock_sysap_server import MockSysApServer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.freeathome_local.api.const import parse_hex_id, parse_pairing_id
from custom_components.freeathome_local.fah_event import (
    dimming_status_from_event,
    dimming_status_sequence_from_event,
    event_type_from_event,
)

from .conftest import entity_id_for
from .test_platforms import _broadcast_dp

WINDOW = ("binary_sensor", "ABB700D10008/ch0000")
DOORBELL = ("binary_sensor", "ABB700D10010/ch0001")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), (0x12, 0x12), (" 0012 ", 0x12), ("zz", None)],
)
def test_parse_hex_id(value: Any, expected: int | None) -> None:
    """Function and parameter IDs are hexadecimal."""
    assert parse_hex_id(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), (256, 256), ("256", 256), ("0x100", 256), ("1a", 26), ("zz", None)],
)
def test_parse_pairing_id(value: Any, expected: int | None) -> None:
    """Pairing IDs are decimal, with a hexadecimal fallback."""
    assert parse_pairing_id(value) == expected


@pytest.mark.parametrize(
    ("event", "status", "sequence", "event_type"),
    [
        (
            {"command": "pressed", "state": True},
            "pressed_up",
            ("pressed_up", "not_pressed"),
            "press_up",
        ),
        (
            {"command": "pressed", "state": False},
            "pressed_down",
            ("pressed_down", "not_pressed"),
            "press_down",
        ),
        ({"command": "pressed", "state": None}, None, (), None),
        ({"command": "dim_start", "direction": "up"}, "held_up", ("held_up",), "hold_up"),
        ({"command": "dim_start", "direction": "down"}, "held_down", ("held_down",), "hold_down"),
        ({"command": "dim_start", "direction": "sideways"}, None, (), None),
        ({"command": "dim_stop"}, None, ("not_pressed",), "release"),
        ({"command": "other"}, None, (), None),
    ],
)
def test_event_decoding(
    event: dict[str, Any], status: str | None, sequence: tuple[str, ...], event_type: str | None
) -> None:
    """Decoded datapoint events map to dimming states and event entity types."""
    assert dimming_status_from_event(event) == status
    assert dimming_status_sequence_from_event(event) == sequence
    assert event_type_from_event(event) == event_type


async def test_window_position_only_as_sensor(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The window contact carries no position attribute; the position sensor shows it."""
    assert "window_position" not in hass.states.get(entity_id_for(hass, *WINDOW)).attributes
    position = entity_id_for(hass, "sensor", "ABB700D10008/ch0000/window_position")
    assert hass.states.get(position).state == "tilted"


async def test_doorbell_resets_after_pulse(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """A ring turns the doorbell on; it resets on its own after the pulse."""
    doorbell = entity_id_for(hass, *DOORBELL)
    assert hass.states.get(doorbell).state == "off"
    seen: list[str] = []

    @callback
    def _record(event: Event[EventStateChangedData]) -> None:
        if (new_state := event.data["new_state"]) is not None:
            seen.append(new_state.state)

    async_track_state_change_event(hass, doorbell, _record)
    real_sleep = asyncio.sleep

    async def _short_pulse(delay: float) -> None:
        # Only the two-second doorbell pulse is shortened.
        await real_sleep(0 if delay == 2 else delay)

    with patch("custom_components.freeathome_local.binary_sensor.asyncio.sleep", _short_pulse):
        await _broadcast_dp(mock_sysap, "ABB700D10010/ch0001/odp0000", "1")
        for _ in range(50):
            await hass.async_block_till_done()
            if len(seen) >= 2:
                break
            await asyncio.sleep(0.02)
    assert seen[:2] == ["on", "off"]
