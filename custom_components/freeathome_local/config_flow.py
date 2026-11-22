"""Config and options flow for free@home Local."""

from __future__ import annotations

import logging
from ipaddress import IPv4Address
from typing import Any

import probatio
from homeassistant import config_entries, core, exceptions
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info import zeroconf

from .api import (
    FreeAtHomeApiError,
    FreeAtHomeAuthError,
    FreeAtHomeConnectionError,
    FreeAtHomeController,
    FreeAtHomeLocalApiClient,
)
from .const import (
    CONF_INCLUDE_ORPHAN_CHANNELS,
    CONF_NAME_PREFIX,
    CONF_SWITCH_AS_X,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DEFAULT_INCLUDE_ORPHAN_CHANNELS,
    DEFAULT_NAME_PREFIX,
    DEFAULT_SWITCH_AS_X,
    DEFAULT_USE_HTTPS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .migration import get_legacy_setup_defaults

_LOGGER = logging.getLogger(__name__)


class CannotConnect(exceptions.HomeAssistantError):
    """Error indicating the SysAP is unreachable."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error indicating invalid Local API credentials."""


async def validate_input(hass: core.HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate that credentials and host can reach the Local API."""
    use_https = bool(data.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS))
    verify_ssl = bool(data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)

    client = FreeAtHomeLocalApiClient(
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        session=session,
        use_https=use_https,
        verify_ssl=verify_ssl,
    )
    controller = FreeAtHomeController(client)
    try:
        title = await controller.validate_connection()
        return {
            "title": title,
            "serial_number": controller.sysap_serial,
            "sysap_uuid": controller.primary_sysap_uuid,
            "resolved_username": client.username,
        }
    except FreeAtHomeAuthError as err:
        raise InvalidAuth from err
    except (FreeAtHomeConnectionError, FreeAtHomeApiError) as err:
        raise CannotConnect from err
    finally:
        await controller.close()


def _shared_options_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return shared setup/options fields."""
    return {
        probatio.Optional(
            CONF_SWITCH_AS_X,
            default=defaults.get(CONF_SWITCH_AS_X, DEFAULT_SWITCH_AS_X),
        ): bool,
        probatio.Optional(
            CONF_NAME_PREFIX,
            default=defaults.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX),
        ): str,
        probatio.Optional(
            CONF_USE_HTTPS,
            default=defaults.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS),
        ): bool,
        probatio.Optional(
            CONF_VERIFY_SSL,
            default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        ): bool,
        probatio.Optional(
            CONF_INCLUDE_ORPHAN_CHANNELS,
            default=defaults.get(CONF_INCLUDE_ORPHAN_CHANNELS, DEFAULT_INCLUDE_ORPHAN_CHANNELS),
        ): bool,
    }


def _user_schema(defaults: dict[str, Any]) -> probatio.Schema:
    """Return user setup form schema."""
    schema: dict[Any, Any] = {
        probatio.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        probatio.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
        probatio.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
    }
    schema.update(_shared_options_schema(defaults))
    return probatio.Schema(schema)


def _discovery_schema(defaults: dict[str, Any]) -> probatio.Schema:
    """Return Zeroconf link form schema (host already known)."""
    schema: dict[Any, Any] = {
        probatio.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
        probatio.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
    }
    schema.update(_shared_options_schema(defaults))
    return probatio.Schema(schema)


class FreeAtHomeLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for free@home Local."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self.discovered_conf: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> FreeAtHomeLocalOptionsFlow:
        """Return the options flow handler."""
        return FreeAtHomeLocalOptionsFlow()

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle Zeroconf discovery of a SysAP."""
        if not isinstance(discovery_info.ip_address, IPv4Address):
            return self.async_abort(reason="not_ipv4address")

        host = discovery_info.ip_address.exploded
        friendly_name = discovery_info.name.split(":", 1)[-1].split(".", 1)[0]

        session = async_get_clientsession(self.hass, verify_ssl=False)
        client = FreeAtHomeLocalApiClient(host, "", "", session=session)
        try:
            settings = await client.fetch_settings_json()
        finally:
            await client.close()
        if not settings:
            return self.async_abort(reason="not_sysap")

        serial = (settings.get("flags") or {}).get("serialNumber")
        if not serial:
            return self.async_abort(reason="serialNumber_not_found")

        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self.discovered_conf = {
            CONF_NAME: friendly_name,
            CONF_HOST: host,
        }
        self.context["title_placeholders"] = self.discovered_conf
        return await self.async_step_link()

    async def async_step_link(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Finish linking a Zeroconf-discovered SysAP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**self.discovered_conf, **user_input}
            try:
                info = await validate_input(self.hass, merged)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during discovery link")
                errors["base"] = "unknown"
            else:
                if info.get("resolved_username"):
                    merged[CONF_USERNAME] = info["resolved_username"]
                unique = info.get("serial_number") or merged[CONF_HOST]
                await self.async_set_unique_id(unique, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=merged)

        defaults = (
            user_input
            if user_input is not None
            else {
                **get_legacy_setup_defaults(
                    self.hass,
                    host=self.discovered_conf.get(CONF_HOST),
                    serial_number=self.unique_id,
                ),
                **self.discovered_conf,
            }
        )
        return self.async_show_form(
            step_id="link",
            data_schema=_discovery_schema(defaults),
            errors=errors,
            description_placeholders=self.discovered_conf,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle manual user setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during user setup")
                errors["base"] = "unknown"
            else:
                saved_data = {**user_input}
                if info.get("resolved_username"):
                    saved_data[CONF_USERNAME] = info["resolved_username"]
                unique = info.get("serial_number") or user_input[CONF_HOST]
                await self.async_set_unique_id(unique, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=saved_data)

        defaults = user_input if user_input is not None else get_legacy_setup_defaults(self.hass)
        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(defaults),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Start re-authentication flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm updated credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                info = await validate_input(self.hass, data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                if info.get("resolved_username"):
                    data[CONF_USERNAME] = info["resolved_username"]
                return self.async_update_and_abort(entry, data=data, reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")
                    ): str,
                    probatio.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={CONF_HOST: entry.data[CONF_HOST]},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Reconfigure host or connection settings."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                info = await validate_input(self.hass, data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reconfigure")
                errors["base"] = "unknown"
            else:
                new_unique = info.get("serial_number") or data[CONF_HOST]
                if entry.unique_id and info.get("serial_number") and new_unique != entry.unique_id:
                    errors[CONF_HOST] = "other_sysap"
                else:
                    return self.async_update_and_abort(
                        entry, data=data, reason="reconfigure_successful"
                    )

        defaults = {**entry.data, **entry.options}
        schema: dict[Any, Any] = {
            probatio.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
        }
        schema.update(_shared_options_schema(defaults))
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=probatio.Schema(schema),
            errors=errors,
        )


class FreeAtHomeLocalOptionsFlow(config_entries.OptionsFlow):
    """Options flow allowing runtime tuning without re-adding the SysAP."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(_shared_options_schema(current)),
        )
