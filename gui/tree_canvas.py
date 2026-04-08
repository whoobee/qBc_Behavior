"""Shared tree canvas renderer for the BT creator and visualizer.

Renders a behavior tree as a visual graph on a tkinter Canvas,
with nodes colored by type or status, connected by lines.
"""

import tkinter as tk
from dataclasses import dataclass, field
from gui.theme import (
    TYPE_COLORS, STATUS_COLORS, CANVAS_BG, FG_COLOR, FG_DIM,
    SELECTION_COLOR, BORDER_COLOR,
    NODE_WIDTH, NODE_HEIGHT, NODE_PADDING_X, NODE_PADDING_Y,
    NODE_FONT, NODE_FONT_BOLD, LABEL_FONT, STATUS_INDICATOR_SIZE,
)


@dataclass
class NodeLayout:
    """Layout information for a single node in the tree."""
    node_id: str
    node_type: str
    name: str
    status: str = "INVALID"
    message: str = ""
    parent_id: str | None = None
    children_ids: list[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    width: float = NODE_WIDTH
    height: float = NODE_HEIGHT
    canvas_items: list[int] = field(default_factory=list)


class TreeCanvas:
    """Renders a behavior tree on a tkinter Canvas widget.

    Used by both the visualizer (read-only, status-colored) and
    the creator (interactive, type-colored, drag-and-drop).
    """

    def __init__(self, parent: tk.Widget, mode: str = "visualizer"):
        """
        Args:
            parent: tkinter parent widget
            mode: "visualizer" (color by status) or "creator" (color by type)
        """
        self.mode = mode
        self._nodes: dict[str, NodeLayout] = {}
        self._selected_id: str | None = None
        self._on_select_callback = None
        self._on_drop_callback = None

        # Scrollable canvas
        self.frame = tk.Frame(parent, bg=CANVAS_BG)
        self.canvas = tk.Canvas(
            self.frame, bg=CANVAS_BG,
            highlightthickness=0,
            scrollregion=(0, 0, 2000, 2000),
        )
        self._scrollbar_v = tk.Scrollbar(
            self.frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self._scrollbar_h = tk.Scrollbar(
            self.frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(
            yscrollcommand=self._scrollbar_v.set,
            xscrollcommand=self._scrollbar_h.set,
        )

        self._scrollbar_v.pack(side=tk.RIGHT, fill=tk.Y)
        self._scrollbar_h.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bindings
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def grid(self, **kwargs):
        self.frame.grid(**kwargs)

    def set_on_select(self, callback):
        """Set callback for node selection: callback(node_id)."""
        self._on_select_callback = callback

    def set_on_drop(self, callback):
        """Set callback for node drop: callback(node_type, parent_id, x, y)."""
        self._on_drop_callback = callback

    # ── Tree data ─────────────────────────────────────────────────

    def load_from_snapshot(self, nodes: list[dict]):
        """Load tree structure from a visualizer snapshot (list of node dicts).

        Each dict: {id, type, status, parent, children, message}
        """
        self._nodes.clear()
        for info in nodes:
            node = NodeLayout(
                node_id=info["id"],
                node_type=info.get("type", ""),
                name=info["id"],
                status=info.get("status", "INVALID"),
                message=info.get("message", ""),
                parent_id=info.get("parent"),
                children_ids=info.get("children", []),
            )
            self._nodes[node.node_id] = node
        self._layout_tree()
        self._render()

    def load_from_descriptor(self, root_desc: dict):
        """Load tree structure from a YAML descriptor dict (for creator)."""
        self._nodes.clear()
        self._load_desc_recursive(root_desc, None)
        self._layout_tree()
        self._render()

    def update_statuses(self, changed: list[dict]):
        """Apply differential status updates from the visualizer.

        Each dict: {id, status, message}
        """
        for update in changed:
            nid = update["id"]
            if nid in self._nodes:
                self._nodes[nid].status = update.get("status", "INVALID")
                self._nodes[nid].message = update.get("message", "")
        self._render()

    def get_selected_id(self) -> str | None:
        return self._selected_id

    def select_node(self, node_id: str | None):
        self._selected_id = node_id
        self._render()

    # ── Internal ──────────────────────────────────────────────────

    def _load_desc_recursive(self, desc: dict, parent_id: str | None):
        """Recursively load nodes from a YAML descriptor."""
        nid = desc["name"]
        node = NodeLayout(
            node_id=nid,
            node_type=desc["type"],
            name=nid,
            parent_id=parent_id,
        )
        self._nodes[nid] = node

        children = desc.get("children", [])
        child_list = desc.get("child", [])
        all_children = children + child_list

        for child_desc in all_children:
            child_id = child_desc["name"]
            node.children_ids.append(child_id)
            self._load_desc_recursive(child_desc, nid)

    def _layout_tree(self):
        """Calculate node positions using a top-down tree layout."""
        root = self._find_root()
        if root is None:
            return

        # First pass: calculate subtree widths
        widths = {}
        self._calc_subtree_width(root.node_id, widths)

        # Second pass: assign positions
        total_width = widths.get(root.node_id, NODE_WIDTH)
        self._assign_positions(root.node_id, total_width / 2, 30, widths)

        # Update scroll region
        max_x = max((n.x + n.width for n in self._nodes.values()), default=500)
        max_y = max((n.y + n.height for n in self._nodes.values()), default=500)
        self.canvas.configure(
            scrollregion=(0, 0, max_x + 50, max_y + 50))

    def _find_root(self) -> NodeLayout | None:
        """Find the root node (no parent)."""
        for node in self._nodes.values():
            if node.parent_id is None:
                return node
        return None

    def _calc_subtree_width(self, node_id: str, widths: dict) -> float:
        """Calculate the width needed for a subtree."""
        node = self._nodes.get(node_id)
        if node is None:
            return NODE_WIDTH

        if not node.children_ids:
            widths[node_id] = NODE_WIDTH + NODE_PADDING_X
            return widths[node_id]

        total = 0
        for cid in node.children_ids:
            total += self._calc_subtree_width(cid, widths)
        widths[node_id] = max(total, NODE_WIDTH + NODE_PADDING_X)
        return widths[node_id]

    def _assign_positions(self, node_id: str, center_x: float, y: float,
                          widths: dict):
        """Assign x, y positions to nodes top-down."""
        node = self._nodes.get(node_id)
        if node is None:
            return

        node.x = center_x - NODE_WIDTH / 2
        node.y = y

        if not node.children_ids:
            return

        child_total = sum(widths.get(cid, NODE_WIDTH) for cid in node.children_ids)
        start_x = center_x - child_total / 2
        child_y = y + NODE_HEIGHT + NODE_PADDING_Y

        for cid in node.children_ids:
            child_width = widths.get(cid, NODE_WIDTH)
            child_cx = start_x + child_width / 2
            self._assign_positions(cid, child_cx, child_y, widths)
            start_x += child_width

    def _render(self):
        """Redraw all nodes and connections on the canvas."""
        self.canvas.delete("all")

        # Draw connections first (behind nodes)
        for node in self._nodes.values():
            if node.parent_id and node.parent_id in self._nodes:
                parent = self._nodes[node.parent_id]
                self.canvas.create_line(
                    parent.x + NODE_WIDTH / 2,
                    parent.y + NODE_HEIGHT,
                    node.x + NODE_WIDTH / 2,
                    node.y,
                    fill=BORDER_COLOR, width=2,
                )

        # Draw nodes
        for node in self._nodes.values():
            self._draw_node(node)

    def _draw_node(self, node: NodeLayout):
        """Draw a single node on the canvas."""
        x, y = node.x, node.y
        w, h = NODE_WIDTH, NODE_HEIGHT
        is_selected = node.node_id == self._selected_id

        # Node color
        if self.mode == "visualizer":
            fill = STATUS_COLORS.get(node.status, STATUS_COLORS["INVALID"])
            # Dim the fill for non-running nodes
            if node.status in ("INVALID",):
                fill = "#333344"
            elif node.status == "SUCCESS":
                fill = "#1a4d3a"
            elif node.status == "FAILURE":
                fill = "#4d1a2a"
        else:
            fill = TYPE_COLORS.get(node.node_type, "#555555")

        outline = SELECTION_COLOR if is_selected else BORDER_COLOR
        outline_width = 3 if is_selected else 1

        # Rectangle
        items = []
        items.append(self.canvas.create_rectangle(
            x, y, x + w, y + h,
            fill=fill, outline=outline, width=outline_width,
            tags=("node", node.node_id),
        ))

        # Status indicator (small circle)
        if self.mode == "visualizer":
            ind_color = STATUS_COLORS.get(node.status, STATUS_COLORS["INVALID"])
            s = STATUS_INDICATOR_SIZE
            items.append(self.canvas.create_oval(
                x + 4, y + (h - s) / 2,
                x + 4 + s, y + (h - s) / 2 + s,
                fill=ind_color, outline="",
                tags=("node", node.node_id),
            ))

        # Node name text
        text_x = x + w / 2
        if self.mode == "visualizer":
            text_x = x + 8 + STATUS_INDICATOR_SIZE + (w - 8 - STATUS_INDICATOR_SIZE) / 2

        # Truncate name to fit
        display_name = node.name
        if len(display_name) > 18:
            display_name = display_name[:16] + ".."

        items.append(self.canvas.create_text(
            text_x, y + h / 2 - 2,
            text=display_name,
            fill=FG_COLOR, font=NODE_FONT_BOLD,
            anchor="center",
            tags=("node", node.node_id),
        ))

        # Type label (small, below name)
        type_label = node.node_type
        if self.mode == "visualizer" and node.message:
            type_label = node.message
            if len(type_label) > 22:
                type_label = type_label[:20] + ".."
        items.append(self.canvas.create_text(
            text_x, y + h + 4,
            text=type_label,
            fill=FG_DIM, font=LABEL_FONT,
            anchor="n",
            tags=("label", node.node_id),
        ))

        node.canvas_items = items

    # ── Event handlers ────────────────────────────────────────────

    def _on_click(self, event):
        """Handle canvas click — select node."""
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)

        clicked_id = None
        for node in self._nodes.values():
            if (node.x <= x <= node.x + NODE_WIDTH and
                    node.y <= y <= node.y + NODE_HEIGHT):
                clicked_id = node.node_id
                break

        self._selected_id = clicked_id
        self._render()

        if self._on_select_callback:
            self._on_select_callback(clicked_id)

    def _on_mousewheel(self, event):
        """Handle mousewheel scroll."""
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")
