"""The add-on's values as real Home Assistant entities, over MQTT discovery.

This is the add-on's one way of creating entities. Each value becomes a sensor
with a unique_id under one "E-Paper Studio" device, so people can rename it,
give it an area and use it in automations; it survives Home Assistant
restarts; and it shows as unavailable when the add-on is stopped instead of
freezing on its last value.

The panel does not depend on any of this: pages read the add-on's own values
directly (`binding.local_value`). Without a broker, everything still renders;
the values just are not mirrored into Home Assistant.

Topics
  homeassistant/<component>/epaper_panel/<object_id>/config   discovery
  epaper_panel/<object_id>/state, .../attributes               values
  epaper_panel/status                                          online/offline (last will)
  epaper_panel/refresh/press                                   the first screen's Refresh button
  epaper_panel/refresh_<suffix>/press                          each other screen's

Discovery topics and unique_ids are the ones 0.8.x used, so entities people
already have carry over with their settings.
"""
from __future__ import annotations

import health
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

from hass import Hass, HassError

DISCOVERY_PREFIX = "homeassistant"
NODE = "epaper_panel"
BASE = "epaper_panel"
AVAILABILITY = f"{BASE}/status"
BUTTON_COMMAND = f"{BASE}/refresh/press"
BUTTON_COMMANDS = f"{BASE}/+/press"
BUTTON_TOPIC = re.compile(rf"^{BASE}/refresh(_[a-z0-9_]+)?/press$")
BIRTH_TOPIC = f"{DISCOVERY_PREFIX}/status"
UID_PREFIX = "epaper_studio_"
BUTTON_UID = "epaper_panel_refresh_button"

# An entity not refreshed for this long, and no longer wanted by anything in
# the configuration (see keep()), is gone and is withdrawn from Home
# Assistant. Never sooner after a start, so a restart cannot withdraw anything.
# A configured source that is failing is still wanted: failing is not gone.
STALE_AFTER = 3600.0

# The add-on's problem sensors (one per outside service, see health.py) are
# binary sensors; everything else is a sensor.
PROBLEM_PREFIX = "epaper_problem_"

# A page's "is it on" sensor (notify.py): a binary sensor made only when someone
# asks to be notified about that page. Keyed by the page's notify id, so renaming
# the page never changes its unique_id; its entity ID is given by the attributes.
SIGNAL_PREFIX = "epaper_page_"

# What the add-on before 0.8.27 left retained and no longer owns: a "Last render" sensor
# on a topic of its own, whose naive timestamp Home Assistant refuses at every start.
# Its replacement is sensor.epaper_panel_last_render. Cleared at every connect.
LEGACY_TOPICS = (f"{DISCOVERY_PREFIX}/sensor/{NODE}/last_render/config",
                 f"{DISCOVERY_PREFIX}/{NODE}/last_render")

# Attributes that are entity metadata, not data.
META_ATTRS = ("friendly_name", "icon", "unit_of_measurement", "device_class", "source", "default_entity_id")


def with_zone(state: str) -> str:
    """A timestamp Home Assistant takes: one without a time zone is the add-on's local time."""
    try:
        dt = datetime.fromisoformat(state)
    except ValueError:
        return state
    return state if dt.tzinfo else dt.astimezone().isoformat(timespec="seconds")


def object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1]


def component_of(obj: str) -> str:
    return "binary_sensor" if obj.startswith((PROBLEM_PREFIX, SIGNAL_PREFIX)) else "sensor"


def entity_name(attrs: dict, obj: str) -> str:
    name = str(attrs.get("friendly_name") or obj.replace("_", " ").capitalize())
    return re.sub(r"^E-?Paper\s*·\s*", "", name, flags=re.I).strip() or obj


