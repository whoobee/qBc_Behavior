#!/usr/bin/env python3
"""qBc Behavior Tree Creator — GUI tree editor.

Visual editor for creating and editing behavior tree YAML descriptors.
Features:
- Drag-and-drop node palette with all available behavior types
- Interactive tree canvas with node selection
- Property editor for selected nodes
- Blackboard binding editor
- MQTT topic browser
- Tree validation
- Save/load YAML files
"""

import argparse
import copy
import json
import logging
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loader.schema import (
    NODE_CATEGORIES, NODE_PARAMS, COMPOSITE_TYPES, DECORATOR_TYPES,
    register_all, validate_node,
)
from loader.tree_loader import TreeLoader, TreeLoadError, tree_to_dict
from loader.topic_registry import (
    INPUT_TOPICS, OUTPUT_TOPICS,
    get_all_input_topics, get_default_bb_key,
)
from gui.tree_canvas import TreeCanvas
from gui.theme import (
    BG_COLOR, BG_SECONDARY, FG_COLOR, FG_DIM, BORDER_COLOR,
    SELECTION_COLOR, CATEGORY_COLORS,
    NODE_FONT, NODE_FONT_BOLD, LABEL_FONT, TITLE_FONT,
)

logger = logging.getLogger("bt_creator")

DEFAULT_TREE_DIR = Path(__file__).parent / "trees"


