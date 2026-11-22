# Switching from `freeathome` to free@home Local

You don't have to switch: free@home Local and the `freeathome` integration work with the same System Access Point and can run side by side for as long as you like. If you decide to switch, this guide shows how free@home Local (`freeathome_local`) takes over what you have set up: **device names, areas, labels, entity names, icons, aliases, voice assistant settings, entity IDs with their Recorder history and long-term statistics, and helpers such as Switch-as-X**, so dashboards and automations keep working.

---

## 1. Running both side by side

Installing free@home Local changes nothing in an existing `freeathome` setup:

- **Own domain and folder:** `freeathome_local` in `custom_components/freeathome_local/`.
- **Own devices:** device identifiers `("freeathome_local", "{sysap_uuid}_{serialnumber}")` below a separate System Access Point device (`("freeathome_local", "hub_{entry_id}")`).
- **Own entities:** unique IDs scoped to `freeathome_local`, in the form `{sysap_uuid}/{serialnumber}/{channel_id}`.
- **Own events and actions:** `freeathome_local_event`, `freeathome_local_scene_triggered`, `freeathome_local_virtual_device_command` and `freeathome_local.*`; the events and actions of `freeathome` are never used.
- **Own connection:** the Local REST & WebSocket API of the System Access Point (`/fhapi/v1/api`).
- **Optional name prefix:** set `name_prefix` (for example `Local `) during setup or in the options to tell both sets of entities apart in dashboards and entity pickers.

---

## 2. Before you start

1. **Home Assistant version:** `2026.9.0` or newer.
2. **Create a backup:** **Settings → System → Backups → Create backup** before you run the takeover with `cutover: true`.
3. **Install and set up free@home Local:**
   - Install **free@home Local** via **Settings → Marketplace** (HA 2026.11+) or **HACS** (HA 2026.9–2026.10) and restart Home Assistant.
   - Add your System Access Point under **Settings → Devices & Services → Add Integration → free@home Local**.
   - When the `freeathome` integration is installed, the setup pre-fills `host` and `switch_as_x` from its entry, so switch actuators end up in the same domain (`light` or `switch`). Its room-name setting has no counterpart: free@home rooms become Home Assistant areas. Check that `switch_as_x` matches before the takeover.
4. **While you try it:** set `name_prefix` to, for example, `Local ` and clear it again after the takeover.

> [!IMPORTANT]
> **Keep `freeathome` installed until the takeover is done.**
> free@home Local reads its config entry, devices and entities directly from Home Assistant, so don't remove it beforehand.

---

## 3. What is taken over

| Item | Side by side (`cutover: false`) | Takeover (`cutover: true`) |
|---|---|---|
| **Device name (`name_by_user`), area and labels** | Copied to the free@home Local devices | Copied to the free@home Local devices |
| **Entity name, icon, area, aliases, labels** | Copied to the free@home Local entities | Copied to the free@home Local entities |
| **Disabled and hidden state** | Copied when you set it (defaults are left alone) | Copied when you set it (defaults are left alone) |
| **Assist, Google and Alexa exposure, display precision** | Copied to the free@home Local entities | Copied to the free@home Local entities |
| **`entity_id`, Recorder history and long-term statistics** | `freeathome` keeps its entity IDs (both run in parallel) | **The `freeathome` entry is removed and free@home Local takes over the exact entity IDs** |
| **Helpers on `freeathome` entities (Switch-as-X, Threshold, Utility Meter, ...)** | Stay linked to the `freeathome` entities | **Kept and linked to the free@home Local entities** (listed under `helper_updates`) |

### Why history and helpers stay intact

In Home Assistant, Recorder history, long-term statistics, dashboards and automations are bound to the **`entity_id`**. free@home Local maps every unique ID of the `freeathome` integration to its own entity (hardware channels `<serial>/chXXXX`, multi-sensor datapoints `<serial>/chXXXX/odpXXXX`, dimming status `<serial>/chXXXX/dimming_status`, thermostat temperatures `<serial>/chXXXX/current_temperature`, and scenes or virtual devices with a System Access Point prefix `<sysap_id>/FFFF.../chXXXX`) and then takes over the original entity IDs, so your history continues without a gap. Unique IDs are matched regardless of case (`ch001A` and `ch001a` are the same channel).

Helpers created in the UI (Switch-as-X, Threshold, Utility Meter, Min/Max, ...) also track their source in the entity registry, and some of them (Switch-as-X, Statistics, Trend) remove themselves when their source entity is removed. The takeover therefore unloads every config entry whose options reference a `freeathome` entity (helpers, but also other integrations that store entity IDs in their options), replaces the entities, points registry-ID references at the new entity and sets the entries up again; the dry run lists them under `helper_updates`. The switch a Switch-as-X helper wraps stays hidden. If one of these entries cannot be unloaded, the takeover stops before changing anything and names it in `warnings`. An entry that uses an entity without a free@home Local counterpart is named in `warnings` too, because Home Assistant may remove or unlink it.

