"""Node type registry and validation for behavior tree YAML descriptors."""

import py_trees

# These are populated after behavior classes are imported (see register_all below)
NODE_REGISTRY: dict[str, type] = {}

# Categories for the creator GUI palette
NODE_CATEGORIES = {
    "Composites": [
        "Sequence",
        "Selector",
        "Parallel",
        "RandomSelector",
    ],
    "Decorators": [
        "Inverter",
        "Timeout",
        "RunningIsSuccess",
        "FailureIsSuccess",
        "SuccessIsFailure",
        "CooldownGuard",
    ],
    "Conditions": [
        "BlackboardCondition",
        "EventCheck",
        "HeartbeatCheck",
    ],
    "Actions": [
        "PlayAnimation",
        "PlayAudio",
        "MoveJoint",
        "SendCommand",
        "WaitForEvent",
        "TimerBehavior",
    ],
}

# Which types are composites (have children) vs decorators (have single child)
COMPOSITE_TYPES = {"Sequence", "Selector", "Parallel", "RandomSelector"}
DECORATOR_TYPES = {
    "Inverter", "Timeout", "RunningIsSuccess", "FailureIsSuccess",
    "SuccessIsFailure", "CooldownGuard",
}

# Required and optional params for each node type (for validation + creator GUI)
NODE_PARAMS = {
    "Sequence":           {"optional": {"memory": bool}},
    "Selector":           {"optional": {"memory": bool}},
    "Parallel":           {"optional": {"policy": str}},
    "RandomSelector":     {"optional": {"memory": bool}},
    "Inverter":           {},
    "Timeout":            {"required": {"duration_sec": float}},
    "RunningIsSuccess":   {},
    "FailureIsSuccess":   {},
    "SuccessIsFailure":   {},
    "CooldownGuard":      {"required": {"cooldown_sec": float}},
    "BlackboardCondition": {
        "required": {"key": str, "operator": str},
        "optional": {"value": object, "default": object},
    },
    "EventCheck": {
        "required": {"key": str},
        "optional": {"max_age_sec": float, "consume": bool},
    },
    "HeartbeatCheck": {
        "required": {"key": str},
        "optional": {"max_age_sec": float},
    },
    "PlayAnimation": {
        "optional": {
            "expression": str, "duration": float,
            "color": str, "joints": dict,
        },
    },
    "PlayAudio": {
        "required": {"file": str},
        "optional": {"volume": int},
    },
    "MoveJoint": {
        "required": {"joint_name": str, "target_position": float},
        "optional": {"duration": float, "movement_type": str},
    },
    "SendCommand": {
        "required": {"topic": str, "payload": dict},
        "optional": {"qos": int},
    },
    "WaitForEvent": {
        "required": {"key": str},
        "optional": {"timeout_sec": float},
    },
    "TimerBehavior": {
        "required": {"duration_sec": float},
    },
}


def register_all():
    """Register all node types. Must be called after behavior modules are imported."""
    from behaviors.conditions import BlackboardCondition, EventCheck, HeartbeatCheck
    from behaviors.actions import PlayAnimation, PlayAudio, MoveJoint, SendCommand
    from behaviors.timers import WaitForEvent, TimerBehavior, CooldownGuard
    from behaviors.composites import RandomSelector

    NODE_REGISTRY.update({
        # py_trees builtins
        "Sequence":         py_trees.composites.Sequence,
        "Selector":         py_trees.composites.Selector,
        "Parallel":         py_trees.composites.Parallel,
        # py_trees decorators
        "Inverter":         py_trees.decorators.Inverter,
        "Timeout":          None,  # handled specially in tree_loader
        "RunningIsSuccess": py_trees.decorators.RunningIsSuccess,
        "FailureIsSuccess": py_trees.decorators.FailureIsSuccess,
        "SuccessIsFailure": py_trees.decorators.SuccessIsFailure,
        # Custom behaviors
        "BlackboardCondition": BlackboardCondition,
        "EventCheck":          EventCheck,
        "HeartbeatCheck":      HeartbeatCheck,
        "PlayAnimation":       PlayAnimation,
        "PlayAudio":           PlayAudio,
        "MoveJoint":           MoveJoint,
        "SendCommand":         SendCommand,
        "WaitForEvent":        WaitForEvent,
        "TimerBehavior":       TimerBehavior,
        "CooldownGuard":       CooldownGuard,
        "RandomSelector":      RandomSelector,
    })