class EntityPublisher:
    def __init__(self, transport, hass: Hass, data_dir: Path, version: str, on_button=None,
                 clock=time.time, buttons=lambda: [("", "")]):
        """`buttons`: (entity suffix, screen name) for each screen's Refresh button; the
        first screen's suffix is "". `on_button(suffix)` runs when one is pressed."""
        self.transport = transport
        self.hass = hass
        self.version = version
        self.on_button = on_button
        self.buttons = buttons
        self._announced_buttons: dict[str, str] = {}
        self._clock = clock
        self._started = clock()
        self._state_path = Path(data_dir) / "mqtt_entities.json"
        self._migrations_path = Path(data_dir) / "migrations.json"

        self.desired: dict[str, dict] = {}            # object_id -> {state, attrs}
        self._sent_config: dict[str, str] = {}        # object_id -> discovery payload sent this connection
        self._sent_state: dict[str, tuple] = {}       # object_id -> (state, attrs json)
        self._registered: dict[str, str] = {}         # our unique_id -> entity_id, from the registry
        self._all_registered: set[str] = set()        # every registered entity_id
        self._registry_ok = False
        self._ready = False
        self._ready_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._sync_task: asyncio.Task | None = None
        self._sync_again = False
        self._kept: set[str] = set()                  # object_ids the configuration still wants
        self._pulse: set[str] = set()                 # signals that fired again while on: off, then on
        self.last_seen: dict[str, float] = self._load(self._state_path)
        self.problem = "" if transport is not None else (
            "No MQTT broker, so these values aren't in Home Assistant. "
            "Install the Mosquitto broker app to add them. The panel works either way.")

    # ------------------------------------------------------------------ public
    @property
    def mode(self) -> str:
        if self.transport is None:
            return "off"
        return "connected" if self.transport.connected and self._ready else "connecting"

    def set(self, entity_id: str, state, attrs: dict | None) -> None:
        obj = object_id(entity_id)
        if state is not None and (attrs or {}).get("device_class") == "timestamp":
            state = with_zone(str(state))
        # "None" is how an MQTT sensor is told its value is unknown.
        self.desired[obj] = {"state": "None" if state is None else str(state)[:255], "attrs": dict(attrs or {})}
        self.last_seen[obj] = self._clock()

    def set_problem(self, slug: str, name: str, on: bool, attrs: dict) -> None:
        """A service's problem sensor: on while it has been failing (health.py)."""
        obj = f"{PROBLEM_PREFIX}{slug}"
        self.desired[obj] = {"state": "ON" if on else "OFF",
                             "attrs": {"friendly_name": name, "device_class": "problem", **attrs}}
        self.last_seen[obj] = self._clock()

    def set_signal(self, key: str, on: bool, attrs: dict) -> None:
        """A page's on/off sensor (notify.py). One that fires again while it's on (a change
        alert held by the last change) goes off and on again, so "turns on" means "fired"."""
        obj = f"{SIGNAL_PREFIX}{key}"
        state = "ON" if on else "OFF"
        was = self.desired.get(obj)
        if on and was and was["state"] == "ON" and was["attrs"].get("fired_at") != attrs.get("fired_at"):
            self._pulse.add(obj)
        self.desired[obj] = {"state": state, "attrs": dict(attrs)}
        self.last_seen[obj] = self._clock()

    def entity_of(self, obj: str) -> str | None:
        """The entity ID Home Assistant gave one of ours, as far as this connection knows."""
        return self._registered.get(f"{UID_PREFIX}{obj}")

    def keep(self, entity_ids) -> None:
        """Entities the configuration still produces, answering or not: never withdrawn."""
        self._kept = {object_id(e) if "." in e else e for e in entity_ids}
        now = self._clock()
        for obj in self._kept:
            if obj in self.last_seen and self.last_seen[obj] != 0.0:
                self.last_seen[obj] = now

    def retire(self, entity_id: str) -> None:
        """Withdraw an entity now (used for values the add-on no longer offers)."""
        obj = object_id(entity_id)
        self.desired.pop(obj, None)
        self.last_seen[obj] = 0.0

    async def run(self):
        if self.transport is None:
            return
        await self.transport.run(self._on_connect, self._on_message)

    async def sync(self) -> None:
        if self.transport is None or not self.transport.connected or not self._ready:
            return
        async with self._lock:
            now = self._clock()
            await self._announce_button()                  # screens come and go
            for obj, want in list(self.desired.items()):
                await self._announce(obj, want)
                await self._send_state(obj, want)
            if now - self._started >= STALE_AFTER:
                for obj, seen in list(self.last_seen.items()):
                    if now - seen >= STALE_AFTER and (seen == 0.0 or obj not in self._kept):
                        await self._withdraw(obj)
            else:
                for obj, seen in list(self.last_seen.items()):
                    if seen == 0.0:                     # explicitly retired
                        await self._withdraw(obj)
            self._save(self._state_path, self.last_seen)

    def request_sync(self) -> None:
        """Mirror the values in the background: a render never waits on the broker, which can
        accept a connection and then stall (each publish waits for its acknowledgement). One
        pass at a time; asked again while one runs, it runs once more after it."""
        if self.transport is None:
            return
        if self._sync_task is not None and not self._sync_task.done():
            self._sync_again = True
            return
        self._sync_task = asyncio.create_task(self._sync_in_background())

    async def _sync_in_background(self) -> None:
        while True:
            self._sync_again = False
            try:
                await self.sync()
            except Exception as exc:
                print(f"mqtt sync failed: {health.describe(exc)}", flush=True)
            if not self._sync_again:
                return

    async def wait_ready(self, timeout: float) -> bool:
        """Wait until the entities are online in Home Assistant again.

        While the add-on is stopped its entities read "unavailable". Rendering
        before they are back would hide every page whose condition reads one.
        """
        if self.transport is None:
            return True
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            print(f"mqtt: not connected after {int(timeout)}s; rendering anyway", flush=True)
            return False

    def status(self) -> dict:
        return {"mode": self.mode, "problem": self.problem, "entities": len(self.desired)}

    # ------------------------------------------------------------------ connection
    async def _on_connect(self):
        self._sent_config.clear()
        self._sent_state.clear()
        self._ready = False
        await self.transport.subscribe(BIRTH_TOPIC)
        await self.transport.subscribe(BUTTON_COMMANDS)
        await self.transport.publish(AVAILABILITY, "online")
        await self._load_registry()
        await self._migrate_once()
        for topic in LEGACY_TOPICS:
            await self.transport.publish(topic, "")
        if self._registry_ok:
            # A retired value Home Assistant no longer has needs no withdrawing.
            for obj, seen in list(self.last_seen.items()):
                if seen == 0.0 and f"{UID_PREFIX}{obj}" not in self._registered \
                        and f"{component_of(obj)}.{obj}" not in self._all_registered:
                    self.last_seen.pop(obj)
        await self._announce_button()
        self._ready = True
        self.problem = ""
        print("mqtt: connected, publishing entities", flush=True)
        await self.sync()
        self._ready_event.set()

    async def _on_message(self, topic: str, payload: bytes):
        text = payload.decode("utf-8", "ignore").strip() if payload else ""
        if topic == BIRTH_TOPIC and text == "online":
            # Home Assistant restarted: announce everything again.
            self._sent_config.clear()
            self._sent_state.clear()
            await self._announce_button(force=True)
            await self.sync()
        elif self.on_button is not None and (m := BUTTON_TOPIC.match(topic)):
            await self.on_button(m.group(1) or "")

    # ------------------------------------------------------------------ entities
    def _config(self, obj: str, attrs: dict) -> dict:
        component = component_of(obj)
        cfg = {
            "name": entity_name(attrs, obj),
            "unique_id": f"{UID_PREFIX}{obj}",
            "default_entity_id": attrs.get("default_entity_id") or f"{component}.{obj}",
            "state_topic": f"{BASE}/{obj}/state",
            "json_attributes_topic": f"{BASE}/{obj}/attributes",
            "availability_topic": AVAILABILITY,
            "device": self._device(),
            "origin": {"name": "E-paper panel add-on", "sw_version": self.version},
        }
        for src, dst in (("icon", "icon"), ("device_class", "device_class"),
                         ("unit_of_measurement", "unit_of_measurement")):
            if attrs.get(src):
                cfg[dst] = attrs[src]
        if obj.startswith(PROBLEM_PREFIX):
            cfg["entity_category"] = "diagnostic"
        return cfg

    def _device(self) -> dict:
        return {"identifiers": ["epaper_panel_hub"], "name": "E-Paper Studio",
                "manufacturer": "E-paper panel add-on", "model": "Home Assistant app",
                "sw_version": self.version}

    async def _announce(self, obj: str, want: dict):
        payload = json.dumps(self._config(obj, want["attrs"]), sort_keys=True)
        if self._sent_config.get(obj) == payload:
            return
        await self._clear_unregistered_state(obj)
        component = component_of(obj)
        if await self.transport.publish(f"{DISCOVERY_PREFIX}/{component}/{NODE}/{obj}/config", payload):
            self._sent_config[obj] = payload
            self._sent_state.pop(obj, None)
            # From here on Home Assistant owns this ID: never clear its state again.
            eid = json.loads(payload)["default_entity_id"]
            self._registered.setdefault(f"{UID_PREFIX}{obj}", eid)
            self._all_registered.add(eid)

    async def _send_state(self, obj: str, want: dict):
        attrs = {k: v for k, v in want["attrs"].items() if k not in META_ATTRS}
        attrs_json = json.dumps(attrs, sort_keys=True, default=str)
        key = (want["state"], attrs_json)
        if obj in self._pulse:
            self._pulse.discard(obj)
            if (self._sent_state.get(obj) or ("",))[0] == "ON" and want["state"] == "ON":
                await self.transport.publish(f"{BASE}/{obj}/state", "OFF")
                self._sent_state.pop(obj, None)
        if self._sent_state.get(obj) == key:
            return
        ok_a = await self.transport.publish(f"{BASE}/{obj}/attributes", attrs_json)
        ok_s = await self.transport.publish(f"{BASE}/{obj}/state", want["state"])
        if ok_a and ok_s:
            self._sent_state[obj] = key

    async def _withdraw(self, obj: str):
        component = component_of(obj)
        for topic in (f"{DISCOVERY_PREFIX}/{component}/{NODE}/{obj}/config",
                      f"{BASE}/{obj}/state", f"{BASE}/{obj}/attributes"):
            await self.transport.publish(topic, "")
        eid = self._registered.get(f"{UID_PREFIX}{obj}") or f"{component}.{obj}"
        if eid not in self._all_registered:                # a leftover directly written state
            try:
                await self.hass.rest("DELETE", f"/states/{eid}")
            except HassError:
                pass
        self.desired.pop(obj, None)
        self.last_seen.pop(obj, None)
        self._sent_config.pop(obj, None)
        self._sent_state.pop(obj, None)
        self._registered.pop(f"{UID_PREFIX}{obj}", None)
        print(f"mqtt: withdrew {eid}", flush=True)

    def _default_id(self, obj: str) -> str:
        want = self.desired.get(obj)
        return (want and want["attrs"].get("default_entity_id")) or f"{component_of(obj)}.{obj}"

    async def _announce_button(self, force: bool = False):
        """A Refresh button per screen; the first keeps the one 0.8.x made. A screen that's gone loses its button."""
        if force:
            self._announced_buttons.clear()
        wanted = {}
        for suffix, name in self.buttons():
            obj = f"refresh{suffix}"
            wanted[obj] = json.dumps({
                "name": "Refresh panel" if not suffix else f"Refresh {name}",
                "unique_id": BUTTON_UID + suffix,
                "default_entity_id": f"button.epaper_refresh_panel{suffix}",
                "command_topic": f"{BASE}/{obj}/press",
                "availability_topic": AVAILABILITY,
                "icon": "mdi:refresh",
                "device": self._device(),
                "origin": {"name": "E-paper panel add-on", "sw_version": self.version},
            })
        for obj, cfg in wanted.items():
            if self._announced_buttons.get(obj) != cfg:
                await self.transport.publish(f"{DISCOVERY_PREFIX}/button/{NODE}/{obj}/config", cfg)
                self._announced_buttons[obj] = cfg
        for obj in [o for o in self._announced_buttons if o not in wanted]:
            await self.transport.publish(f"{DISCOVERY_PREFIX}/button/{NODE}/{obj}/config", "")
            del self._announced_buttons[obj]

    # ------------------------------------------------------------------ registry hygiene
    async def _load_registry(self):
        self._registered = {}
        self._all_registered = set()
        self._registry_ok = False
        try:
            entries = await self.hass.ws({"type": "config/entity_registry/list"})
        except HassError as exc:
            print(f"mqtt: couldn't read the entity registry ({exc}); skipping clean-up", flush=True)
            return
        self._registry_ok = True
        for e in entries or []:
            self._all_registered.add(e.get("entity_id"))
            if e.get("platform") == "mqtt" and str(e.get("unique_id", "")).startswith(UID_PREFIX):
                self._registered[e["unique_id"]] = e["entity_id"]

    async def _clear_unregistered_state(self, obj: str):
        """Before a value is first announced, remove a state the old add-on wrote directly.

        Otherwise Home Assistant sees the ID as taken and names the new entity
        `sensor.<id>_2`. Only an unregistered state is removed, never an entity
        something else owns.
        """
        eid = self._default_id(obj)
        if f"{UID_PREFIX}{obj}" in self._registered or eid in self._all_registered:
            return
        try:
            await self.hass.rest("DELETE", f"/states/{eid}")
        except HassError:
            pass                                          # nothing there, or not allowed: harmless

    async def _migrate_once(self):
        """0.8.x wrote every value twice, so Home Assistant suffixed the MQTT copies `_2`.

        Remove the directly written states and give each of our entities back
        its intended ID. Only IDs Home Assistant suffixed itself (`<id>_<n>`)
        are changed; an ID someone chose on purpose is left alone.
        """
        done = self._load(self._migrations_path)
        if done.get("dedupe_v1"):
            return
        ok = True
        for uid, current in list(self._registered.items()):
            obj = uid[len(UID_PREFIX):]
            wanted = f"sensor.{obj}"
            # Values 0.8.x left retained on the old, non-standard state topics.
            await self.transport.publish(f"{DISCOVERY_PREFIX}/{NODE}/{obj}/state", "")
            await self.transport.publish(f"{DISCOVERY_PREFIX}/{NODE}/{obj}/attributes", "")
            if current == wanted or not re.fullmatch(re.escape(wanted) + r"_\d+", current):
                continue
            if wanted in self._all_registered:
                print(f"mqtt: {wanted} belongs to something else; leaving {current} as is", flush=True)
                continue
            try:
                try:
                    await self.hass.rest("DELETE", f"/states/{wanted}")
                except HassError as exc:
                    if exc.status != 404:
                        raise
                await self.hass.ws({"type": "config/entity_registry/update",
                                    "entity_id": current, "new_entity_id": wanted})
                self._registered[uid] = wanted
                self._all_registered.discard(current)
                self._all_registered.add(wanted)
                print(f"mqtt: renamed {current} -> {wanted}", flush=True)
            except HassError as exc:
                ok = False
                print(f"mqtt: couldn't rename {current} to {wanted}: {exc}", flush=True)
        if ok:
            done["dedupe_v1"] = time.time()
            self._save(self._migrations_path, done)

    # ------------------------------------------------------------------ persistence
    @staticmethod
    def _load(path: Path) -> dict:
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _save(path: Path, data: dict) -> None:
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
            tmp.replace(path)
        except Exception as exc:
            print(f"mqtt: couldn't save {path.name}: {exc}", flush=True)