- **About `switch_as_x`:** if one integration shows switch actuators as `switch.*` and the other as `light.*`, those entities change domain (`domain_changed_entities`). Home Assistant cannot rename `switch.*` to `light.*`; names, areas and voice assistant settings are still copied, but the entity ID is not taken over for them.

---

## 4. Step by step (`freeathome_local.migrate_from_legacy`)

Open **Developer Tools → Actions** and run `freeathome_local.migrate_from_legacy` in up to three steps.

### Step 1: Preview (`dry_run: true`)

A dry run changes nothing; it shows exactly what would happen:

```yaml
action: freeathome_local.migrate_from_legacy
data:
  dry_run: true
  cutover: true
```

*(With several System Access Points, also pass `config_entry_id`: pick the System Access Point in the action editor.)*

What the response tells you:
- **`summary`:** how many devices and entities were found, device updates, entities that keep their history (`history_preserved: true`), `domain_changed_entities`, `missing_target_entities` (entities without a free@home Local counterpart), `conflicts`, `helper_updates`, and the entry that will be removed.
- **`entity_migrations`:** every `freeathome` entity with its free@home Local counterpart, and whether it keeps its entity ID (`will_rename_entity_id`, `history_preserved`).
- **`conflicts`:** entity IDs held by a third integration (neither `freeathome` nor free@home Local). Settings are still copied, without taking over that ID.
- **`helper_updates`:** config entries (helpers and other integrations) that use `freeathome` entities and are kept across the takeover; they are briefly unloaded during it.
- **`warnings`:** different `switch_as_x` settings, an active `name_prefix`, helpers at risk, and events or actions to update afterwards.

### Step 2 (optional): copy settings while both run (`cutover: false`)

Copies device names, areas, labels, entity names, icons, aliases and voice assistant settings, and leaves `freeathome` running:

```yaml
action: freeathome_local.migrate_from_legacy
data:
  dry_run: false
  cutover: false
```

### Step 3: take over (`dry_run: false`, `cutover: true`)

When you are ready to switch for good and take over the entity IDs and their history:

```yaml
action: freeathome_local.migrate_from_legacy
data:
  dry_run: false
  cutover: true
```

**What happens:**
1. Checks that matching free@home Local entities exist; without any match it stops and removes nothing.
2. Pauses reloads while the registries are updated, and unloads helpers that use `freeathome` entities.
3. Removes the `freeathome` config entry (and leftover entity registry entries), which frees the original entity IDs; the Recorder history stays.
4. Copies device names (`name_by_user`), areas and labels to the free@home Local devices.
5. Copies entity settings (`name`, `icon`, `area_id`, `aliases`, `labels`, disabled and hidden state you set), gives the free@home Local entities the original entity IDs, and then applies the entity options (Assist, Google and Alexa exposure, display precision).
6. Sets the unloaded helpers up again; they now use the free@home Local entities.

---

## 5. Afterwards

1. **Clear `name_prefix`** if you used it: **Settings → Devices & Services → free@home Local → Configure**.
2. **Update events and actions in automations and scripts:**
   - Replace the event `freeathome_event` with **`freeathome_local_event`** (the `unique_id` in the event data starts with `{sysap_uuid}/...`, in case an automation filters on `event_data.unique_id`).
   - Replace actions of the `freeathome` integration:
     - `freeathome.cover_force_position` → `select.select_option` on the cover's **Forced position** select
     - `freeathome.thermostat_temperature_correction` → `number.set_value` on the thermostat's **Temperature correction** number
     - `freeathome.dump` → `freeathome_local.dump_config`
     - `freeathome.monitor` → `freeathome_local.monitor`
3. **Restart Home Assistant and check:**
   - Restart Home Assistant (**Settings → System → Restart**).
   - Look at the history of a few thermostats, power or valve sensors and utility meters across the time of the takeover.
   - Check **Settings → System → Logs** and **Settings → Repairs**.
4. **Uninstall `freeathome`** when you are happy: remove it in **Settings → Marketplace** (or **HACS**), remove a `freeathome:` block from `configuration.yaml` if you have one, and restart Home Assistant.

---

## 6. Selected devices and questions

### Copying settings for selected devices (`serialnumbers`)

The `freeathome` integration uses **one config entry for the whole System Access Point**, so a takeover always covers all of its devices. A preview or copying settings (`cutover: false`) also works for selected serial numbers:

```yaml
action: freeathome_local.migrate_from_legacy
data:
  dry_run: false
  cutover: false
  serialnumbers: "ABB700DA1DDF, ABB700DB3F2C"
```

### Questions

- **Why does `cutover: true` reject `serialnumbers`?**
  Removing the `freeathome` config entry removes all its entities on that System Access Point at once. A partial takeover would leave the remaining entities removed without a counterpart, so free@home Local does not allow it.
- **I see a `switch_as_x mismatch detected` warning.**
  Set **Expose switch actuators as switches (instead of lights)** in the free@home Local options to match `freeathome` before `cutover: true`, if switch actuators should keep their exact `switch.*` or `light.*` entity IDs and history.
- **An entity ID is listed under `conflicts`.**
  Another integration (for example a helper) holds that exact entity ID. Rename or remove that entity if free@home Local should take it over.
