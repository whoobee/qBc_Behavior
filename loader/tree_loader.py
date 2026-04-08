"""YAML behavior tree descriptor loader.

Parses a YAML file and builds a py_trees behaviour tree, using the
node type registry from schema.py.
"""

import logging
from pathlib import Path

import yaml
import py_trees

from loader.schema import (
    NODE_REGISTRY, COMPOSITE_TYPES, DECORATOR_TYPES,
    register_all, validate_node,
)

logger = logging.getLogger(__name__)


class TreeLoadError(Exception):
    """Raised when a tree descriptor cannot be loaded or is invalid."""


class TreeLoader:
    """Loads YAML descriptors and builds py_trees behaviour trees."""

    def __init__(self):
        if not NODE_REGISTRY:
            register_all()

    def load(self, yaml_path: str) -> tuple:
        """Load a YAML descriptor and build the tree.

        Returns:
            (root_behaviour, blackboard_config, tree_meta)
        """
        path = Path(yaml_path)
        if not path.exists():
            raise TreeLoadError(f"File not found: {yaml_path}")

        with open(path) as f:
            desc = yaml.safe_load(f)

        if not isinstance(desc, dict):
            raise TreeLoadError(f"Invalid YAML structure in {yaml_path}")

        tree_meta = desc.get("tree", {})
        bb_config = desc.get("blackboard", {})
        root_desc = desc.get("root")

        if root_desc is None:
            raise TreeLoadError(f"No 'root' section in {yaml_path}")

        errors = self._validate_tree(root_desc)
        if errors:
            msg = f"Validation errors in {yaml_path}:\n" + "\n".join(
                f"  - {e}" for e in errors)
            raise TreeLoadError(msg)

        root = self._build_node(root_desc)
        logger.info(
            "Loaded tree '%s' from %s (%d nodes)",
            tree_meta.get("name", "unnamed"), yaml_path,
            self._count_nodes(root),
        )
        return root, bb_config, tree_meta

    def _build_node(self, desc: dict) -> py_trees.behaviour.Behaviour:
        """Recursively build a py_trees node from a descriptor dict."""
        node_type = desc["type"]
        name = desc["name"]
        params = desc.get("params", {})

        if node_type in DECORATOR_TYPES:
            return self._build_decorator(node_type, name, params, desc)

        if node_type in COMPOSITE_TYPES:
            return self._build_composite(node_type, name, params, desc)

        return self._build_leaf(node_type, name, params)

    def _build_composite(self, node_type: str, name: str, params: dict,
                         desc: dict) -> py_trees.behaviour.Behaviour:
        """Build a composite node (Sequence, Selector, Parallel, etc.)."""
        cls = NODE_REGISTRY[node_type]

        if node_type == "Parallel":
            policy_name = params.get("policy", "SuccessOnAll")
            policy = self._make_parallel_policy(policy_name)
            node = cls(name=name, policy=policy)
        elif node_type in ("Sequence", "Selector"):
            memory = params.get("memory", True)
            node = cls(name=name, memory=memory)
        else:
            # Custom composites (RandomSelector, etc.)
            node = cls(name=name, **params)

        for child_desc in desc.get("children", []):
            child = self._build_node(child_desc)
            node.add_child(child)

        return node

    def _build_decorator(self, node_type: str, name: str, params: dict,
                         desc: dict) -> py_trees.behaviour.Behaviour:
        """Build a decorator node with its single child."""
        child_desc = desc.get("child")
        if not child_desc:
            raise TreeLoadError(
                f"Decorator '{name}' ({node_type}) requires a 'child'")
        child = self._build_node(child_desc)

        if node_type == "CooldownGuard":
            from behaviors.timers import CooldownGuard
            return CooldownGuard(name=name, child=child, **params)

        if node_type == "Timeout":
            duration = params.get("duration_sec", 10.0)
            return py_trees.decorators.Timeout(
                name=name, child=child, duration=duration)

        cls = NODE_REGISTRY[node_type]
        return cls(name=name, child=child)

    def _build_leaf(self, node_type: str, name: str,
                    params: dict) -> py_trees.behaviour.Behaviour:
        """Build a leaf behavior node."""
        cls = NODE_REGISTRY[node_type]
        return cls(name=name, **params)

    def _make_parallel_policy(self, name: str):
        """Create a py_trees parallel policy from a string name."""
        policies = {
            "SuccessOnAll": py_trees.common.ParallelPolicy.SuccessOnAll,
            "SuccessOnOne": py_trees.common.ParallelPolicy.SuccessOnOne,
        }
        policy_cls = policies.get(name)
        if policy_cls is None:
            raise TreeLoadError(f"Unknown parallel policy: {name}")
        return policy_cls()

    def _validate_tree(self, desc: dict, path: str = "root") -> list[str]:
        """Recursively validate a tree descriptor. Returns error messages."""
        errors = []

        if "type" not in desc:
            errors.append(f"{path}: missing 'type'")
            return errors
        if "name" not in desc:
            errors.append(f"{path}: missing 'name'")
            return errors

        node_type = desc["type"]
        name = desc["name"]
        params = desc.get("params", {})
        node_path = f"{path}/{name}"

        # Validate node type exists
        if node_type not in NODE_REGISTRY:
            errors.append(f"{node_path}: unknown type '{node_type}'")
            return errors

        # Validate params
        errors.extend(
            f"{node_path}: {e}"
            for e in validate_node(node_type, params)
        )

        # Validate children
        if node_type in COMPOSITE_TYPES:
            children = desc.get("children", [])
            if not children:
                errors.append(f"{node_path}: composite has no children")
            for i, child_desc in enumerate(children):
                errors.extend(self._validate_tree(
                    child_desc, f"{node_path}[{i}]"))

        elif node_type in DECORATOR_TYPES:
            child_desc = desc.get("child")
            if not child_desc:
                errors.append(f"{node_path}: decorator has no child")
            elif isinstance(child_desc, dict):
                errors.extend(self._validate_tree(
                    child_desc, f"{node_path}/child"))
            else:
                errors.append(f"{node_path}: 'child' must be a single node")

        return errors

    def _count_nodes(self, node: py_trees.behaviour.Behaviour) -> int:
        """Count total nodes in a tree."""
        count = 1
        if hasattr(node, "children"):
            for child in node.children:
                count += self._count_nodes(child)
        return count


