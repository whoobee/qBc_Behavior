"""BlackboardManager: MQTT-to-blackboard bridge with thread-safe staging."""

import json
import time
import threading
import logging

import py_trees

logger = logging.getLogger(__name__)


class BlackboardManager:
    """Bridges MQTT subscriptions to the py_trees blackboard.

    Architecture:
        - MQTT callbacks (running in paho's network thread) write incoming
          data into a thread-safe staging dict.
        - At the start of each tick cycle, the tick thread calls
          flush_to_blackboard() which copies staged data into the actual
          py_trees blackboard.
        - This ensures the blackboard is only ever accessed from the tick
          thread, avoiding race conditions.

    The blackboard config from the YAML descriptor defines three categories:
        subscriptions: retained state topics (full JSON dict → bb key)
        events:        transient events (dict + timestamp + consumed flag)
        heartbeats:    store time.monotonic() of last receipt
    """

    def __init__(self, bb_config: dict):
        self._lock = threading.Lock()
        self._staged: dict[str, object] = {}

        # Parse config into lookup tables
        self._state_topics: dict[str, str] = {}    # topic → bb_key
        self._event_topics: dict[str, str] = {}    # topic → bb_key
        self._heartbeat_topics: dict[str, str] = {}  # topic → bb_key

        for entry in bb_config.get("subscriptions", []):
            topic = entry["topic"]
            key = entry["key"].replace(".", "/")
            self._state_topics[topic] = key

        for entry in bb_config.get("events", []):
            topic = entry["topic"]
            key = entry["key"].replace(".", "/")
            self._event_topics[topic] = key

        for entry in bb_config.get("heartbeats", []):
            topic = entry["topic"]
            key = entry["key"].replace(".", "/")
            self._heartbeat_topics[topic] = key

        # All topics we need to subscribe to
        self._all_topics = {}
        for entry in bb_config.get("subscriptions", []):
            self._all_topics[entry["topic"]] = entry.get("qos", 1)
        for entry in bb_config.get("events", []):
            self._all_topics[entry["topic"]] = entry.get("qos", 1)
        for entry in bb_config.get("heartbeats", []):
            self._all_topics[entry["topic"]] = 0

        # Create blackboard client for writing
        self._bb = py_trees.blackboard.Client(name="mqtt_bridge")
        all_keys = set(self._state_topics.values()) | set(
            self._event_topics.values()) | set(self._heartbeat_topics.values())
        for key in all_keys:
            self._bb.register_key(
                key=key, access=py_trees.common.Access.WRITE,
            )

        logger.info(
            "BlackboardManager: %d state, %d event, %d heartbeat topics",
            len(self._state_topics), len(self._event_topics),
            len(self._heartbeat_topics),
        )

    def subscribe_all(self, mqtt_client):
        """Subscribe to all configured MQTT topics. Call from _on_connect."""
        if not self._all_topics:
            return
        sub_list = [(topic, qos) for topic, qos in self._all_topics.items()]
        mqtt_client.subscribe(sub_list)
        logger.info("Subscribed to %d blackboard topics", len(sub_list))

    def handle_message(self, topic: str, payload: bytes):
        """Called from MQTT on_message callback. Writes to staging dict."""
        if topic in self._state_topics:
            self._stage_state(topic, payload)
        elif topic in self._event_topics:
            self._stage_event(topic, payload)
        elif topic in self._heartbeat_topics:
            self._stage_heartbeat(topic)

    def handles_topic(self, topic: str) -> bool:
        """Check if this topic is managed by the BlackboardManager."""
        return topic in self._all_topics

    def flush_to_blackboard(self):
        """Copy all staged data to the py_trees blackboard.

        Called at the start of each tick from the tick thread.
        """
        with self._lock:
            staged = dict(self._staged)
            self._staged.clear()

        for key, value in staged.items():
            try:
                self._bb.set(key, value)
            except KeyError:
                logger.warning("Blackboard key not registered: %s", key)

    def get_blackboard_snapshot(self) -> dict:
        """Return a snapshot of all managed blackboard values for visualization."""
        snapshot = {}
        all_keys = set(self._state_topics.values()) | set(
            self._event_topics.values()) | set(self._heartbeat_topics.values())
        for key in all_keys:
            try:
                val = self._bb.get(key)
                display_key = key.replace("/", ".")
                if isinstance(val, dict) and "timestamp" in val:
                    # Event: show data + age
                    age = time.monotonic() - val.get("timestamp", 0)
                    snapshot[display_key] = {
                        "data": val.get("data"),
                        "age_sec": round(age, 1),
                        "consumed": val.get("consumed", False),
                    }
                elif isinstance(val, float) and key.startswith("heartbeat"):
                    # Heartbeat: show age
                    age = time.monotonic() - val
                    snapshot[display_key] = f"{age:.1f}s ago"
                else:
                    snapshot[display_key] = val
            except KeyError:
                snapshot[key.replace("/", ".")] = None
        return snapshot

    def _stage_state(self, topic: str, payload: bytes):
        """Stage a state topic update."""
        bb_key = self._state_topics[topic]
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Invalid JSON on %s", topic)
            return
        with self._lock:
            self._staged[bb_key] = data

    def _stage_event(self, topic: str, payload: bytes):
        """Stage an event topic update."""
        bb_key = self._event_topics[topic]
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Invalid JSON on %s", topic)
            return
        with self._lock:
            self._staged[bb_key] = {
                "data": data,
                "timestamp": time.monotonic(),
                "consumed": False,
            }

    def _stage_heartbeat(self, topic: str):
        """Stage a heartbeat timestamp."""
        bb_key = self._heartbeat_topics[topic]
        with self._lock:
            self._staged[bb_key] = time.monotonic()
