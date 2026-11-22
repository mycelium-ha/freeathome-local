"""Config, reauth, reconfigure, zeroconf and options flow tests against real HA."""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from mock_sysap_server import MockSysApServer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.freeathome_local.api import (
    FreeAtHomeApiError,
    FreeAtHomeAuthError,
    FreeAtHomeConnectionError,
)
from custom_components.freeathome_local.config_flow import CannotConnect, InvalidAuth
from custom_components.freeathome_local.const import (
    CONF_NAME_PREFIX,
    CONF_SWITCH_AS_X,
    DOMAIN,
    LEGACY_DOMAIN,
)

from .conftest import PASSWORD, SYSAP_SERIAL, USERNAME, entry_data

pytestmark = pytest.mark.usefixtures("mock_setup_entry")

VALIDATE = "custom_components.freeathome_local.config_flow.FreeAtHomeController.validate_connection"
FETCH_SETTINGS = (
    "custom_components.freeathome_local.config_flow.FreeAtHomeLocalApiClient.fetch_settings_json"
)
VALIDATE_INPUT = "custom_components.freeathome_local.config_flow.validate_input"

# Exceptions raised by `validate_input`, keyed by the expected form error.
LINK_ERRORS: dict[str, Exception] = {
    "invalid_auth": InvalidAuth(),
    "cannot_connect": CannotConnect(),
    "unknown": RuntimeError("unexpected"),
}


def _zeroconf(
    host: str = "192.168.1.50", name: str = "free@home:Living SysAP._http._tcp.local."
) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        port=80,
        hostname="sysap.local.",
        type="_http._tcp.local.",
        name=name,
        properties={},
    )


async def test_user_flow_success(hass: HomeAssistant, mock_sysap: MockSysApServer) -> None:
    """A valid manual setup creates an entry keyed by the SysAP serial."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**entry_data(mock_sysap), CONF_NAME_PREFIX: "Local "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test SysAP"
    assert result["data"][CONF_HOST] == mock_sysap.host_port
    assert result["data"][CONF_USERNAME] == USERNAME
    assert result["data"][CONF_NAME_PREFIX] == "Local "
    assert result["result"].unique_id == SYSAP_SERIAL


async def test_user_flow_resolves_display_username(
    hass: HomeAssistant, mock_sysap: MockSysApServer
) -> None:
    """A SysAP display name is resolved to the JID localpart via /settings.json."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], entry_data(mock_sysap, **{CONF_USERNAME: "installer"})
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == USERNAME


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (FreeAtHomeAuthError("bad"), "invalid_auth"),
        (FreeAtHomeConnectionError("down"), "cannot_connect"),
        (FreeAtHomeApiError("boom"), "cannot_connect"),
        (RuntimeError("unexpected"), "unknown"),
    ],
)
async def test_user_flow_errors_recover(
    hass: HomeAssistant, mock_sysap: MockSysApServer, side_effect: Exception, error: str
) -> None:
    """Each failure shows its error and the flow can still complete afterwards."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(VALIDATE, side_effect=side_effect):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], entry_data(mock_sysap)
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], entry_data(mock_sysap)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_wrong_password(hass: HomeAssistant, mock_sysap: MockSysApServer) -> None:
    """Credentials rejected by the real (mock) SysAP map to invalid_auth."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], entry_data(mock_sysap, **{CONF_PASSWORD: "wrong"})
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_sysap: MockSysApServer, mock_config_entry: MockConfigEntry
) -> None:
    """The same SysAP cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], entry_data(mock_sysap)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_prefills_legacy_defaults(hass: HomeAssistant) -> None:
    """Settings of a legacy `freeathome` entry pre-fill the form without touching it."""
    legacy = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        data={
            CONF_HOST: "192.168.1.60",
            CONF_USERNAME: "u",
            CONF_PASSWORD: "p",
            "use_room_names": True,  # legacy option without a counterpart here
            CONF_SWITCH_AS_X: True,
        },
    )
    legacy.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    defaults = {
        str(key): key.default() for key in result["data_schema"].schema if callable(key.default)
    }
    assert defaults[CONF_HOST] == "192.168.1.60"
    assert "use_room_names" not in defaults
    assert defaults[CONF_SWITCH_AS_X] is True
    assert legacy.data[CONF_HOST] == "192.168.1.60"


async def test_zeroconf_link_flow(hass: HomeAssistant) -> None:
    """A discovered SysAP is linked with credentials only."""
    with patch(FETCH_SETTINGS, return_value={"flags": {"serialNumber": SYSAP_SERIAL}}):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf()
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "link"
    assert result["description_placeholders"] == {
        CONF_NAME: "Living SysAP",
        CONF_HOST: "192.168.1.50",
    }

    info = {"title": "Living SysAP", "serial_number": SYSAP_SERIAL, "resolved_username": USERNAME}
    with patch(VALIDATE_INPUT, AsyncMock(side_effect=LINK_ERRORS["invalid_auth"])):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "installer", CONF_PASSWORD: PASSWORD}
        )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch(VALIDATE_INPUT, AsyncMock(return_value=info)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: "installer", CONF_PASSWORD: PASSWORD}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living SysAP"
    assert result["data"][CONF_HOST] == "192.168.1.50"
    assert result["data"][CONF_USERNAME] == USERNAME
    assert result["result"].unique_id == SYSAP_SERIAL


@pytest.mark.parametrize(
    ("error", "reason"),
    [("cannot_connect", "cannot_connect"), ("unknown", "unknown")],
)
async def test_zeroconf_link_errors(hass: HomeAssistant, error: str, reason: str) -> None:
    """Link step maps connection and unexpected errors."""
    with patch(FETCH_SETTINGS, return_value={"flags": {"serialNumber": SYSAP_SERIAL}}):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf()
        )
    side_effect = LINK_ERRORS[error]
    with patch(VALIDATE_INPUT, AsyncMock(side_effect=side_effect)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
        )
    assert result["errors"] == {"base": reason}


async def test_zeroconf_updates_host_of_existing_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Rediscovery of a known SysAP updates its host and aborts."""
    mock_config_entry.add_to_hass(hass)
    with patch(FETCH_SETTINGS, return_value={"flags": {"serialNumber": SYSAP_SERIAL}}):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf("192.168.1.55")
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_HOST] == "192.168.1.55"


