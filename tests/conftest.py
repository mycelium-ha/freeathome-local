"""Shared fixtures for the free@home Local test suite (real Home Assistant core)."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import HomeAssistantSnapshotExtension
from syrupy.assertion import SnapshotAssertion

TESTS_DIR = Path(__file__).parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from mock_sysap_server import MockSysApServer  # noqa: E402

from custom_components.freeathome_local.const import DOMAIN  # noqa: E402

SYSAP_UUID = "00000000-0000-0000-0000-000000000000"
SYSAP_SERIAL = "ABB700999999"
USERNAME = "apiuser"
PASSWORD = "secret"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load `custom_components/freeathome_local` in every test."""


@pytest.fixture(autouse=True)
def _allow_localhost_sockets(socket_enabled: None) -> None:
    """Allow real sockets so tests can talk to the local mock SysAP.

    `pytest-homeassistant-custom-component` still restricts connections to 127.0.0.1.
    """


@pytest.fixture
async def mock_sysap() -> AsyncGenerator[MockSysApServer]:
    """Start a mock SysAP (REST + WebSocket) on a free localhost port."""
    server = MockSysApServer(port=0, username=USERNAME, password=PASSWORD)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


def entity_id_for(hass: HomeAssistant, platform: str, uid_tail: str) -> str:
    """Return the entity ID of `{SYSAP_UUID}/{uid_tail}` on `platform`.

    Tests look entities up by unique ID, because Home Assistant releases generate
    entity IDs for child devices differently.
    """
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{SYSAP_UUID}/{uid_tail}")
    assert entity_id is not None, f"no {platform} entity for {uid_tail}"
    return entity_id


def entry_data(server: MockSysApServer, **overrides: Any) -> dict[str, Any]:
    """Return config entry data pointing at the mock SysAP."""
    return {
        CONF_HOST: server.host_port,
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
        **overrides,
    }


@pytest.fixture
def mock_config_entry(mock_sysap: MockSysApServer) -> MockConfigEntry:
    """Return a config entry for the mock SysAP (not yet added to hass)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Mock SysAP",
        unique_id=SYSAP_SERIAL,
        data=entry_data(mock_sysap),
        entry_id="01JNGTESTENTRY0000000000000",
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration against the mock SysAP and return the entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


@pytest.fixture
def mock_setup_entry() -> Generator[Any]:
    """Prevent the integration from being set up during config flow tests."""
    with patch(
        "custom_components.freeathome_local.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Enable entities that are disabled by default, so snapshots cover all of them."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Return snapshot assertion fixture with the Home Assistant extension."""
    return snapshot.use_extension(HomeAssistantSnapshotExtension)
