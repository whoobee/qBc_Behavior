#!/usr/bin/env python3
"""qBc Behavior Tree Visualizer — Real-time tree state viewer.

Subscribes to the behavior service's tree state MQTT topic and
displays the tree with color-coded node statuses, plus a live
blackboard panel.

Can run on any machine on the same network as the MQTT broker.
"""

import argparse
import json
import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.tree_canvas import TreeCanvas
from gui.theme import (
    BG_COLOR, BG_SECONDARY, FG_COLOR, FG_DIM, BORDER_COLOR,
    STATUS_COLORS, NODE_FONT, LABEL_FONT, TITLE_FONT,
)

logger = logging.getLogger("bt_visualizer")

TOPIC_TREE_STATE = "robot/behavior/tree_state"
TOPIC_SERVICE_STATE = "robot/behavior/state"


class BTVisualizer:
    """Real-time behavior tree visualizer GUI."""

    def __init__(self, broker: str = "localhost", port: int = 1883):
        self.broker = broker
        self.port = port
        self._connected = False
        self._tick_count = 0
        self._tick_rate = 0.0
        self._tree_name = ""
        self._blackboard: dict = {}

        # Pending updates queue (thread-safe: MQTT thread → GUI thread)
        self._pending_updates: list[dict] = []
        self._update_lock = threading.Lock()

        self._build_gui()
        self._setup_mqtt()

    def _build_gui(self):
        """Build the tkinter GUI."""
        self.root = tk.Tk()
        self.root.title("qBc Behavior Tree Visualizer")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("1200x700")

        # Top status bar
        top_frame = tk.Frame(self.root, bg=BG_SECONDARY, padx=10, pady=5)
        top_frame.pack(fill=tk.X)

        self._lbl_connection = tk.Label(
            top_frame, text="Disconnected", fg="#ff3366",
            bg=BG_SECONDARY, font=NODE_FONT)
        self._lbl_connection.pack(side=tk.LEFT)

        self._lbl_tree = tk.Label(
            top_frame, text="", fg=FG_COLOR,
            bg=BG_SECONDARY, font=NODE_FONT)
        self._lbl_tree.pack(side=tk.LEFT, padx=20)

        self._lbl_tick = tk.Label(
            top_frame, text="Tick: 0", fg=FG_DIM,
            bg=BG_SECONDARY, font=NODE_FONT)
        self._lbl_tick.pack(side=tk.RIGHT)

        self._lbl_rate = tk.Label(
            top_frame, text="", fg=FG_DIM,
            bg=BG_SECONDARY, font=NODE_FONT)
        self._lbl_rate.pack(side=tk.RIGHT, padx=20)

        # Main content: tree canvas + blackboard panel
        content = tk.PanedWindow(
            self.root, orient=tk.HORIZONTAL, bg=BG_COLOR,
            sashwidth=4, sashrelief=tk.FLAT,
        )
        content.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tree canvas (left, main area)
        self._tree_canvas = TreeCanvas(content, mode="visualizer")
        content.add(self._tree_canvas.frame, stretch="always", minsize=600)

        # Blackboard panel (right sidebar)
        bb_frame = tk.Frame(content, bg=BG_SECONDARY)
        content.add(bb_frame, stretch="never", minsize=250, width=300)

        tk.Label(
            bb_frame, text="Blackboard", fg=FG_COLOR,
            bg=BG_SECONDARY, font=TITLE_FONT,
        ).pack(fill=tk.X, padx=10, pady=(10, 5))

        # Blackboard text widget (scrollable)
        bb_scroll = tk.Scrollbar(bb_frame)
        bb_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._bb_text = tk.Text(
            bb_frame, bg=BG_COLOR, fg=FG_COLOR,
            font=LABEL_FONT, wrap=tk.WORD,
            yscrollcommand=bb_scroll.set,
            state=tk.DISABLED, relief=tk.FLAT,
            padx=8, pady=5,
        )
        self._bb_text.pack(fill=tk.BOTH, expand=True, padx=(10, 0), pady=5)
        bb_scroll.config(command=self._bb_text.yview)

        # Configure text tags for blackboard coloring
        self._bb_text.tag_configure("key", foreground="#89b4fa")
        self._bb_text.tag_configure("value", foreground="#a6e3a1")
        self._bb_text.tag_configure("null", foreground=FG_DIM)
        self._bb_text.tag_configure("section", foreground="#f9e2af",
                                    font=NODE_FONT)

        # Bottom status bar
        bottom_frame = tk.Frame(self.root, bg=BG_SECONDARY, padx=10, pady=3)
        bottom_frame.pack(fill=tk.X)

        self._lbl_status = tk.Label(
            bottom_frame, text="Waiting for tree state...",
            fg=FG_DIM, bg=BG_SECONDARY, font=LABEL_FONT)
        self._lbl_status.pack(side=tk.LEFT)

    def _setup_mqtt(self):
        """Set up MQTT client."""
        self._mqtt = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="qbc_bt_visualizer",
        )
        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_disconnect = self._on_disconnect
        self._mqtt.on_message = self._on_message

    def _on_connect(self, client, userdata, connect_flags, reason_code,
                    properties):
        if reason_code.is_failure:
            logger.error("MQTT connection failed: %s", reason_code)
            return
        self._connected = True
        client.subscribe([
            (TOPIC_TREE_STATE, 0),
            (TOPIC_SERVICE_STATE, 1),
        ])
        logger.info("Connected to MQTT broker %s:%d", self.broker, self.port)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code,
                       properties):
        self._connected = False

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages (runs in paho thread)."""
        try:
            data = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        with self._update_lock:
            self._pending_updates.append({
                "topic": msg.topic,
                "data": data,
            })

    def _process_updates(self):
        """Process pending MQTT updates in the GUI thread (called via after)."""
        with self._update_lock:
            updates = list(self._pending_updates)
            self._pending_updates.clear()

        for update in updates:
            topic = update["topic"]
            data = update["data"]

            if topic == TOPIC_SERVICE_STATE:
                self._update_service_state(data)
            elif topic == TOPIC_TREE_STATE:
                self._update_tree_state(data)

        # Schedule next check
        self.root.after(33, self._process_updates)  # ~30Hz

    def _update_service_state(self, data: dict):
        """Update from robot/behavior/state (retained)."""
        status = data.get("status", "offline")
        self._tree_name = data.get("tree_name", "")
        self._lbl_tree.configure(text=f"Tree: {self._tree_name}")

        rate = data.get("tick_rate_actual", 0)
        self._lbl_rate.configure(text=f"@ {rate:.1f} Hz")

    def _update_tree_state(self, data: dict):
        """Update from robot/behavior/tree_state (live stream)."""
        self._tick_count = data.get("tick", 0)
        self._lbl_tick.configure(text=f"Tick: {self._tick_count}")

        snapshot_type = data.get("snapshot", "diff")

        if snapshot_type == "full":
            # Full tree snapshot — rebuild canvas
            nodes = data.get("nodes", [])
            self._tree_canvas.load_from_snapshot(nodes)
            node_count = len(nodes)
            self._lbl_status.configure(
                text=f"Nodes: {node_count} | Tree: {data.get('tree_name', '')}")
        else:
            # Differential update — just update statuses
            changed = data.get("changed", [])
            if changed:
                self._tree_canvas.update_statuses(changed)

        # Update blackboard panel
        bb = data.get("blackboard", {})
        if bb:
            self._blackboard = bb
            self._render_blackboard()

    def _render_blackboard(self):
        """Render the blackboard state in the text widget."""
        self._bb_text.configure(state=tk.NORMAL)
        self._bb_text.delete("1.0", tk.END)

        # Group by prefix
        groups: dict[str, dict] = {}
        for key, value in sorted(self._blackboard.items()):
            prefix = key.split(".")[0] if "." in key else key
            groups.setdefault(prefix, {})[key] = value

        for group, entries in groups.items():
            self._bb_text.insert(tk.END, f"[{group}]\n", "section")
            for key, value in entries.items():
                short_key = key.split(".", 1)[-1] if "." in key else key
                self._bb_text.insert(tk.END, f"  {short_key}: ", "key")
                if value is None:
                    self._bb_text.insert(tk.END, "null\n", "null")
                elif isinstance(value, dict):
                    val_str = json.dumps(value, default=str)
                    if len(val_str) > 40:
                        val_str = val_str[:38] + ".."
                    self._bb_text.insert(tk.END, f"{val_str}\n", "value")
                else:
                    self._bb_text.insert(tk.END, f"{value}\n", "value")
            self._bb_text.insert(tk.END, "\n")

        self._bb_text.configure(state=tk.DISABLED)

    def run(self):
        """Start the visualizer (blocking)."""
        # Connect MQTT in background
        self._mqtt.connect_async(self.broker, self.port)
        self._mqtt.loop_start()

        # Start GUI update loop
        self.root.after(100, self._process_updates)
        self.root.after(500, self._update_connection_label)

        try:
            self.root.mainloop()
        finally:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()

    def _update_connection_label(self):
        """Update the connection status label periodically."""
        if self._connected:
            self._lbl_connection.configure(
                text=f"Connected: {self.broker}:{self.port}",
                fg="#00ff88")
        else:
            self._lbl_connection.configure(
                text=f"Disconnected: {self.broker}:{self.port}",
                fg="#ff3366")
        self.root.after(1000, self._update_connection_label)


def main():
    parser = argparse.ArgumentParser(
        description="qBc Behavior Tree Visualizer",
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
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    viz = BTVisualizer(broker=args.mqtt_broker, port=args.mqtt_port)
    viz.run()


if __name__ == "__main__":
    main()