def _load_valid_values():
    """Load known-good values from the filesystem and config.

    Returns a dict of sets for value validation. Loaded lazily and cached.
    """
    if hasattr(_load_valid_values, "_cache"):
        return _load_valid_values._cache

    import json as _json
    from pathlib import Path

    project = Path(__file__).parent.parent.parent
    result = {
        "animations": set(),
        "sounds": set(),
        "joint_names": set(),
        "operators": {"==", "!=", ">", "<", ">=", "<=", "in", "not_in", "exists"},
        "movement_types": {"linear", "quadratic", "exponential"},
    }

    ani_dir = project / "qBc_Animation" / "animations"
    if ani_dir.exists():
        result["animations"] = {f.stem for f in ani_dir.glob("*.ani")}

    sounds_dir = project / "qBc_Audio" / "resources" / "sounds"
    if sounds_dir.exists():
        result["sounds"] = {
            f.name for f in sounds_dir.iterdir()
            if f.suffix.lower() in {".wav", ".mp3", ".ogg", ".flac"}
        }

    calib = project / "qBc_Servos" / "servo_calibration.json"
    if calib.exists():
        try:
            data = _json.loads(calib.read_text())
            result["joint_names"] = set(data.get("servos", {}).keys())
        except Exception:
            pass

    _load_valid_values._cache = result
    return result


def validate_node(node_type: str, params: dict) -> list[str]:
    """Validate node params against schema. Returns list of error messages.

    Checks:
      1. Node type is known.
      2. Required params are present.
      3. No unknown params.
      4. Param value types are correct.
      5. Param values are valid (e.g., operator is a known operator,
         expression is a real animation, joint_name exists, etc.).
    """
    errors = []
    if node_type not in NODE_PARAMS:
        errors.append(f"Unknown node type: {node_type}")
        return errors

    spec = NODE_PARAMS[node_type]
    required = spec.get("required", {})
    optional = spec.get("optional", {})
    allowed = set(required) | set(optional)

    for key in required:
        if key not in params:
            errors.append(f"{node_type}: missing required param '{key}'")

    for key in params:
        if key not in allowed:
            errors.append(f"{node_type}: unknown param '{key}'")

    # -- Type checks --
    all_specs = {**required, **optional}
    for key, value in params.items():
        expected_type = all_specs.get(key)
        if expected_type is None or expected_type is object:
            continue
        if expected_type is float and isinstance(value, (int, float)):
            continue
        if expected_type is int and isinstance(value, int):
            continue
        if not isinstance(value, expected_type):
            errors.append(
                f"{node_type}: param '{key}' expected {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )

    # -- Value validation --
    valid = _load_valid_values()

    if node_type == "BlackboardCondition":
        op = params.get("operator")
        if op is not None and op not in valid["operators"]:
            errors.append(
                f"{node_type}: unknown operator '{op}' "
                f"(valid: {', '.join(sorted(valid['operators']))})"
            )

    if node_type == "PlayAnimation":
        expr = params.get("expression")
        if expr is not None and valid["animations"] and expr not in valid["animations"]:
            errors.append(
                f"{node_type}: unknown expression '{expr}' "
                f"(available: {', '.join(sorted(valid['animations']))})"
            )

    if node_type == "PlayAudio":
        f = params.get("file")
        if f is not None and valid["sounds"] and f not in valid["sounds"]:
            errors.append(
                f"{node_type}: sound file '{f}' not found "
                f"(available: {', '.join(sorted(valid['sounds']))})"
            )
        vol = params.get("volume")
        if vol is not None and isinstance(vol, int) and not (0 <= vol <= 100):
            errors.append(f"{node_type}: volume {vol} out of range (0-100)")

    if node_type == "MoveJoint":
        jn = params.get("joint_name")
        if jn is not None and valid["joint_names"] and jn not in valid["joint_names"]:
            errors.append(
                f"{node_type}: unknown joint '{jn}' "
                f"(available: {', '.join(sorted(valid['joint_names']))})"
            )
        mt = params.get("movement_type")
        if mt is not None and mt not in valid["movement_types"]:
            errors.append(
                f"{node_type}: unknown movement_type '{mt}' "
                f"(valid: {', '.join(sorted(valid['movement_types']))})"
            )

    if node_type == "CooldownGuard":
        cd = params.get("cooldown_sec")
        if cd is not None and isinstance(cd, (int, float)) and cd <= 0:
            errors.append(f"{node_type}: cooldown_sec must be positive")

    if node_type == "Timeout":
        ds = params.get("duration_sec")
        if ds is not None and isinstance(ds, (int, float)) and ds <= 0:
            errors.append(f"{node_type}: duration_sec must be positive")

    return errors
