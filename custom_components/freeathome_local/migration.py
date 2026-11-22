"""Migration helpers for moving devices, metadata, and history from legacy `freeathome`."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_NAME_PREFIX,
    CONF_SWITCH_AS_X,
    DEFAULT_NAME_PREFIX,
    DEFAULT_SWITCH_AS_X,
    DOMAIN,
    LEGACY_DOMAIN,
)

if TYPE_CHECKING:
    from . import FreeAtHomeLocalRuntime

_LOGGER = logging.getLogger(__name__)
_CHANNEL_RE = re.compile(r"^ch[0-9a-fA-F]{4}$")


@dataclass(frozen=True)
class ParsedLegacyUniqueId:
    """Parsed components of a legacy `freeathome` entity `unique_id`."""

    serialnumber: str
    channel_id: str
    suffix: str = ""
    sysap_prefix: str | None = None


@dataclass
class LegacyDeviceInfo:
    """Discovered device from legacy `freeathome` device registry."""

    serialnumber: str
    entry_id: str | None
    device_registry_id: str | None
    title: str
    device_name: str | None = None
    area_id: str | None = None
    labels: set[str] = field(default_factory=set)

    def as_summary(self) -> dict[str, Any]:
        """Return JSON-serializable summary representation."""
        return {
            "serialnumber": self.serialnumber,
            "legacy_entry_id": self.entry_id,
            "title": self.title,
            "device_name": self.device_name,
            "area_id": self.area_id,
            "labels": sorted(self.labels),
        }


@dataclass
class LegacyEntityInfo:
    """Mapped entity from legacy `freeathome` entity registry."""

    entity_id: str
    unique_id: str
    serialnumber: str
    channel_id: str
    suffix: str
    legacy_domain: str
    target_domain: str
    target_unique_id: str
    config_entry_id: str | None = None
    name: str | None = None
    icon: str | None = None
    area_id: str | None = None
    aliases: list[Any] | None = None
    labels: set[str] = field(default_factory=set)
    disabled_by_user: bool = False
    hidden_by_user: bool = False
    options: dict[str, dict[str, Any]] = field(default_factory=dict)
    domain_changed: bool = False
    registry_id: str | None = None

    def as_summary(
        self,
        *,
        cutover: bool,
        current_target_entity_id: str | None = None,
        target_entity_id: str | None = None,
    ) -> dict[str, Any]:
        """Return JSON-serializable summary representation."""
        return {
            "legacy_entity_id": self.entity_id,
            "legacy_unique_id": self.unique_id,
            "serialnumber": self.serialnumber,
            "channel_id": self.channel_id,
            "legacy_domain": self.legacy_domain,
            "target_domain": self.target_domain,
            "target_unique_id": self.target_unique_id,
            "current_target_entity_id": current_target_entity_id,
            "target_entity_id": target_entity_id,
            "will_rename_entity_id": bool(
                cutover
                and not self.domain_changed
                and target_entity_id == self.entity_id
                and current_target_entity_id != self.entity_id
            ),
            "history_preserved": bool(
                cutover and not self.domain_changed and target_entity_id == self.entity_id
            ),
            "domain_changed": self.domain_changed,
            "name": self.name,
            "area_id": self.area_id,
            "icon": self.icon,
            "aliases": sorted(a for a in (self.aliases or ()) if isinstance(a, str)),
            "labels": sorted(self.labels),
            "disabled_by_user": self.disabled_by_user,
            "hidden_by_user": self.hidden_by_user,
            "option_domains": sorted(self.options),
        }


def parse_legacy_unique_id(unique_id: str) -> ParsedLegacyUniqueId | None:
    """Parse legacy `freeathome` unique_id into serial, channel, and suffix."""
    raw = unique_id.strip()
    if not raw or "/" not in raw:
        return None
    parts = [part.strip() for part in raw.split("/")]

    # Format A: `<SERIAL>/chXXXX` (+ optional `/odpXXXX`, `/current_temperature`, `/dimming_status`)
    if len(parts) >= 2 and parts[0] and _CHANNEL_RE.match(parts[1]):
        suffix = f"/{'/'.join(parts[2:])}" if len(parts) > 2 and any(parts[2:]) else ""
        return ParsedLegacyUniqueId(
            serialnumber=parts[0],
            channel_id=parts[1],
            suffix=suffix,
        )

    # Format B (virtual devices / scenes on multi-SysAP legacy): `<SYSAP_ID>/FFFF.../chXXXX`
    if len(parts) >= 3 and parts[0] and parts[1] and _CHANNEL_RE.match(parts[2]):
        suffix = f"/{'/'.join(parts[3:])}" if len(parts) > 3 and any(parts[3:]) else ""
        return ParsedLegacyUniqueId(
            serialnumber=parts[1],
            channel_id=parts[2],
            suffix=suffix,
            sysap_prefix=parts[0],
        )

    return None


def parse_serialnumbers_text(raw: str) -> list[str]:
    """Parse comma-, space-, or newline-separated serial numbers uniquely."""
    seen: set[str] = set()
    result: list[str] = []
    for token in re.split(r"[\s,]+", raw.strip()):
        cleaned = token.strip().upper()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _is_user_reason(reason: Any) -> bool:
    """Return True only if disabled_by/hidden_by represents a user-initiated action."""
    if reason is None:
        return False
    value = getattr(reason, "value", reason)
    return str(value).strip().lower().endswith("user")


def _extract_entity_options(raw_options: Any) -> dict[str, dict[str, Any]]:
    """Extract user-meaningful entity options, dropping legacy precision defaults."""
    if not isinstance(raw_options, dict) and not hasattr(raw_options, "items"):
        return {}
    cleaned: dict[str, dict[str, Any]] = {}
    for opt_domain, opt_values in raw_options.items():
        if not isinstance(opt_domain, str) or not hasattr(opt_values, "items"):
            continue
        if opt_domain == LEGACY_DOMAIN:
            continue
        copied = {
            k: v
            for k, v in opt_values.items()
            if not (opt_domain == "sensor" and k == "suggested_display_precision")
        }
        if copied:
            cleaned[opt_domain] = copied
    return cleaned


def _extract_aliases(raw_aliases: Any) -> list[Any] | None:
    """Return aliases (in order) when user-defined string aliases exist, keeping markers."""
    if not raw_aliases:
        return None
    alias_items = list(dict.fromkeys(raw_aliases))
    if any(isinstance(item, str) and item for item in alias_items):
        return alias_items
    return None


def _iter_entity_entries(ent_reg: er.EntityRegistry) -> list[er.RegistryEntry]:
    """Return all entity registry entries."""
    return list(ent_reg.entities.values())


def _lookup_device(
    dev_reg: dr.DeviceRegistry,
    domain: str,
    identifier_value: str,
    *,
    config_entry_id: str | None,
) -> dr.DeviceEntry | None:
    """Look up the device with `(domain, identifier_value)` owned by `config_entry_id`."""
    if not config_entry_id:
        return None
    return dev_reg.async_get_device_by_identifier((domain, identifier_value), config_entry_id)


def _legacy_config_entries(hass: Any) -> list[ConfigEntry[Any]]:
    """Return all configured legacy `freeathome` config entries."""
    if hass is None:
        return []
    return [
        entry
        for entry in hass.config_entries.async_entries(LEGACY_DOMAIN)
        if getattr(entry, "domain", None) == LEGACY_DOMAIN
    ]


def find_matching_legacy_entry(hass: Any, hub_entry: ConfigEntry[Any]) -> ConfigEntry[Any] | None:
    """Match the legacy `freeathome` config entry corresponding to `hub_entry`."""
    legacy_entries = _legacy_config_entries(hass)
    if not legacy_entries:
        return None

    runtime: FreeAtHomeLocalRuntime | None = getattr(hub_entry, "runtime_data", None)
    hub_serial = (
        str(
            getattr(hub_entry, "unique_id", None)
            or (getattr(runtime.controller, "sysap_serial", None) if runtime else None)
            or ""
        )
        .strip()
        .upper()
    )
    hub_host = str(hub_entry.data.get(CONF_HOST, "")).strip().lower()

    if hub_serial:
        for entry in legacy_entries:
            leg_serial = str(getattr(entry, "unique_id", None) or "").strip().upper()
            if leg_serial and leg_serial == hub_serial:
                return entry

    if hub_host:
        for entry in legacy_entries:
            leg_host = str(entry.data.get(CONF_HOST, "")).strip().lower()
            if leg_host and leg_host == hub_host:
                return entry

    if len(legacy_entries) == 1:
        return legacy_entries[0]

    return None


def get_legacy_setup_defaults(
    hass: Any,
    *,
    host: str | None = None,
    serial_number: str | None = None,
) -> dict[str, Any]:
    """Return non-destructive setup defaults read from a legacy `freeathome` entry."""
    legacy_entries = _legacy_config_entries(hass)
    if not legacy_entries:
        return {}

    matched: ConfigEntry[Any] | None = None
    target_serial = (serial_number or "").strip().upper()
    target_host = (host or "").strip().lower()

    if target_serial:
        matched = next(
            (
                entry
                for entry in legacy_entries
                if str(getattr(entry, "unique_id", None) or "").strip().upper() == target_serial
            ),
            None,
        )
    if matched is None and target_host:
        matched = next(
            (
                entry
                for entry in legacy_entries
                if str(entry.data.get(CONF_HOST, "")).strip().lower() == target_host
            ),
            None,
        )
    if matched is None and len(legacy_entries) == 1:
        matched = legacy_entries[0]
    if matched is None:
        return {}

    defaults: dict[str, Any] = {}
    if matched.data.get(CONF_HOST):
        defaults[CONF_HOST] = str(matched.data[CONF_HOST])
    if CONF_SWITCH_AS_X in matched.data:
        defaults[CONF_SWITCH_AS_X] = bool(matched.data[CONF_SWITCH_AS_X])
    return defaults


def _candidate_sysap_uuids(hub_entry: ConfigEntry[Any]) -> list[str]:
    """Return ordered SysAP UUIDs owned by `hub_entry`."""
    runtime: FreeAtHomeLocalRuntime | None = getattr(hub_entry, "runtime_data", None)
    if runtime is None:
        return ["00000000-0000-0000-0000-000000000000"]
    uuids = list(getattr(runtime.controller, "sysap_uuids", ()) or ())
    if uuids:
        return uuids
    primary = getattr(runtime.controller, "primary_sysap_uuid", "")
    return [primary or "00000000-0000-0000-0000-000000000000"]


def _uid_key(unique_id: str) -> str:
    """Return the lookup key of a unique ID.

    Unique IDs are compared without case: the legacy integration writes channel IDs
    in upper case (`ch001A`), the Local API and this integration in lower case (`ch001a`).
    """
    return unique_id.casefold()


def _index_target_entities(
    ent_reg: Any, hub_entry_id: str
) -> tuple[dict[tuple[str, str], Any], dict[str, Any]]:
    """Index free@home Local entity registry entries by `(domain, unique_id)` and `unique_id`.

    Keys use `_uid_key`, so look them up with `_uid_key` too.
    """
    by_domain_uid: dict[tuple[str, str], Any] = {}
    by_uid: dict[str, Any] = {}
    for ent_entry in er.async_entries_for_config_entry(ent_reg, hub_entry_id):
        entity_id = str(getattr(ent_entry, "entity_id", ""))
        ent_domain = str(
            getattr(ent_entry, "domain", None)
            or (entity_id.split(".", 1)[0] if "." in entity_id else "sensor")
        )
        unique_id = str(getattr(ent_entry, "unique_id", ""))
        if unique_id:
            by_domain_uid[(ent_domain, _uid_key(unique_id))] = ent_entry
            by_uid.setdefault(_uid_key(unique_id), ent_entry)
    return by_domain_uid, by_uid


def _build_legacy_device_info(
    dev_entry: Any,
    serialnumber: str,
    entry_id: str | None,
) -> LegacyDeviceInfo:
    """Create a `LegacyDeviceInfo` from a DeviceEntry."""
    raw_name_by_user = getattr(dev_entry, "name_by_user", None)
    device_name = (
        str(raw_name_by_user).strip()
        if isinstance(raw_name_by_user, str) and raw_name_by_user.strip()
        else None
    )
    area_id = getattr(dev_entry, "area_id", None)
    labels = set(getattr(dev_entry, "labels", None) or ())
    title = str(getattr(dev_entry, "name", None) or serialnumber)

    return LegacyDeviceInfo(
        serialnumber=serialnumber,
        entry_id=entry_id,
        device_registry_id=getattr(dev_entry, "id", None),
        title=title,
        device_name=device_name,
        area_id=area_id if isinstance(area_id, str) and area_id else None,
        labels={str(lbl) for lbl in labels if lbl},
    )


def discover_legacy_devices(
    hass: Any,
    legacy_entry: ConfigEntry[Any] | None,
    legacy_entities: list[LegacyEntityInfo] | None = None,
    *,
    serialnumbers_filter: set[str] | None = None,
) -> list[LegacyDeviceInfo]:
    """Discover legacy `freeathome` device metadata from the device registry."""
    if hass is None:
        return []

    dev_reg = dr.async_get(hass)
    discovered: dict[str, LegacyDeviceInfo] = {}

    legacy_entry_ids = (
        [legacy_entry.entry_id]
        if legacy_entry is not None
        else [entry.entry_id for entry in _legacy_config_entries(hass)]
    )
    candidates = [
        (entry_id, dev_entry)
        for entry_id in legacy_entry_ids
        for dev_entry in dr.async_entries_for_config_entry(dev_reg, entry_id)
    ]
    for entry_id, dev_entry in candidates:
        serial = next(
            (
                ident_val
                for ident_dom, ident_val in getattr(dev_entry, "identifiers", ())
                if ident_dom == LEGACY_DOMAIN and ident_val
            ),
            None,
        )
        if not serial:
            continue
        if serialnumbers_filter is not None and serial.upper() not in serialnumbers_filter:
            continue
        discovered[serial] = _build_legacy_device_info(dev_entry, serial, entry_id)

    # Supplement via entity references (devices referenced only by legacy entities).
    if legacy_entities:
        for le in legacy_entities:
            if le.serialnumber in discovered:
                continue
            lookup_entry_id = legacy_entry.entry_id if legacy_entry else le.config_entry_id
            referenced = _lookup_device(
                dev_reg,
                LEGACY_DOMAIN,
                le.serialnumber,
                config_entry_id=lookup_entry_id,
            )
            if referenced is not None:
                discovered[le.serialnumber] = _build_legacy_device_info(
                    referenced, le.serialnumber, lookup_entry_id
                )

    return list(discovered.values())


def collect_legacy_entities(
    hass: Any,
    hub_entry: ConfigEntry[Any],
    legacy_entry: ConfigEntry[Any] | None,
    *,
    serialnumbers_filter: set[str] | None = None,
) -> tuple[list[LegacyEntityInfo], list[dict[str, Any]]]:
    """Collect and deterministically map legacy `freeathome` entities onto free@home Local."""
    ent_reg = er.async_get(hass)
    target_by_domain_uid, target_by_uid = _index_target_entities(ent_reg, hub_entry.entry_id)
    candidate_uuids = _candidate_sysap_uuids(hub_entry)
    primary_uuid = candidate_uuids[0]

    mapped: list[LegacyEntityInfo] = []
    skipped: list[dict[str, Any]] = []

    for ent_entry in _iter_entity_entries(ent_reg):
        if getattr(ent_entry, "platform", None) != LEGACY_DOMAIN:
            continue

        ent_cfg_id = getattr(ent_entry, "config_entry_id", None)
        if legacy_entry is not None and ent_cfg_id not in (legacy_entry.entry_id, None):
            continue

        entity_id = str(getattr(ent_entry, "entity_id", ""))
        unique_id = str(getattr(ent_entry, "unique_id", ""))
        parsed = parse_legacy_unique_id(unique_id)
        if parsed is None:
            skipped.append(
                {
                    "entity_id": entity_id,
                    "unique_id": unique_id,
                    "reason": "unrecognized_legacy_unique_id",
                }
            )
            continue

        if (
            serialnumbers_filter is not None
            and parsed.serialnumber.upper() not in serialnumbers_filter
        ):
            continue

        legacy_domain = str(
            getattr(ent_entry, "domain", None)
            or (entity_id.split(".", 1)[0] if "." in entity_id else "sensor")
        )

        target_domain = legacy_domain
        target_unique_id = (
            f"{primary_uuid}/{parsed.serialnumber}/{parsed.channel_id}{parsed.suffix}"
        )
        matched_target = None

        for sysap_uuid in candidate_uuids:
            candidate_uid = f"{sysap_uuid}/{parsed.serialnumber}/{parsed.channel_id}{parsed.suffix}"
            if (legacy_domain, _uid_key(candidate_uid)) in target_by_domain_uid:
                matched_target = target_by_domain_uid[(legacy_domain, _uid_key(candidate_uid))]
                target_domain = legacy_domain
                target_unique_id = str(matched_target.unique_id)
                break

        if matched_target is None:
            for sysap_uuid in candidate_uuids:
                candidate_uid = (
                    f"{sysap_uuid}/{parsed.serialnumber}/{parsed.channel_id}{parsed.suffix}"
                )
                if _uid_key(candidate_uid) in target_by_uid:
                    matched_target = target_by_uid[_uid_key(candidate_uid)]
                    matched_eid = str(getattr(matched_target, "entity_id", ""))
                    target_domain = str(
                        getattr(matched_target, "domain", None)
                        or (matched_eid.split(".", 1)[0] if "." in matched_eid else legacy_domain)
                    )
                    target_unique_id = str(matched_target.unique_id)
                    break

        raw_name = getattr(ent_entry, "name", None)
        raw_icon = getattr(ent_entry, "icon", None)
        raw_area = getattr(ent_entry, "area_id", None)
        raw_labels = getattr(ent_entry, "labels", None) or ()

        mapped.append(
            LegacyEntityInfo(
                entity_id=entity_id,
                unique_id=unique_id,
                serialnumber=parsed.serialnumber,
                channel_id=parsed.channel_id,
                suffix=parsed.suffix,
                legacy_domain=legacy_domain,
                target_domain=target_domain,
                target_unique_id=target_unique_id,
                config_entry_id=ent_cfg_id,
                name=str(raw_name) if isinstance(raw_name, str) and raw_name else None,
                icon=str(raw_icon) if isinstance(raw_icon, str) and raw_icon else None,
                area_id=str(raw_area) if isinstance(raw_area, str) and raw_area else None,
                aliases=_extract_aliases(getattr(ent_entry, "aliases", None)),
                labels={str(lbl) for lbl in raw_labels if lbl},
                disabled_by_user=_is_user_reason(getattr(ent_entry, "disabled_by", None)),
                hidden_by_user=_is_user_reason(getattr(ent_entry, "hidden_by", None)),
                options=_extract_entity_options(getattr(ent_entry, "options", None)),
                domain_changed=legacy_domain != target_domain,
                registry_id=getattr(ent_entry, "id", None),
            )
        )

    return mapped, skipped


def _transfer_device_metadata(
    dev_reg: Any,
    target_dev: Any,
    legacy: LegacyDeviceInfo,
) -> dict[str, Any] | None:
    """Copy device name override, area, and labels onto a free@home Local device entry."""
    kwargs: dict[str, Any] = {}
    if legacy.device_name:
        kwargs["name_by_user"] = legacy.device_name
    if legacy.area_id:
        kwargs["area_id"] = legacy.area_id
    if legacy.labels:
        existing_labels = set(getattr(target_dev, "labels", None) or ())
        kwargs["labels"] = existing_labels | legacy.labels
    if not kwargs:
        return None
    dev_reg.async_update_device(target_dev.id, **kwargs)
    return {
        "serialnumber": legacy.serialnumber,
        "target_device_id": target_dev.id,
        "name_by_user": kwargs.get("name_by_user"),
        "area_id": kwargs.get("area_id"),
        "labels": sorted(kwargs["labels"]) if "labels" in kwargs else [],
    }


def _apply_entity_migration(
    ent_reg: Any,
    target_ent: Any,
    legacy_ent: LegacyEntityInfo,
    *,
    cutover: bool,
    has_conflict: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Copy metadata, options, and optionally `entity_id` onto a free@home Local entity."""
    kwargs: dict[str, Any] = {}
    if legacy_ent.name is not None:
        kwargs["name"] = legacy_ent.name
    if legacy_ent.icon is not None:
        kwargs["icon"] = legacy_ent.icon
    if legacy_ent.area_id is not None:
        kwargs["area_id"] = legacy_ent.area_id
    if legacy_ent.aliases is not None:
        kwargs["aliases"] = legacy_ent.aliases
    if legacy_ent.labels:
        existing_labels = set(getattr(target_ent, "labels", None) or ())
        kwargs["labels"] = existing_labels | legacy_ent.labels
    if legacy_ent.disabled_by_user:
        disabler_cls = getattr(er, "RegistryEntryDisabler", None)
        kwargs["disabled_by"] = getattr(disabler_cls, "USER", "user")
    if legacy_ent.hidden_by_user:
        hider_cls = getattr(er, "RegistryEntryHider", None)
        kwargs["hidden_by"] = getattr(hider_cls, "USER", "user")

    wants_rename = (
        cutover
        and not legacy_ent.domain_changed
        and not has_conflict
        and target_ent.entity_id != legacy_ent.entity_id
    )
    if wants_rename:
        kwargs["new_entity_id"] = legacy_ent.entity_id

    conflict_entry: dict[str, Any] | None = None
    original_target_entity_id = target_ent.entity_id
    final_entity_id = original_target_entity_id

    if kwargs:
        try:
            updated = ent_reg.async_update_entity(original_target_entity_id, **kwargs)
            final_entity_id = (
                getattr(updated, "entity_id", None)
                or kwargs.get("new_entity_id")
                or original_target_entity_id
            )
        except ValueError as err:
            if "new_entity_id" in kwargs:
                conflict_entry = {
                    "entity_id": legacy_ent.entity_id,
                    "target_entity_id": original_target_entity_id,
                    "reason": str(err),
                }
                fallback_kwargs = {k: v for k, v in kwargs.items() if k != "new_entity_id"}
                if fallback_kwargs:
                    updated = ent_reg.async_update_entity(
                        original_target_entity_id, **fallback_kwargs
                    )
                    final_entity_id = (
                        getattr(updated, "entity_id", None) or original_target_entity_id
                    )
            else:
                raise

    if legacy_ent.options:
        for opt_domain, opt_values in legacy_ent.options.items():
            ent_reg.async_update_entity_options(final_entity_id, opt_domain, opt_values)

    return (
        legacy_ent.as_summary(
            cutover=cutover,
            current_target_entity_id=original_target_entity_id,
            target_entity_id=final_entity_id,
        ),
        conflict_entry,
    )


