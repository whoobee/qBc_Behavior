"""Visual theme constants for the BT creator and visualizer GUIs."""

# Node status colors (matching qBc project aesthetic)
STATUS_COLORS = {
    "SUCCESS":  "#00ff88",
    "FAILURE":  "#ff3366",
    "RUNNING":  "#00d4ff",
    "INVALID":  "#666666",
}

# Node type colors (for the tree canvas)
TYPE_COLORS = {
    # Composites
    "Sequence":       "#4a90d9",
    "Selector":       "#d94a4a",
    "Parallel":       "#d9944a",
    "RandomSelector": "#d94a8f",
    # Decorators
    "Inverter":         "#9b59b6",
    "Timeout":          "#9b59b6",
    "RunningIsSuccess": "#9b59b6",
    "FailureIsSuccess": "#9b59b6",
    "SuccessIsFailure": "#9b59b6",
    "CooldownGuard":    "#9b59b6",
    # Conditions
    "BlackboardCondition": "#f1c40f",
    "EventCheck":          "#f1c40f",
    "HeartbeatCheck":      "#f1c40f",
    # Actions
    "PlayAnimation": "#2ecc71",
    "PlayAudio":     "#2ecc71",
    "MoveJoint":     "#2ecc71",
    "SendCommand":   "#2ecc71",
    "WaitForEvent":  "#27ae60",
    "TimerBehavior": "#27ae60",
}

# Category colors (broader groupings)
CATEGORY_COLORS = {
    "Composites":  "#4a90d9",
    "Decorators":  "#9b59b6",
    "Conditions":  "#f1c40f",
    "Actions":     "#2ecc71",
}

# GUI layout
BG_COLOR = "#1e1e2e"
BG_SECONDARY = "#2a2a3e"
FG_COLOR = "#cdd6f4"
FG_DIM = "#6c7086"
CANVAS_BG = "#181825"
SELECTION_COLOR = "#89b4fa"
BORDER_COLOR = "#45475a"

# Node rendering
NODE_WIDTH = 160
NODE_HEIGHT = 40
NODE_PADDING_X = 20
NODE_PADDING_Y = 50
NODE_CORNER_RADIUS = 8
NODE_FONT = ("Monospace", 9)
NODE_FONT_BOLD = ("Monospace", 9, "bold")
LABEL_FONT = ("Monospace", 8)
TITLE_FONT = ("Monospace", 12, "bold")

# Status indicators
STATUS_INDICATOR_SIZE = 8

# Type shape prefixes for the canvas (visual hint for node category)
TYPE_SHAPES = {
    "Composites":  "rectangle",
    "Decorators":  "diamond",
    "Conditions":  "ellipse",
    "Actions":     "rectangle",
}