def tree_to_dict(node: py_trees.behaviour.Behaviour) -> dict:
    """Serialize a py_trees tree back to a descriptor dict (for the creator)."""
    from loader.schema import COMPOSITE_TYPES, DECORATOR_TYPES

    desc = {
        "type": _get_type_name(node),
        "name": node.name,
    }

    params = _extract_params(node)
    if params:
        desc["params"] = params

    type_name = desc["type"]
    if type_name in COMPOSITE_TYPES:
        desc["children"] = [tree_to_dict(c) for c in node.children]
    elif type_name in DECORATOR_TYPES:
        if hasattr(node, "children") and node.children:
            desc["child"] = [tree_to_dict(node.children[0])]
        elif hasattr(node, "decorated"):
            desc["child"] = [tree_to_dict(node.decorated)]

    return desc


def _get_type_name(node: py_trees.behaviour.Behaviour) -> str:
    """Map a py_trees node instance back to its registry type name."""
    from behaviors.conditions import BlackboardCondition, EventCheck, HeartbeatCheck
    from behaviors.actions import PlayAnimation, PlayAudio, MoveJoint, SendCommand
    from behaviors.timers import WaitForEvent, TimerBehavior, CooldownGuard
    from behaviors.composites import RandomSelector

    type_map = {
        py_trees.composites.Sequence: "Sequence",
        py_trees.composites.Selector: "Selector",
        py_trees.composites.Parallel: "Parallel",
        py_trees.decorators.Inverter: "Inverter",
        py_trees.decorators.Timeout: "Timeout",
        py_trees.decorators.RunningIsSuccess: "RunningIsSuccess",
        py_trees.decorators.FailureIsSuccess: "FailureIsSuccess",
        py_trees.decorators.SuccessIsFailure: "SuccessIsFailure",
        BlackboardCondition: "BlackboardCondition",
        EventCheck: "EventCheck",
        HeartbeatCheck: "HeartbeatCheck",
        PlayAnimation: "PlayAnimation",
        PlayAudio: "PlayAudio",
        MoveJoint: "MoveJoint",
        SendCommand: "SendCommand",
        WaitForEvent: "WaitForEvent",
        TimerBehavior: "TimerBehavior",
        CooldownGuard: "CooldownGuard",
        RandomSelector: "RandomSelector",
    }
    return type_map.get(type(node), type(node).__name__)


def _extract_params(node: py_trees.behaviour.Behaviour) -> dict:
    """Extract constructor params from a node instance for serialization."""
    params = {}

    # Composites
    if isinstance(node, (py_trees.composites.Sequence, py_trees.composites.Selector)):
        if hasattr(node, "memory"):
            params["memory"] = node.memory

    # Custom behaviors store their params as instance attributes
    from behaviors.conditions import BlackboardCondition, EventCheck, HeartbeatCheck
    from behaviors.actions import PlayAnimation, PlayAudio, MoveJoint, SendCommand
    from behaviors.timers import WaitForEvent, TimerBehavior, CooldownGuard

    if isinstance(node, BlackboardCondition):
        params = {
            "key": node._key, "operator": node._operator_name,
            "value": node._compare_value, "default": node._default,
        }
    elif isinstance(node, EventCheck):
        params = {
            "key": node._key, "max_age_sec": node._max_age,
            "consume": node._consume,
        }
    elif isinstance(node, HeartbeatCheck):
        params = {"key": node._key, "max_age_sec": node._max_age}
    elif isinstance(node, PlayAnimation):
        for attr, key in [("_expression", "expression"), ("_duration", "duration"),
                          ("_color", "color"), ("_joints", "joints")]:
            val = getattr(node, attr)
            if val is not None:
                params[key] = val
    elif isinstance(node, PlayAudio):
        params = {"file": node._file, "volume": node._volume}
    elif isinstance(node, MoveJoint):
        params = {
            "joint_name": node._joint_name,
            "target_position": node._target_position,
            "movement_type": node._movement_type,
        }
        if node._duration is not None:
            params["duration"] = node._duration
    elif isinstance(node, SendCommand):
        params = {
            "topic": node._topic, "payload": node._payload,
            "qos": node._qos,
        }
    elif isinstance(node, WaitForEvent):
        params = {"key": node._key, "timeout_sec": node._timeout}
    elif isinstance(node, TimerBehavior):
        params = {"duration_sec": node._duration}
    elif isinstance(node, CooldownGuard):
        params = {"cooldown_sec": node._cooldown}

    return params
