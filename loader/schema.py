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


def validate_node(node_type: str, params: dict) -> list[str]:
    """Validate node params against schema. Returns list of error messages."""
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

    return errors