@dataclass
class HelperRebind:
    """A helper config entry whose options reference legacy entities."""

    entry: ConfigEntry[Any]
    # option key -> {legacy reference: replacement}; a reference is an entity ID or a
    # registry ID. Entity IDs stay as they are: the cutover hands them to the new entity.
    replacements: dict[str, dict[str, str]]
    legacy_entity_ids: list[str]
    at_risk: list[str]
    # Legacy entities the helper hid itself (Switch-as-X hides the switch it wraps).
    integration_hidden: list[str] = field(default_factory=list)
    was_loaded: bool = False

    def as_summary(self) -> dict[str, Any]:
        """Return JSON-serializable summary representation."""
        return {
            "config_entry_id": self.entry.entry_id,
            "domain": self.entry.domain,
            "title": self.entry.title,
            "legacy_entity_ids": self.legacy_entity_ids,
        }


def _find_helper_rebinds(
    hass: Any,
    legacy_entities: list[LegacyEntityInfo],
    target_by_domain_uid: dict[tuple[str, str], Any],
    conflicting_eids: set[str],
) -> list[HelperRebind]:
    """Find config entries (helpers such as Switch-as-X, or other integrations) using legacy entities.

    Home Assistant helpers track their source entity in the entity registry, and some
    (Switch-as-X, Statistics, Trend) remove themselves when it is removed. The cutover
    unloads them while it replaces the legacy entities and sets them up again afterwards.
    Only top-level option values (a string or a list of strings) are considered.
    """
    ent_reg = er.async_get(hass)
    by_ref: dict[str, LegacyEntityInfo] = {}
    for legacy_entity in legacy_entities:
        by_ref[legacy_entity.entity_id] = legacy_entity
        if legacy_entity.registry_id:
            by_ref[legacy_entity.registry_id] = legacy_entity

    rebinds: list[HelperRebind] = []
    for entry in hass.config_entries.async_entries():
        if entry.domain in (DOMAIN, LEGACY_DOMAIN):
            continue
        replacements: dict[str, dict[str, str]] = {}
        legacy_ids: list[str] = []
        at_risk: list[str] = []
        hidden: list[str] = []
        for key, value in entry.options.items():
            refs = value if isinstance(value, list) else [value]
            for ref in refs:
                le = by_ref.get(ref) if isinstance(ref, str) else None
                if le is None:
                    continue
                target = target_by_domain_uid.get((le.target_domain, _uid_key(le.target_unique_id)))
                if target is None or le.domain_changed or le.entity_id in conflicting_eids:
                    at_risk.append(le.entity_id)
                    continue
                legacy_ids.append(le.entity_id)
                legacy_reg = ent_reg.async_get(le.entity_id)
                if (
                    legacy_reg is not None
                    and legacy_reg.hidden_by is er.RegistryEntryHider.INTEGRATION
                ):
                    hidden.append(le.entity_id)
                if ref == le.registry_id:
                    replacements.setdefault(key, {})[ref] = str(target.id)
        if legacy_ids or at_risk:
            rebinds.append(
                HelperRebind(
                    entry=entry,
                    replacements=replacements,
                    legacy_entity_ids=sorted(set(legacy_ids)),
                    at_risk=sorted(set(at_risk)),
                    integration_hidden=sorted(set(hidden)),
                )
            )
    return rebinds


