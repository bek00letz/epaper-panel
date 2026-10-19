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
  epaper_panel/refresh/press                                   the Refresh button

Discovery topics and unique_ids are the ones 0.8.x used, so entities people
already have carry over with their settings.
"""
from __future__ import annotations

import health
import asyncio
import json
import re
import time
from pathlib import Path

from hass import Hass, HassError

DISCOVERY_PREFIX = "homeassistant"
NODE = "epaper_panel"
BASE = "epaper_panel"
AVAILABILITY = f"{BASE}/status"
BUTTON_COMMAND = f"{BASE}/refresh/press"
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

# Attributes that are entity metadata, not data.
META_ATTRS = ("friendly_name", "icon", "unit_of_measurement", "device_class", "source")


def object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1]


def component_of(obj: str) -> str:
    return "binary_sensor" if obj.startswith(PROBLEM_PREFIX) else "sensor"


def entity_name(attrs: dict, obj: str) -> str:
    name = str(attrs.get("friendly_name") or obj.replace("_", " ").capitalize())
    return re.sub(r"^E-?Paper\s*·\s*", "", name, flags=re.I).strip() or obj


class EntityPublisher:
    def __init__(self, transport, hass: Hass, data_dir: Path, version: str, on_button=None,
                 clock=time.time):
        self.transport = transport
        self.hass = hass
        self.version = version
        self.on_button = on_button
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
        self._kept: set[str] = set()                  # object_ids the configuration still wants
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
        # "None" is how an MQTT sensor is told its value is unknown.
        self.desired[obj] = {"state": "None" if state is None else str(state)[:255], "attrs": dict(attrs or {})}
        self.last_seen[obj] = self._clock()

    def set_problem(self, slug: str, name: str, on: bool, attrs: dict) -> None:
        """A service's problem sensor: on while it has been failing (health.py)."""
        obj = f"{PROBLEM_PREFIX}{slug}"
        self.desired[obj] = {"state": "ON" if on else "OFF",
                             "attrs": {"friendly_name": name, "device_class": "problem", **attrs}}
        self.last_seen[obj] = self._clock()

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
        await self.transport.subscribe(BUTTON_COMMAND)
        await self.transport.publish(AVAILABILITY, "online")
        await self._load_registry()
        await self._migrate_once()
        if self._registry_ok:
            # A retired value Home Assistant no longer has needs no withdrawing.
            for obj, seen in list(self.last_seen.items()):
                if seen == 0.0 and f"{UID_PREFIX}{obj}" not in self._registered \
                        and f"sensor.{obj}" not in self._all_registered:
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
        elif topic == BUTTON_COMMAND and self.on_button is not None:
            await self.on_button()

    # ------------------------------------------------------------------ entities
    def _config(self, obj: str, attrs: dict) -> dict:
        component = component_of(obj)
        cfg = {
            "name": entity_name(attrs, obj),
            "unique_id": f"{UID_PREFIX}{obj}",
            "default_entity_id": f"{component}.{obj}",
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
        if component == "binary_sensor":
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
            self._registered.setdefault(f"{UID_PREFIX}{obj}", f"{component}.{obj}")
            self._all_registered.add(f"{component}.{obj}")

    async def _send_state(self, obj: str, want: dict):
        attrs = {k: v for k, v in want["attrs"].items() if k not in META_ATTRS}
        attrs_json = json.dumps(attrs, sort_keys=True, default=str)
        key = (want["state"], attrs_json)
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
        eid = f"{component}.{obj}"
        if eid not in self._all_registered:                # a leftover directly written state
            try:
                await self.hass.rest("DELETE", f"/states/{eid}")
            except HassError:
                pass
        self.desired.pop(obj, None)
        self.last_seen.pop(obj, None)
        self._sent_config.pop(obj, None)
        self._sent_state.pop(obj, None)
        print(f"mqtt: withdrew {eid}", flush=True)

    async def _announce_button(self, force: bool = False):
        cfg = {
            "name": "Refresh panel",
            "unique_id": BUTTON_UID,
            "default_entity_id": "button.epaper_refresh_panel",
            "command_topic": BUTTON_COMMAND,
            "availability_topic": AVAILABILITY,
            "icon": "mdi:refresh",
            "device": self._device(),
            "origin": {"name": "E-paper panel add-on", "sw_version": self.version},
        }
        await self.transport.publish(f"{DISCOVERY_PREFIX}/button/{NODE}/refresh/config", json.dumps(cfg))

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
        eid = f"{component_of(obj)}.{obj}"
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