class MqttTransport:
    """A long-lived broker connection with reconnects. Needs `aiomqtt`."""

    def __init__(self, host: str, port: int, username: str = "", password: str = ""):
        self.host, self.port = host, int(port)
        self.username, self.password = username or None, password or None
        self.connected = False
        self._client = None

    async def run(self, on_connect, on_message):
        import aiomqtt                                    # only needed when a broker exists
        delay = 2.0
        while True:
            try:
                will = aiomqtt.Will(AVAILABILITY, "offline", qos=1, retain=True)
                async with aiomqtt.Client(self.host, port=self.port, username=self.username,
                                          password=self.password, identifier="epaper_panel_addon",
                                          will=will) as client:
                    self._client = client
                    self.connected = True
                    delay = 2.0
                    await on_connect()
                    async for msg in client.messages:
                        try:
                            await on_message(str(msg.topic), msg.payload)
                        except Exception as exc:
                            print(f"mqtt: message handler failed: {health.describe(exc)}", flush=True)
            except aiomqtt.MqttError as exc:
                print(f"mqtt: connection lost ({exc}); retrying in {int(delay)}s", flush=True)
            except Exception as exc:
                print(f"mqtt: unexpected error ({health.describe(exc)}); retrying in {int(delay)}s", flush=True)
            finally:
                self.connected = False
                self._client = None
            await asyncio.sleep(delay)
            delay = min(60.0, delay * 2)

    async def publish(self, topic: str, payload: str, retain: bool = True) -> bool:
        if not self.connected or self._client is None:
            return False
        try:
            await self._client.publish(topic, payload, qos=1, retain=retain)
            return True
        except Exception as exc:
            print(f"mqtt: publish to {topic} failed: {health.describe(exc)}", flush=True)
            return False

    async def subscribe(self, topic: str) -> None:
        if self._client is not None:
            await self._client.subscribe(topic, qos=1)
