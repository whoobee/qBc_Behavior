#!/usr/bin/env python3
"""qBc_Behavior — Behavior Tree Engine MQTT Service.

Loads a behavior tree from a YAML descriptor, subscribes to sensor data
via MQTT, populates a py_trees blackboard, and ticks the tree at ~30Hz.
Actions in the tree publish commands back to MQTT to control animation,
servos, audio, and other subsystems.

Follows the standard qBc service pattern (paho-mqtt 2.x).
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import py_trees

# Ensure the module's directory is on the path for relative imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loader.tree_loader import TreeLoader, TreeLoadError
from behaviors.mqtt_behaviors import BlackboardManager

logger = logging.getLogger("qBc_Behavior")

# MQTT topics
TOPIC_STATE = "robot/behavior/state"
TOPIC_TREE_STATE = "robot/behavior/tree_state"
TOPIC_CMD = "robot/behavior/cmd"
TOPIC_HEARTBEAT = "robot/system/heartbeat/behavior"


class BehaviorService:
    """Behavior tree engine that bridges MQTT and py_trees."""

    def __init__(self, broker: str = "localhost", port: int = 1883,
                 tree_path: str = "trees/default.yaml",
                 tick_rate: float = 30.0):
        self.broker = broker
        self.port = port
        self.tree_path = str(Path(tree_path).resolve())
        self.tick_rate = tick_rate
        self._tick_interval = 1.0 / tick_rate
        self._running = False
        self._tick_count = 0
        self._tick_rate_actual = 0.0
        self.connected = False

        # Load the behavior tree
        self._loader = TreeLoader()
        self._root, self._bb_config, self._tree_meta = self._load_tree(
            self.tree_path)
        self._tree = py_trees.trees.BehaviourTree(root=self._root)
        self._tree_name = self._tree_meta.get("name", "unnamed")

        # Override tick rate from YAML if specified
        yaml_rate = self._tree_meta.get("tick_rate_hz")
        if yaml_rate is not None:
            self.tick_rate = float(yaml_rate)
            self._tick_interval = 1.0 / self.tick_rate

        # MQTT client (standard qBc pattern)
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="qbc_behavior",
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.will_set(
            TOPIC_STATE,
            json.dumps({"status": "offline"}),
            qos=1, retain=True,
        )

        # Blackboard manager (MQTT → blackboard bridge)
        self._bb_manager = BlackboardManager(self._bb_config)

        # Inject MQTT client into all action behaviors
        self._inject_mqtt_client(self._root)

        # Tree state tracking for differential visualization updates
        self._last_node_statuses: dict[str, str] = {}
        self._full_snapshot_sent = False
        self._lock = threading.Lock()

    def _load_tree(self, path: str):
        """Load tree from YAML, raising on error."""
        try:
            return self._loader.load(path)
        except TreeLoadError as e:
            logger.error("Failed to load tree: %s", e)
            raise

    def _inject_mqtt_client(self, node: py_trees.behaviour.Behaviour):
        """Walk the tree and inject the MQTT client into action behaviors."""
        if hasattr(node, "set_mqtt_client"):
            node.set_mqtt_client(self._client)
        if hasattr(node, "children"):
            for child in node.children:
                self._inject_mqtt_client(child)
        if hasattr(node, "decorated"):
            self._inject_mqtt_client(node.decorated)

    # ── MQTT callbacks ────────────────────────────────────────────

    def _on_connect(self, client, userdata, connect_flags, reason_code,
                    properties):
        if reason_code.is_failure:
            logger.error("MQTT connection failed: %s", reason_code)
            return
        self.connected = True
        logger.info("Connected to MQTT broker %s:%d", self.broker, self.port)
        client.subscribe(TOPIC_CMD, qos=1)
        self._bb_manager.subscribe_all(client)
        self._publish_state()

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code,
                       properties):
        self.connected = False
        if reason_code.is_failure:
            logger.warning("Disconnected from MQTT broker: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        # Route blackboard-managed topics to the manager
        if self._bb_manager.handles_topic(msg.topic):
            self._bb_manager.handle_message(msg.topic, msg.payload)
            return

        # Handle behavior service commands
        if msg.topic == TOPIC_CMD:
            self._handle_command(msg.payload)

    def _handle_command(self, payload: bytes):
        """Handle commands sent to robot/behavior/cmd."""
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Invalid JSON on %s", TOPIC_CMD)
            return

        command = data.get("command", "")
        if command == "reload":
            self._reload_tree(data.get("tree", self.tree_path))
        elif command == "load":
            tree_file = data.get("tree")
            if tree_file:
                self._reload_tree(tree_file)
            else:
                logger.warning("Load command missing 'tree' field")
        else:
            logger.warning("Unknown behavior command: %s", command)

    def _reload_tree(self, tree_path: str):
        """Reload the behavior tree from a YAML file."""
        # Resolve bare filenames against the trees directory
        p = Path(tree_path)
        if not p.is_absolute() and not p.exists():
            trees_dir = Path(__file__).parent / "trees"
            candidate = trees_dir / p
            if candidate.exists():
                tree_path = str(candidate)
        logger.info("Reloading tree from %s", tree_path)
        try:
            root, bb_config, tree_meta = self._load_tree(tree_path)
        except TreeLoadError as e:
            logger.error("Reload failed: %s", e)
            return

        with self._lock:
            self.tree_path = str(Path(tree_path).resolve())
            self._root = root
            self._tree = py_trees.trees.BehaviourTree(root=root)
            self._bb_config = bb_config
            self._tree_meta = tree_meta
            self._tree_name = tree_meta.get("name", "unnamed")
            self._bb_manager = BlackboardManager(bb_config)
            self._inject_mqtt_client(self._root)
            self._last_node_statuses.clear()
            self._full_snapshot_sent = False
            self._tick_count = 0

            yaml_rate = tree_meta.get("tick_rate_hz")
            if yaml_rate is not None:
                self.tick_rate = float(yaml_rate)
                self._tick_interval = 1.0 / self.tick_rate

        # Re-subscribe with new config
        if self.connected:
            self._bb_manager.subscribe_all(self._client)

        logger.info("Tree reloaded: %s", self._tree_name)
        self._publish_state()

    # ── State publishing ──────────────────────────────────────────

    def _publish_state(self):
        """Publish retained service state (standard qBc pattern)."""
        state = {
            "status": "online",
            "tree_name": self._tree_name,
            "tree_file": self.tree_path,
            "tick_count": self._tick_count,
            "tick_rate_target": self.tick_rate,
            "tick_rate_actual": round(self._tick_rate_actual, 1),
            "node_count": self._count_nodes(self._root),
        }
        self._client.publish(TOPIC_STATE, json.dumps(state), qos=1,
                             retain=True)

    def _publish_tree_state(self):
        """Publish tree state snapshot for the visualizer.

        Uses differential updates: first message is a full snapshot,
        subsequent messages only contain changed nodes.

        Publishes every 3 ticks (~10 Hz at 30 Hz tick rate) to keep
        the visualizer responsive without flooding MQTT.
        """
        # Throttle to every 3rd tick (~10 Hz) to match WS bridge rate
        if self._tick_count % 3 != 0:
            return

        nodes = []
        current_statuses = {}
        self._collect_node_info(self._root, None, nodes, current_statuses)

        # Re-send a full snapshot every ~5s so late subscribers get the graph
        send_full = (not self._full_snapshot_sent
                     or self._tick_count % 150 == 0)

        if send_full:
            msg = {
                "tick": self._tick_count,
                "timestamp": time.time(),
                "tree_name": self._tree_name,
                "snapshot": "full",
                "nodes": nodes,
                "blackboard": self._bb_manager.get_blackboard_snapshot(),
            }
            self._full_snapshot_sent = True
        else:
            # Differential: only changed nodes
            changed = []
            for node_info in nodes:
                nid = node_info["id"]
                if current_statuses.get(nid) != self._last_node_statuses.get(nid):
                    changed.append({
                        "id": nid,
                        "status": node_info["status"],
                        "message": node_info.get("message", ""),
                    })

            # Always include tick/timestamp so visualizer stays alive
            msg = {
                "tick": self._tick_count,
                "timestamp": time.time(),
                "snapshot": "diff",
                "changed": changed,
                "blackboard": self._bb_manager.get_blackboard_snapshot(),
            }

        self._last_node_statuses = current_statuses
        self._client.publish(TOPIC_TREE_STATE, json.dumps(msg, default=str),
                             qos=0)

    def _collect_node_info(self, node, parent_name, nodes_list,
                           statuses_dict):
        """Recursively collect node info for tree state publishing."""
        status = node.status.name if node.status else "INVALID"
        info = {
            "id": node.name,
            "type": type(node).__name__,
            "status": status,
            "parent": parent_name,
            "message": getattr(node, "feedback_message", ""),
        }
        if hasattr(node, "children") and node.children:
            info["children"] = [c.name for c in node.children]
        nodes_list.append(info)
        statuses_dict[node.name] = status

        if hasattr(node, "children"):
            for child in node.children:
                self._collect_node_info(child, node.name, nodes_list,
                                        statuses_dict)

    def _count_nodes(self, node) -> int:
        count = 1
        if hasattr(node, "children"):
            for child in node.children:
                count += self._count_nodes(child)
        return count

    # ── Tick loop ─────────────────────────────────────────────────

    def _tick_loop(self):
        """~30Hz behavior tree tick loop running in a dedicated thread."""
        rate_window = []
        last_state_publish = 0

        while self._running:
            tick_start = time.monotonic()

            with self._lock:
                # 1. Flush staged MQTT data to blackboard
                self._bb_manager.flush_to_blackboard()

                # 2. Tick the tree
                try:
                    self._tree.tick()
                except Exception:
                    logger.exception("Error during tree tick")

                self._tick_count += 1

                # 3. Publish tree state for visualizer
                try:
                    self._publish_tree_state()
                except Exception:
                    logger.exception("Error publishing tree state")

            # Track actual tick rate
            elapsed = time.monotonic() - tick_start
            rate_window.append(elapsed)
            if len(rate_window) > 30:
                rate_window.pop(0)
            avg_tick = sum(rate_window) / len(rate_window)
            self._tick_rate_actual = 1.0 / max(avg_tick, 0.001)

            # Publish service state every 5 seconds
            now = time.monotonic()
            if now - last_state_publish >= 5.0:
                self._publish_state()
                last_state_publish = now

            # Maintain tick rate
            sleep_time = self._tick_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    # ── Main run loop ─────────────────────────────────────────────

    def run(self):
        """Start the behavior service (blocking)."""
        self._running = True

        # Start tick loop in background thread
        tick_thread = threading.Thread(target=self._tick_loop, daemon=True)

        # Connect MQTT
        self._client.connect(self.broker, self.port)
        self._client.loop_start()

        tick_thread.start()

        logger.info(
            "qBc_Behavior service started — tree '%s' @ %.0f Hz, "
            "MQTT %s:%d",
            self._tree_name, self.tick_rate, self.broker, self.port,
        )

        # Signal handling & heartbeat (standard qBc pattern)
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())

        while not stop.is_set():
            self._client.publish(TOPIC_HEARTBEAT, b"1", qos=0)
            stop.wait(1.0)

        # Graceful shutdown
        logger.info("Shutting down...")
        self._running = False
        tick_thread.join(timeout=2.0)
        self._client.publish(
            TOPIC_STATE, json.dumps({"status": "offline"}),
            qos=1, retain=True,
        )
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("qBc_Behavior service stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="qBc_Behavior — Behavior Tree Engine",
    )
    parser.add_argument(
        "--mqtt-broker", default="localhost",
        help="MQTT broker address (default: localhost)",
    )
    parser.add_argument(
        "--mqtt-port", type=int, default=1883,
        help="MQTT broker port (default: 1883)",
    )
    parser.add_argument(
        "--tree", default="trees/default.yaml",
        help="Path to behavior tree YAML descriptor (default: trees/default.yaml)",
    )
    parser.add_argument(
        "--tick-rate", type=float, default=30.0,
        help="Tree tick rate in Hz (default: 30, can be overridden by YAML)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Resolve tree path relative to script directory
    script_dir = Path(__file__).parent
    tree_path = Path(args.tree)
    if not tree_path.is_absolute():
        tree_path = script_dir / tree_path

    service = BehaviorService(
        broker=args.mqtt_broker,
        port=args.mqtt_port,
        tree_path=str(tree_path),
        tick_rate=args.tick_rate,
    )
    service.run()


if __name__ == "__main__":
    main()