async def _async_unload_helpers(hass: Any, rebinds: list[HelperRebind]) -> HelperRebind | None:
    """Unload the loaded helpers; return the first one that cannot be unloaded."""
    for rb in rebinds:
        rb.was_loaded = rb.entry.state is ConfigEntryState.LOADED
        if rb.was_loaded and not await hass.config_entries.async_unload(rb.entry.entry_id):
            return rb
    return None


async def _async_setup_helpers(hass: Any, rebinds: list[HelperRebind], warnings: list[str]) -> None:
    """Set the helpers unloaded for the cutover up again, one by one."""
    for rb in rebinds:
        if not rb.was_loaded:
            continue
        entry = hass.config_entries.async_get_entry(rb.entry.entry_id)
        if entry is None or entry.state is not ConfigEntryState.NOT_LOADED:
            continue
        try:
            loaded = await hass.config_entries.async_setup(entry.entry_id)
        except Exception:  # noqa: BLE001 - one helper must not stop the others
            _LOGGER.exception("Could not set up %s again after the migration", entry.title)
            loaded = False
        if not loaded:
            warnings.append(
                f"Helper '{entry.title}' ({entry.domain}) could not be set up again after "
                "the cutover; check it under Settings > Devices & services."
            )


def _finish_helper_rebinds(ent_reg: Any, rebinds: list[HelperRebind], warnings: list[str]) -> None:
    """Check that the new entities took over the helpers' entity IDs; keep helper-hidden flags."""
    for rb in rebinds:
        for entity_id in rb.legacy_entity_ids:
            entry = ent_reg.async_get(entity_id)
            if entry is None or entry.platform != DOMAIN:
                warnings.append(
                    f"Helper '{rb.entry.title}' ({rb.entry.domain}) uses {entity_id}, which no "
                    "free@home Local entity took over; check the helper."
                )
            elif entity_id in rb.integration_hidden and entry.hidden_by is None:
                ent_reg.async_update_entity(entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION)