class BTCreator:
    """Behavior tree creator GUI application."""

    def __init__(self):
        register_all()
        self._current_file: Path | None = None
        self._unsaved = False
        self._tree_desc: dict = self._new_tree()
        self._selected_node_path: list[str] = []

        self._build_gui()
        self._refresh_canvas()

    # ── Tree descriptor management ────────────────────────────────

    def _new_tree(self) -> dict:
        """Create a new empty tree descriptor."""
        return {
            "tree": {
                "name": "new_behavior",
                "description": "",
                "tick_rate_hz": 30,
            },
            "blackboard": {
                "subscriptions": [],
                "events": [],
                "heartbeats": [],
            },
            "root": {
                "type": "Selector",
                "name": "root",
                "memory": False,
                "children": [],
            },
        }

    def _find_node(self, desc: dict, name: str) -> dict | None:
        """Find a node descriptor by name (DFS)."""
        if desc.get("name") == name:
            return desc
        for child in desc.get("children", []) + desc.get("child", []):
            result = self._find_node(child, name)
            if result is not None:
                return result
        return None

    def _find_parent(self, desc: dict, name: str) -> dict | None:
        """Find the parent of a node by name."""
        for child in desc.get("children", []) + desc.get("child", []):
            if child.get("name") == name:
                return desc
            result = self._find_parent(child, name)
            if result is not None:
                return result
        return None

    def _generate_unique_name(self, base: str) -> str:
        """Generate a unique node name."""
        existing = set()
        self._collect_names(self._tree_desc["root"], existing)
        if base not in existing:
            return base
        i = 2
        while f"{base}_{i}" in existing:
            i += 1
        return f"{base}_{i}"

    def _collect_names(self, desc: dict, names: set):
        names.add(desc.get("name", ""))
        for child in desc.get("children", []) + desc.get("child", []):
            self._collect_names(child, names)

    # ── GUI construction ──────────────────────────────────────────

    def _build_gui(self):
        self.root = tk.Tk()
        self.root.title("qBc Behavior Tree Creator")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("1300x750")

        # Menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New", command=self._cmd_new,
                              accelerator="Ctrl+N")
        file_menu.add_command(label="Open...", command=self._cmd_open,
                              accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self._cmd_save,
                              accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self._cmd_save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._cmd_exit)

        tree_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tree", menu=tree_menu)
        tree_menu.add_command(label="Validate", command=self._cmd_validate,
                              accelerator="Ctrl+V")
        tree_menu.add_command(label="Tree Settings...",
                              command=self._cmd_tree_settings)

        self.root.bind("<Control-n>", lambda e: self._cmd_new())
        self.root.bind("<Control-o>", lambda e: self._cmd_open())
        self.root.bind("<Control-s>", lambda e: self._cmd_save())

        # Main layout: palette | canvas + bb bindings | properties
        main_pane = tk.PanedWindow(
            self.root, orient=tk.HORIZONTAL, bg=BG_COLOR,
            sashwidth=4, sashrelief=tk.FLAT,
        )
        main_pane.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Left: Node palette
        palette_frame = self._build_palette(main_pane)
        main_pane.add(palette_frame, minsize=170, width=180)

        # Center: Tree canvas + blackboard bindings
        center_pane = tk.PanedWindow(
            main_pane, orient=tk.VERTICAL, bg=BG_COLOR,
            sashwidth=4, sashrelief=tk.FLAT,
        )
        main_pane.add(center_pane, stretch="always", minsize=500)

        # Tree canvas
        self._tree_canvas = TreeCanvas(center_pane, mode="creator")
        self._tree_canvas.set_on_select(self._on_node_selected)
        center_pane.add(self._tree_canvas.frame, stretch="always", minsize=350)

        # Blackboard bindings panel
        bb_frame = self._build_bb_panel(center_pane)
        center_pane.add(bb_frame, stretch="never", minsize=120, height=170)

        # Right: Properties panel
        props_frame = self._build_properties(main_pane)
        main_pane.add(props_frame, minsize=250, width=280)

        # Bottom status bar
        status_frame = tk.Frame(self.root, bg=BG_SECONDARY, padx=10, pady=3)
        status_frame.pack(fill=tk.X)

        self._lbl_status = tk.Label(
            status_frame, text="Ready", fg=FG_DIM,
            bg=BG_SECONDARY, font=LABEL_FONT)
        self._lbl_status.pack(side=tk.LEFT)

        self._lbl_file = tk.Label(
            status_frame, text="New tree", fg=FG_DIM,
            bg=BG_SECONDARY, font=LABEL_FONT)
        self._lbl_file.pack(side=tk.RIGHT)

    def _build_palette(self, parent) -> tk.Frame:
        """Build the node type palette panel."""
        frame = tk.Frame(parent, bg=BG_SECONDARY)

        tk.Label(
            frame, text="Node Palette", fg=FG_COLOR,
            bg=BG_SECONDARY, font=TITLE_FONT,
        ).pack(fill=tk.X, padx=8, pady=(8, 4))

        # Scrollable palette
        canvas = tk.Canvas(frame, bg=BG_SECONDARY, highlightthickness=0)
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL,
                                 command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG_SECONDARY)
        inner.bind("<Configure>",
                    lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(fill=tk.BOTH, expand=True)

        for category, types in NODE_CATEGORIES.items():
            cat_color = CATEGORY_COLORS.get(category, FG_COLOR)
            tk.Label(
                inner, text=f"  {category}", fg=cat_color,
                bg=BG_SECONDARY, font=NODE_FONT_BOLD,
                anchor="w",
            ).pack(fill=tk.X, pady=(8, 2))

            for node_type in types:
                btn = tk.Label(
                    inner, text=f"    {node_type}", fg=FG_COLOR,
                    bg=BG_SECONDARY, font=NODE_FONT,
                    anchor="w", cursor="hand2",
                    padx=8, pady=1,
                )
                btn.pack(fill=tk.X)
                btn.bind("<Button-1>",
                         lambda e, t=node_type: self._add_node(t))
                btn.bind("<Enter>",
                         lambda e, b=btn: b.configure(bg=BORDER_COLOR))
                btn.bind("<Leave>",
                         lambda e, b=btn: b.configure(bg=BG_SECONDARY))

        return frame

    def _build_bb_panel(self, parent) -> tk.Frame:
        """Build the blackboard bindings panel."""
        frame = tk.Frame(parent, bg=BG_SECONDARY)

        header = tk.Frame(frame, bg=BG_SECONDARY)
        header.pack(fill=tk.X, padx=8, pady=(5, 2))

        tk.Label(
            header, text="Blackboard Bindings", fg=FG_COLOR,
            bg=BG_SECONDARY, font=NODE_FONT_BOLD,
        ).pack(side=tk.LEFT)

        tk.Button(
            header, text="+Add", command=self._cmd_add_binding,
            bg=BG_COLOR, fg=FG_COLOR, font=LABEL_FONT,
            relief=tk.FLAT, padx=5,
        ).pack(side=tk.RIGHT)

        # Bindings list
        list_frame = tk.Frame(frame, bg=BG_COLOR)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=2)

        cols = ("category", "topic", "key")
        self._bb_tree = ttk.Treeview(
            list_frame, columns=cols, show="headings", height=4)
        self._bb_tree.heading("category", text="Cat.")
        self._bb_tree.heading("topic", text="MQTT Topic")
        self._bb_tree.heading("key", text="BB Key")
        self._bb_tree.column("category", width=50, minwidth=40)
        self._bb_tree.column("topic", width=250, minwidth=100)
        self._bb_tree.column("key", width=150, minwidth=80)

        bb_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                   command=self._bb_tree.yview)
        self._bb_tree.configure(yscrollcommand=bb_scroll.set)

        self._bb_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bb_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Context menu for delete
        self._bb_tree.bind("<Button-3>", self._bb_context_menu)

        return frame

    def _build_properties(self, parent) -> tk.Frame:
        """Build the properties editor panel."""
        frame = tk.Frame(parent, bg=BG_SECONDARY)

        tk.Label(
            frame, text="Properties", fg=FG_COLOR,
            bg=BG_SECONDARY, font=TITLE_FONT,
        ).pack(fill=tk.X, padx=8, pady=(8, 4))

        # Scrollable properties
        canvas = tk.Canvas(frame, bg=BG_SECONDARY, highlightthickness=0)
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL,
                                 command=canvas.yview)
        self._props_inner = tk.Frame(canvas, bg=BG_SECONDARY)
        self._props_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._props_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(fill=tk.BOTH, expand=True)

        # Start with "no selection" message
        self._props_widgets: dict = {}
        self._show_no_selection()

        return frame

    def _show_no_selection(self):
        """Show placeholder when no node is selected."""
        for widget in self._props_inner.winfo_children():
            widget.destroy()
        tk.Label(
            self._props_inner, text="Select a node\nto edit properties",
            fg=FG_DIM, bg=BG_SECONDARY, font=NODE_FONT,
        ).pack(padx=20, pady=40)

    def _show_properties(self, node_desc: dict):
        """Show property editor for the selected node."""
        for widget in self._props_inner.winfo_children():
            widget.destroy()
        self._props_widgets.clear()

        node_type = node_desc.get("type", "")
        name = node_desc.get("name", "")
        params = node_desc.get("params", {})

        # Name field
        self._add_prop_field("Name", name, "name")

        # Type display (read-only)
        self._add_prop_label("Type", node_type)

        # Composite memory flag
        if node_type in ("Sequence", "Selector"):
            memory = node_desc.get("memory", True)
            self._add_prop_checkbox("Memory", memory, "memory")

        # Type-specific params
        param_spec = NODE_PARAMS.get(node_type, {})
        all_params = {}
        all_params.update(param_spec.get("required", {}))
        all_params.update(param_spec.get("optional", {}))

        for param_name, param_type in all_params.items():
            current_value = params.get(param_name, "")
            if param_type == bool:
                val = params.get(param_name, False)
                self._add_prop_checkbox(param_name, val,
                                        f"params.{param_name}")
            elif param_type == dict:
                val = json.dumps(params.get(param_name, {}))
                self._add_prop_field(param_name, val, f"params.{param_name}",
                                     multiline=True)
            elif param_name == "topic":
                self._add_prop_topic_selector(param_name, str(current_value),
                                               f"params.{param_name}")
            elif param_name == "operator":
                self._add_prop_dropdown(param_name, str(current_value),
                                        ["==", "!=", ">", "<", ">=", "<=",
                                         "in", "not_in", "exists"],
                                        f"params.{param_name}")
            elif param_name == "movement_type":
                self._add_prop_dropdown(param_name, str(current_value),
                                        ["linear", "quadratic", "exponential"],
                                        f"params.{param_name}")
            elif param_name == "expression":
                self._add_prop_dropdown(param_name, str(current_value),
                                        ["idle", "happy", "sad", "angry",
                                         "curious", "thinking", "blink",
                                         "surprised", "sleepy"],
                                        f"params.{param_name}")
            else:
                self._add_prop_field(param_name, str(current_value),
                                     f"params.{param_name}")

        # Required marker
        required_params = set(param_spec.get("required", {}).keys())
        if required_params:
            tk.Label(
                self._props_inner,
                text=f"Required: {', '.join(required_params)}",
                fg=FG_DIM, bg=BG_SECONDARY, font=LABEL_FONT,
            ).pack(fill=tk.X, padx=8, pady=(10, 2))

        # Action buttons
        btn_frame = tk.Frame(self._props_inner, bg=BG_SECONDARY)
        btn_frame.pack(fill=tk.X, padx=8, pady=(15, 5))

        tk.Button(
            btn_frame, text="Apply", command=self._cmd_apply_props,
            bg="#2ecc71", fg="white", font=NODE_FONT,
            relief=tk.FLAT, padx=10,
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            btn_frame, text="Delete", command=self._cmd_delete_node,
            bg="#e74c3c", fg="white", font=NODE_FONT,
            relief=tk.FLAT, padx=10,
        ).pack(side=tk.RIGHT, padx=2)

    def _add_prop_label(self, label: str, value: str):
        f = tk.Frame(self._props_inner, bg=BG_SECONDARY)
        f.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(f, text=f"{label}:", fg=FG_DIM, bg=BG_SECONDARY,
                 font=LABEL_FONT, width=12, anchor="w").pack(side=tk.LEFT)
        tk.Label(f, text=value, fg=SELECTION_COLOR, bg=BG_SECONDARY,
                 font=NODE_FONT).pack(side=tk.LEFT, fill=tk.X)

    def _add_prop_field(self, label: str, value: str, key: str,
                        multiline: bool = False):
        f = tk.Frame(self._props_inner, bg=BG_SECONDARY)
        f.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(f, text=f"{label}:", fg=FG_DIM, bg=BG_SECONDARY,
                 font=LABEL_FONT, width=12, anchor="w").pack(side=tk.LEFT)
        if multiline:
            entry = tk.Text(f, bg=BG_COLOR, fg=FG_COLOR, font=LABEL_FONT,
                            height=3, width=20, relief=tk.FLAT)
            entry.insert("1.0", value)
        else:
            entry = tk.Entry(f, bg=BG_COLOR, fg=FG_COLOR, font=LABEL_FONT,
                             relief=tk.FLAT)
            entry.insert(0, value)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._props_widgets[key] = entry

    def _add_prop_checkbox(self, label: str, value: bool, key: str):
        f = tk.Frame(self._props_inner, bg=BG_SECONDARY)
        f.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(f, text=f"{label}:", fg=FG_DIM, bg=BG_SECONDARY,
                 font=LABEL_FONT, width=12, anchor="w").pack(side=tk.LEFT)
        var = tk.BooleanVar(value=value)
        cb = tk.Checkbutton(f, variable=var, bg=BG_SECONDARY, fg=FG_COLOR,
                            selectcolor=BG_COLOR, relief=tk.FLAT)
        cb.pack(side=tk.LEFT)
        self._props_widgets[key] = var

    def _add_prop_dropdown(self, label: str, value: str,
                           options: list[str], key: str):
        f = tk.Frame(self._props_inner, bg=BG_SECONDARY)
        f.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(f, text=f"{label}:", fg=FG_DIM, bg=BG_SECONDARY,
                 font=LABEL_FONT, width=12, anchor="w").pack(side=tk.LEFT)
        var = tk.StringVar(value=value)
        combo = ttk.Combobox(f, textvariable=var, values=options,
                             font=LABEL_FONT, width=18)
        combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._props_widgets[key] = var

    def _add_prop_topic_selector(self, label: str, value: str, key: str):
        """Add a topic selector with all known output topics."""
        topics = []
        for group_topics in OUTPUT_TOPICS.values():
            for topic in group_topics:
                topics.append(topic)
        self._add_prop_dropdown(label, value, topics, key)

    # ── Canvas interaction ────────────────────────────────────────

    def _refresh_canvas(self):
        """Redraw the tree canvas from the current descriptor."""
        self._tree_canvas.load_from_descriptor(self._tree_desc["root"])
        self._refresh_bb_list()
        self._update_title()

    def _on_node_selected(self, node_id: str | None):
        """Handle node selection on the canvas."""
        if node_id is None:
            self._show_no_selection()
            return

        node_desc = self._find_node(self._tree_desc["root"], node_id)
        if node_desc is None:
            self._show_no_selection()
            return

        self._selected_node_path = [node_id]
        self._show_properties(node_desc)

    # ── Node operations ───────────────────────────────────────────

    def _add_node(self, node_type: str):
        """Add a new node of the given type to the selected parent."""
        selected = self._tree_canvas.get_selected_id()
        if selected is None:
            selected = self._tree_desc["root"]["name"]

        parent = self._find_node(self._tree_desc["root"], selected)
        if parent is None:
            self._set_status("No parent selected")
            return

        parent_type = parent.get("type", "")

        # Only composites can have children added
        if parent_type not in COMPOSITE_TYPES:
            # Try parent's parent
            grandparent = self._find_parent(self._tree_desc["root"], selected)
            if grandparent and grandparent.get("type", "") in COMPOSITE_TYPES:
                parent = grandparent
            else:
                self._set_status(
                    f"Cannot add child to {parent_type} node. "
                    "Select a composite node.")
                return

        # Create new node descriptor
        base_name = node_type.lower()
        name = self._generate_unique_name(base_name)

        new_node = {"type": node_type, "name": name}

        if node_type in COMPOSITE_TYPES:
            new_node["children"] = []
            if node_type in ("Sequence", "Selector"):
                new_node["memory"] = True
        elif node_type in DECORATOR_TYPES:
            # Add a placeholder child
            placeholder_name = self._generate_unique_name("placeholder")
            new_node["child"] = [{
                "type": "TimerBehavior",
                "name": placeholder_name,
                "params": {"duration_sec": 1.0},
            }]
        else:
            new_node["params"] = {}

        parent.setdefault("children", []).append(new_node)
        self._unsaved = True
        self._refresh_canvas()
        self._tree_canvas.select_node(name)
        self._on_node_selected(name)
        self._set_status(f"Added {node_type} node: {name}")

    def _cmd_delete_node(self):
        """Delete the selected node."""
        selected = self._tree_canvas.get_selected_id()
        if selected is None:
            return

        # Cannot delete root
        if selected == self._tree_desc["root"].get("name"):
            self._set_status("Cannot delete root node")
            return

        parent = self._find_parent(self._tree_desc["root"], selected)
        if parent is None:
            return

        # Remove from children or child list
        for key in ("children", "child"):
            lst = parent.get(key, [])
            parent[key] = [c for c in lst if c.get("name") != selected]

        self._unsaved = True
        self._show_no_selection()
        self._refresh_canvas()
        self._set_status(f"Deleted node: {selected}")

    def _cmd_apply_props(self):
        """Apply property changes from the editor to the descriptor."""
        selected = self._tree_canvas.get_selected_id()
        if selected is None:
            return

        node_desc = self._find_node(self._tree_desc["root"], selected)
        if node_desc is None:
            return

        for key, widget in self._props_widgets.items():
            if key == "name":
                new_name = widget.get().strip()
                if new_name and new_name != node_desc.get("name"):
                    node_desc["name"] = new_name
            elif key == "memory":
                node_desc["memory"] = widget.get()
            elif key.startswith("params."):
                param_name = key.split(".", 1)[1]
                if isinstance(widget, tk.BooleanVar):
                    value = widget.get()
                elif isinstance(widget, tk.StringVar):
                    value = widget.get()
                elif isinstance(widget, tk.Text):
                    raw = widget.get("1.0", tk.END).strip()
                    try:
                        value = json.loads(raw)
                    except json.JSONDecodeError:
                        value = raw
                else:
                    raw = widget.get().strip()
                    # Try numeric conversion
                    value = self._coerce_value(raw)

                node_desc.setdefault("params", {})[param_name] = value

        self._unsaved = True
        self._refresh_canvas()
        self._set_status("Properties applied")

    def _coerce_value(self, raw: str):
        """Try to convert a string to int, float, bool, or keep as string."""
        if raw.lower() in ("true", "false"):
            return raw.lower() == "true"
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
        return raw

    # ── Blackboard bindings ───────────────────────────────────────

    def _refresh_bb_list(self):
        """Refresh the blackboard bindings treeview."""
        self._bb_tree.delete(*self._bb_tree.get_children())

        bb = self._tree_desc.get("blackboard", {})
        for entry in bb.get("subscriptions", []):
            self._bb_tree.insert("", tk.END, values=(
                "state", entry["topic"], entry["key"]))
        for entry in bb.get("events", []):
            self._bb_tree.insert("", tk.END, values=(
                "event", entry["topic"], entry["key"]))
        for entry in bb.get("heartbeats", []):
            self._bb_tree.insert("", tk.END, values=(
                "hb", entry["topic"], entry["key"]))

    def _cmd_add_binding(self):
        """Open dialog to add a blackboard binding."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Blackboard Binding")
        dialog.configure(bg=BG_SECONDARY)
        dialog.geometry("500x350")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(
            dialog, text="Select MQTT Topic", fg=FG_COLOR,
            bg=BG_SECONDARY, font=TITLE_FONT,
        ).pack(padx=10, pady=(10, 5))

        # Topic list grouped by subsystem
        list_frame = tk.Frame(dialog, bg=BG_COLOR)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        cols = ("topic", "category", "description")
        topic_tree = ttk.Treeview(
            list_frame, columns=cols, show="headings", height=10)
        topic_tree.heading("topic", text="Topic")
        topic_tree.heading("category", text="Category")
        topic_tree.heading("description", text="Description")
        topic_tree.column("topic", width=200)
        topic_tree.column("category", width=60)
        topic_tree.column("description", width=200)

        for info in get_all_input_topics():
            topic_tree.insert("", tk.END, values=(
                info["topic"], info["category"],
                info.get("description", "")))

        topic_tree.pack(fill=tk.BOTH, expand=True)

        # BB key field
        key_frame = tk.Frame(dialog, bg=BG_SECONDARY)
        key_frame.pack(fill=tk.X, padx=10, pady=5)
        tk.Label(key_frame, text="BB Key:", fg=FG_DIM, bg=BG_SECONDARY,
                 font=NODE_FONT).pack(side=tk.LEFT)
        key_entry = tk.Entry(key_frame, bg=BG_COLOR, fg=FG_COLOR,
                             font=NODE_FONT, relief=tk.FLAT)
        key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        def on_topic_select(event):
            sel = topic_tree.selection()
            if sel:
                vals = topic_tree.item(sel[0], "values")
                suggested_key = get_default_bb_key(vals[0])
                key_entry.delete(0, tk.END)
                key_entry.insert(0, suggested_key)

        topic_tree.bind("<<TreeviewSelect>>", on_topic_select)

        def on_add():
            sel = topic_tree.selection()
            if not sel:
                return
            vals = topic_tree.item(sel[0], "values")
            topic = vals[0]
            category = vals[1]
            bb_key = key_entry.get().strip()
            if not bb_key:
                bb_key = get_default_bb_key(topic)

            bb = self._tree_desc.setdefault("blackboard", {})
            entry = {"topic": topic, "key": bb_key, "qos": 1}

            if category == "heartbeat":
                entry.pop("qos", None)
                bb.setdefault("heartbeats", []).append(entry)
            elif category == "event":
                bb.setdefault("events", []).append(entry)
            else:
                bb.setdefault("subscriptions", []).append(entry)

            self._unsaved = True
            self._refresh_bb_list()
            dialog.destroy()

        tk.Button(
            dialog, text="Add Binding", command=on_add,
            bg="#2ecc71", fg="white", font=NODE_FONT,
            relief=tk.FLAT, padx=15,
        ).pack(pady=10)

    def _bb_context_menu(self, event):
        """Right-click context menu for blackboard bindings."""
        item = self._bb_tree.identify_row(event.y)
        if not item:
            return
        self._bb_tree.selection_set(item)

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Delete", command=lambda: self._delete_binding(item))
        menu.post(event.x_root, event.y_root)

    def _delete_binding(self, item):
        """Delete a blackboard binding."""
        vals = self._bb_tree.item(item, "values")
        category, topic, key = vals[0], vals[1], vals[2]

        bb = self._tree_desc.get("blackboard", {})
        list_key = {"state": "subscriptions", "event": "events",
                    "hb": "heartbeats"}.get(category, "subscriptions")

        bb[list_key] = [e for e in bb.get(list_key, [])
                        if e["topic"] != topic]

        self._unsaved = True
        self._refresh_bb_list()

    # ── File operations ───────────────────────────────────────────

    def _cmd_new(self):
        if self._unsaved:
            if not messagebox.askyesno("Unsaved Changes",
                                       "Discard unsaved changes?"):
                return
        self._tree_desc = self._new_tree()
        self._current_file = None
        self._unsaved = False
        self._show_no_selection()
        self._refresh_canvas()
        self._set_status("New tree created")

    def _cmd_open(self):
        if self._unsaved:
            if not messagebox.askyesno("Unsaved Changes",
                                       "Discard unsaved changes?"):
                return

        path = filedialog.askopenfilename(
            initialdir=str(DEFAULT_TREE_DIR),
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path) as f:
                desc = yaml.safe_load(f)
            if "root" not in desc:
                messagebox.showerror("Error", "Invalid tree file: no 'root' section")
                return
            self._tree_desc = desc
            self._current_file = Path(path)
            self._unsaved = False
            self._show_no_selection()
            self._refresh_canvas()
            self._set_status(f"Opened: {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file:\n{e}")

    def _cmd_save(self):
        if self._current_file is None:
            self._cmd_save_as()
            return
        self._save_to(self._current_file)

    def _cmd_save_as(self):
        path = filedialog.asksaveasfilename(
            initialdir=str(DEFAULT_TREE_DIR),
            defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml *.yml")],
        )
        if not path:
            return
        self._current_file = Path(path)
        self._save_to(self._current_file)

    def _save_to(self, path: Path):
        """Save the tree descriptor to a YAML file."""
        # Clean up empty params
        self._clean_descriptor(self._tree_desc["root"])

        try:
            with open(path, "w") as f:
                yaml.dump(self._tree_desc, f, default_flow_style=False,
                          sort_keys=False, allow_unicode=True)
            self._unsaved = False
            self._update_title()
            self._set_status(f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def _clean_descriptor(self, desc: dict):
        """Remove empty params and clean up the descriptor."""
        params = desc.get("params", {})
        desc["params"] = {k: v for k, v in params.items()
                          if v != "" and v is not None}
        if not desc["params"]:
            desc.pop("params", None)

        for child in desc.get("children", []) + desc.get("child", []):
            self._clean_descriptor(child)

    # ── Validation ────────────────────────────────────────────────

    def _cmd_validate(self):
        """Validate the current tree descriptor."""
        try:
            loader = TreeLoader()
            loader.load.__func__  # Just check it's callable
            # Do a dry-run validation
            errors = loader._validate_tree(self._tree_desc["root"])
            if errors:
                msg = "Validation errors:\n\n" + "\n".join(
                    f"  - {e}" for e in errors)
                messagebox.showwarning("Validation", msg)
                self._set_status(f"Validation: {len(errors)} error(s)")
            else:
                messagebox.showinfo("Validation", "Tree is valid!")
                self._set_status("Validation: OK")
        except Exception as e:
            messagebox.showerror("Error", f"Validation failed:\n{e}")

    # ── Tree settings ─────────────────────────────────────────────

    def _cmd_tree_settings(self):
        """Open tree metadata settings dialog."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Tree Settings")
        dialog.configure(bg=BG_SECONDARY)
        dialog.geometry("400x250")
        dialog.transient(self.root)
        dialog.grab_set()

        meta = self._tree_desc.get("tree", {})

        fields = {}
        for label, key, default in [
            ("Name", "name", "new_behavior"),
            ("Description", "description", ""),
            ("Tick Rate (Hz)", "tick_rate_hz", 30),
        ]:
            f = tk.Frame(dialog, bg=BG_SECONDARY)
            f.pack(fill=tk.X, padx=15, pady=5)
            tk.Label(f, text=f"{label}:", fg=FG_DIM, bg=BG_SECONDARY,
                     font=NODE_FONT, width=15, anchor="w").pack(side=tk.LEFT)
            entry = tk.Entry(f, bg=BG_COLOR, fg=FG_COLOR, font=NODE_FONT,
                             relief=tk.FLAT)
            entry.insert(0, str(meta.get(key, default)))
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            fields[key] = entry

        def on_apply():
            for key, entry in fields.items():
                val = entry.get().strip()
                if key == "tick_rate_hz":
                    try:
                        val = int(val)
                    except ValueError:
                        val = 30
                self._tree_desc.setdefault("tree", {})[key] = val
            self._unsaved = True
            self._update_title()
            dialog.destroy()

        tk.Button(
            dialog, text="Apply", command=on_apply,
            bg="#2ecc71", fg="white", font=NODE_FONT,
            relief=tk.FLAT, padx=15,
        ).pack(pady=15)

    # ── Utilities ─────────────────────────────────────────────────

    def _cmd_exit(self):
        if self._unsaved:
            if not messagebox.askyesno("Unsaved Changes",
                                       "Discard unsaved changes?"):
                return
        self.root.destroy()

    def _set_status(self, msg: str):
        self._lbl_status.configure(text=msg)

    def _update_title(self):
        name = self._tree_desc.get("tree", {}).get("name", "unnamed")
        file_str = str(self._current_file) if self._current_file else "New"
        unsaved = " *" if self._unsaved else ""
        self.root.title(f"qBc BT Creator — {name}{unsaved}")
        self._lbl_file.configure(text=f"{file_str}{unsaved}")

    def run(self):
        """Start the creator GUI (blocking)."""
        self._update_title()
        self.root.protocol("WM_DELETE_WINDOW", self._cmd_exit)
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(
        description="qBc Behavior Tree Creator",
    )
    parser.add_argument(
        "--open", default=None,
        help="Open a YAML tree file on startup",
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

    creator = BTCreator()

    if args.open:
        path = Path(args.open)
        if path.exists():
            try:
                with open(path) as f:
                    desc = yaml.safe_load(f)
                if "root" in desc:
                    creator._tree_desc = desc
                    creator._current_file = path
                    creator._refresh_canvas()
            except Exception as e:
                logger.error("Failed to open %s: %s", path, e)

    creator.run()


if __name__ == "__main__":
    main()