@pytest.mark.parametrize(
    ("discovery", "settings", "reason"),
    [
        (_zeroconf("fe80::1"), {"flags": {"serialNumber": SYSAP_SERIAL}}, "not_ipv4address"),
        (_zeroconf(), None, "not_sysap"),
        (_zeroconf(), {"flags": {}}, "serialNumber_not_found"),
    ],
)
async def test_zeroconf_aborts(
    hass: HomeAssistant,
    discovery: ZeroconfServiceInfo,
    settings: dict[str, Any] | None,
    reason: str,
) -> None:
    """Non-IPv4, non-SysAP and serial-less discoveries abort."""
    with patch(FETCH_SETTINGS, return_value=settings):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=discovery
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


async def test_reauth_flow(
    hass: HomeAssistant, mock_sysap: MockSysApServer, mock_config_entry: MockConfigEntry
) -> None:
    """Reauth stores new credentials after showing errors for wrong ones."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_PASSWORD: "old"}
    )
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"][CONF_HOST] == mock_sysap.host_port

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: "still-wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    for side_effect, error in (
        (FreeAtHomeConnectionError("down"), "cannot_connect"),
        (RuntimeError("unexpected"), "unknown"),
    ):
        with patch(VALIDATE, side_effect=side_effect):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
            )
        assert result["errors"] == {"base": error}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == PASSWORD


async def test_reconfigure_flow(
    hass: HomeAssistant, mock_sysap: MockSysApServer, mock_config_entry: MockConfigEntry
) -> None:
    """Reconfigure updates connection settings of the same SysAP."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    for side_effect, error in (
        (FreeAtHomeAuthError("bad"), "invalid_auth"),
        (FreeAtHomeConnectionError("down"), "cannot_connect"),
        (RuntimeError("unexpected"), "unknown"),
    ):
        with patch(VALIDATE, side_effect=side_effect):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_HOST: mock_sysap.host_port}
            )
        assert result["errors"] == {"base": error}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: mock_sysap.host_port, CONF_NAME_PREFIX: "Local "}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_NAME_PREFIX] == "Local "


async def test_reconfigure_rejects_other_sysap(
    hass: HomeAssistant, mock_sysap: MockSysApServer, mock_config_entry: MockConfigEntry
) -> None:
    """Pointing an entry at a different SysAP is refused."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, unique_id="ABB700000001")
    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: mock_sysap.host_port}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_HOST: "other_sysap"}


async def test_options_flow(hass: HomeAssistant, mock_config_entry: MockConfigEntry) -> None:
    """Options are stored on the entry."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME_PREFIX: "Test "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "use_room_names" not in mock_config_entry.options
    assert mock_config_entry.options[CONF_NAME_PREFIX] == "Test "