def _aborted_result(
    hub_entry: ConfigEntry[Any],
    legacy_entry: ConfigEntry[Any] | None,
    *,
    missing: list[dict[str, Any]],
    skipped_entities: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    """Return the result of a cutover that stopped before changing anything."""
    return {
        "success": False,
        "dry_run": False,
        "cutover": True,
        "hub_entry_id": hub_entry.entry_id,
        "legacy_entry_id": legacy_entry.entry_id if legacy_entry else None,
        "summary": {
            "device_metadata_updates": 0,
            "same_domain_entities_migrated": 0,
            "domain_changed_entities_migrated": 0,
            "missing_target_entities": len(missing),
            "skipped_entities": len(skipped_entities),
            "conflicts": len(conflicts),
            "helper_updates": 0,
            "removed_legacy_entries": 0,
        },
        "device_metadata_updates": [],
        "entity_migrations": [],
        "domain_changed_entities": [],
        "missing_target_entities": missing,
        "skipped_entities": skipped_entities,
        "conflicts": conflicts,
        "helper_updates": [],
        "removed_legacy_entries": [],
        "warnings": warnings,
    }


def _helper_risk_warnings(rebinds: list[HelperRebind]) -> list[str]:
    """Return a warning per helper that uses legacy entities without a counterpart."""
    return [
        f"Helper '{rb.entry.title}' ({rb.entry.domain}) uses {', '.join(rb.at_risk)}, which "
        "has no matching free@home Local entity to take over; Home Assistant may remove "
        "or unlink the helper when the freeathome entity is removed."
        for rb in rebinds
        if rb.at_risk
    ]


def _rebind_options(rebind: HelperRebind) -> dict[str, Any]:
    """Return the helper's options with legacy registry IDs replaced."""
    options = dict(rebind.entry.options)
    for key, mapping in rebind.replacements.items():
        value = options[key]
        if isinstance(value, list):
            options[key] = [mapping.get(item, item) for item in value]
        else:
            options[key] = mapping.get(value, value)
    return options


async def async_migrate_from_legacy(
    hass: Any,
    hub_entry: ConfigEntry[Any],
    *,
    dry_run: bool = True,
    cutover: bool = False,
    serialnumbers_filter: set[str] | None = None,
) -> dict[str, Any]:
    """Preview or execute migration from legacy `freeathome` to `freeathome_local`."""
    runtime: FreeAtHomeLocalRuntime | None = getattr(hub_entry, "runtime_data", None)
    if runtime is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"entry_id": hub_entry.entry_id},
        )

    filter_serials = (
        {s.strip().upper() for s in serialnumbers_filter if s.strip()}
        if serialnumbers_filter
        else None
    )
    if not dry_run and cutover and filter_serials:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="partial_cutover_not_supported"
        )

    legacy_entries = _legacy_config_entries(hass)
    legacy_entry = find_matching_legacy_entry(hass, hub_entry)
    warnings: list[str] = []

    if len(legacy_entries) > 1 and legacy_entry is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="legacy_entry_ambiguous"
        )

    legacy_entities, skipped_entities = collect_legacy_entities(
        hass,
        hub_entry,
        legacy_entry,
        serialnumbers_filter=filter_serials,
    )
    legacy_devices = discover_legacy_devices(
        hass,
        legacy_entry,
        legacy_entities,
        serialnumbers_filter=filter_serials,
    )

    if filter_serials is not None:
        found_serials = {d.serialnumber.upper() for d in legacy_devices} | {
            e.serialnumber.upper() for e in legacy_entities
        }
        missing_filter = sorted(filter_serials - found_serials)
        if missing_filter:
            warnings.append(
                f"Requested serial numbers not found in freeathome: {', '.join(missing_filter)}"
            )

    merged_opts = {**hub_entry.data, **hub_entry.options}
    name_prefix = str(merged_opts.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX))
    if cutover and name_prefix:
        warnings.append(
            f"Hub currently has name_prefix='{name_prefix}'. Clear it in Hub Options "
            "after cutover if you no longer want prefixed entity names."
        )

    target_switch_as_x = bool(merged_opts.get(CONF_SWITCH_AS_X, DEFAULT_SWITCH_AS_X))
    if legacy_entry is not None and CONF_SWITCH_AS_X in legacy_entry.data:
        leg_switch_as_x = bool(legacy_entry.data[CONF_SWITCH_AS_X])
        if leg_switch_as_x != target_switch_as_x:
            warnings.append(
                f"switch_as_x mismatch detected (freeathome={leg_switch_as_x}, "
                f"freeathome_local={target_switch_as_x}). Switching actuators changed domain "
                "between light and switch and cannot retain same-domain Recorder history."
            )

    if any(ent.domain_changed for ent in legacy_entities):
        warnings.append(
            "Some entities changed domain between freeathome and freeathome_local "
            "(for example light <-> switch due to switch_as_x); metadata and Assist "
            "options are copied, while cross-domain entity_id renaming is skipped."
        )

    if cutover:
        warnings.append(
            "Update automations using freeathome_event to freeathome_local_event, "
            "freeathome.dump/monitor to freeathome_local.dump_config/monitor, and "
            "freeathome.cover_force_position/thermostat_temperature_correction to the "
            "forced position select and temperature correction number entities."
        )

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    existing_by_eid = {str(e.entity_id): e for e in _iter_entity_entries(ent_reg)}
    target_by_domain_uid, _ = _index_target_entities(ent_reg, hub_entry.entry_id)

    conflicts: list[dict[str, Any]] = []
    conflicting_eids: set[str] = set()
    for le in legacy_entities:
        if cutover and not le.domain_changed:
            holder = existing_by_eid.get(le.entity_id)
            if holder is not None and getattr(holder, "platform", None) not in (
                LEGACY_DOMAIN,
                DOMAIN,
            ):
                conflicts.append(
                    {
                        "entity_id": le.entity_id,
                        "reason": "held_by_other_integration",
                        "holder_platform": getattr(holder, "platform", None),
                    }
                )
                conflicting_eids.add(le.entity_id)

    rebinds = (
        _find_helper_rebinds(hass, legacy_entities, target_by_domain_uid, conflicting_eids)
        if cutover
        else []
    )
    warnings.extend(_helper_risk_warnings(rebinds))
    helper_rebinds = [rb for rb in rebinds if rb.legacy_entity_ids]

    if dry_run:
        device_updates = [
            dev.as_summary()
            for dev in legacy_devices
            if dev.device_name or dev.area_id or dev.labels
        ]
        same_domain_plan: list[dict[str, Any]] = []
        changed_domain_plan: list[dict[str, Any]] = []
        missing_target_plan: list[dict[str, Any]] = []

        for le in legacy_entities:
            target_ent = target_by_domain_uid.get((le.target_domain, _uid_key(le.target_unique_id)))
            if target_ent is None:
                missing_target_plan.append(
                    {
                        "legacy_entity_id": le.entity_id,
                        "target_domain": le.target_domain,
                        "target_unique_id": le.target_unique_id,
                        "reason": "target_entity_not_created",
                    }
                )
            current_target_eid = target_ent.entity_id if target_ent is not None else None
            planned_target = (
                le.entity_id
                if (
                    cutover
                    and target_ent is not None
                    and not le.domain_changed
                    and le.entity_id not in conflicting_eids
                )
                else current_target_eid
            )
            row = le.as_summary(
                cutover=cutover,
                current_target_entity_id=current_target_eid,
                target_entity_id=planned_target,
            )
            if le.domain_changed:
                changed_domain_plan.append(row)
            else:
                same_domain_plan.append(row)

        legacy_entries_to_remove = (
            [
                {
                    "entry_id": legacy_entry.entry_id,
                    "title": getattr(legacy_entry, "title", LEGACY_DOMAIN),
                    "unique_id": getattr(legacy_entry, "unique_id", None),
                }
            ]
            if cutover and legacy_entry is not None
            else []
        )

        return {
            "success": True,
            "dry_run": True,
            "cutover": cutover,
            "hub_entry_id": hub_entry.entry_id,
            "legacy_entry_id": legacy_entry.entry_id if legacy_entry else None,
            "summary": {
                "discovered_legacy_devices": len(legacy_devices),
                "discovered_legacy_entities": len(legacy_entities),
                "device_metadata_updates": len(device_updates),
                "same_domain_entities": len(same_domain_plan),
                "domain_changed_entities": len(changed_domain_plan),
                "missing_target_entities": len(missing_target_plan),
                "skipped_entities": len(skipped_entities),
                "conflicts": len(conflicts),
                "helper_updates": len(helper_rebinds),
                "legacy_entries_to_remove": len(legacy_entries_to_remove),
            },
            "device_metadata_updates": device_updates,
            "entity_migrations": same_domain_plan,
            "domain_changed_entities": changed_domain_plan,
            "missing_target_entities": missing_target_plan,
            "skipped_entities": skipped_entities,
            "conflicts": conflicts,
            "helper_updates": [rb.as_summary() for rb in helper_rebinds],
            "legacy_entries_to_remove": legacy_entries_to_remove,
            "warnings": warnings,
        }

    # --- Execution mode (`dry_run=False`) ---
    matched_target_count = sum(
        1
        for le in legacy_entities
        if target_by_domain_uid.get((le.target_domain, _uid_key(le.target_unique_id))) is not None
    )
    if cutover and matched_target_count == 0 and (legacy_entry is not None or legacy_entities):
        warnings.append(
            "Cutover aborted before removing freeathome: zero matching "
            "freeathome_local entities were found on this hub."
        )
        missing_all = [
            {
                "legacy_entity_id": le.entity_id,
                "target_domain": le.target_domain,
                "target_unique_id": le.target_unique_id,
                "reason": "target_entity_not_created",
            }
            for le in legacy_entities
        ]
        return _aborted_result(
            hub_entry,
            legacy_entry,
            missing=missing_all,
            skipped_entities=skipped_entities,
            conflicts=conflicts,
            warnings=warnings,
        )

    if cutover:
        # Helpers track their source in the entity registry; unload them so removing the
        # legacy entities cannot make them remove or unlink themselves. Stop before any
        # change if one of them cannot be unloaded.
        failed = await _async_unload_helpers(hass, helper_rebinds)
        if failed is not None:
            await _async_setup_helpers(hass, helper_rebinds, warnings)
            warnings.append(
                "Cutover aborted before removing freeathome: the config entry "
                f"'{failed.entry.title}' ({failed.entry.domain}) uses a freeathome entity and "
                "could not be unloaded. Disable it or restart Home Assistant, then try again."
            )
            return _aborted_result(
                hub_entry,
                legacy_entry,
                missing=[],
                skipped_entities=skipped_entities,
                conflicts=conflicts,
                warnings=warnings,
            )

    removed_legacy_entries: list[dict[str, Any]] = []
    device_metadata_updates: list[dict[str, Any]] = []
    migrated_same_domain: list[dict[str, Any]] = []
    migrated_changed_domain: list[dict[str, Any]] = []
    missing_target_entities: list[dict[str, Any]] = []

    try:
        runtime.suppress_reload = True

        if cutover:
            if legacy_entry is not None:
                await hass.config_entries.async_remove(legacy_entry.entry_id)
                removed_legacy_entries.append(
                    {
                        "entry_id": legacy_entry.entry_id,
                        "title": getattr(legacy_entry, "title", LEGACY_DOMAIN),
                        "unique_id": getattr(legacy_entry, "unique_id", None),
                    }
                )

            # Remove any orphaned/YAML legacy entities holding target same-domain entity_ids.
            post_remove_by_eid = {str(e.entity_id): e for e in _iter_entity_entries(ent_reg)}
            for le in legacy_entities:
                if le.domain_changed:
                    continue
                holder = post_remove_by_eid.get(le.entity_id)
                if holder is not None and getattr(holder, "platform", None) == LEGACY_DOMAIN:
                    ent_reg.async_remove(le.entity_id)

            # Only now, with the legacy entities gone, point registry-ID references at the
            # new entities: an update listener reloading the helper early finds nothing old.
            for rb in helper_rebinds:
                if rb.replacements:
                    hass.config_entries.async_update_entry(rb.entry, options=_rebind_options(rb))

        candidate_uuids = _candidate_sysap_uuids(hub_entry)
        for dev in legacy_devices:
            target_dev = None
            for sysap_uuid in candidate_uuids:
                target_dev = _lookup_device(
                    dev_reg,
                    DOMAIN,
                    f"{sysap_uuid}_{dev.serialnumber}",
                    config_entry_id=hub_entry.entry_id,
                )
                if target_dev is not None:
                    break
            if target_dev is not None:
                updated_dev = _transfer_device_metadata(dev_reg, target_dev, dev)
                if updated_dev is not None:
                    device_metadata_updates.append(updated_dev)

        target_by_domain_uid, _ = _index_target_entities(ent_reg, hub_entry.entry_id)
        for le in legacy_entities:
            target_ent = target_by_domain_uid.get((le.target_domain, _uid_key(le.target_unique_id)))
            if target_ent is None:
                missing_target_entities.append(
                    {
                        "legacy_entity_id": le.entity_id,
                        "target_domain": le.target_domain,
                        "target_unique_id": le.target_unique_id,
                        "reason": "target_entity_not_created",
                    }
                )
                continue

            row, conflict_entry = _apply_entity_migration(
                ent_reg,
                target_ent,
                le,
                cutover=cutover,
                has_conflict=le.entity_id in conflicting_eids,
            )
            if conflict_entry is not None:
                conflicts.append(conflict_entry)
            if le.domain_changed:
                migrated_changed_domain.append(row)
            else:
                migrated_same_domain.append(row)

        _finish_helper_rebinds(ent_reg, helper_rebinds, warnings)
    finally:
        runtime.suppress_reload = False
        # Set the helpers up again: their entity IDs now belong to the new entities.
        await _async_setup_helpers(hass, helper_rebinds, warnings)

    return {
        "success": True,
        "dry_run": False,
        "cutover": cutover,
        "hub_entry_id": hub_entry.entry_id,
        "legacy_entry_id": legacy_entry.entry_id if legacy_entry else None,
        "summary": {
            "device_metadata_updates": len(device_metadata_updates),
            "same_domain_entities_migrated": len(migrated_same_domain),
            "domain_changed_entities_migrated": len(migrated_changed_domain),
            "missing_target_entities": len(missing_target_entities),
            "skipped_entities": len(skipped_entities),
            "conflicts": len(conflicts),
            "helper_updates": len(helper_rebinds),
            "removed_legacy_entries": len(removed_legacy_entries),
        },
        "device_metadata_updates": device_metadata_updates,
        "entity_migrations": migrated_same_domain,
        "domain_changed_entities": migrated_changed_domain,
        "missing_target_entities": missing_target_entities,
        "skipped_entities": skipped_entities,
        "conflicts": conflicts,
        "helper_updates": [rb.as_summary() for rb in helper_rebinds],
        "removed_legacy_entries": removed_legacy_entries,
        "warnings": warnings,
    }
