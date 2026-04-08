"""Condition behaviors that check blackboard state."""

import operator as op
import time
import logging

import py_trees

logger = logging.getLogger(__name__)

OPERATORS = {
    "==":     op.eq,
    "!=":     op.ne,
    ">":      op.gt,
    "<":      op.lt,
    ">=":     op.ge,
    "<=":     op.le,
    "in":     lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "exists": lambda a, _: a is not None,
}


class BlackboardCondition(py_trees.behaviour.Behaviour):
    """Check a blackboard value against a comparison operator.

    Returns SUCCESS if the comparison is true, FAILURE otherwise.
    Completes within a single tick (condition, not action).
    """

    def __init__(self, name: str, key: str, operator: str,
                 value=None, default=None, **kwargs):
        super().__init__(name=name)
        self._key = key
        self._operator_name = operator
        self._op_func = OPERATORS[operator]
        self._compare_value = value
        self._default = default
        self._bb = self.attach_blackboard_client()
        self._bb.register_key(
            key=self._bb_key, access=py_trees.common.Access.READ,
        )

    @property
    def _bb_key(self) -> str:
        return self._key.replace(".", "/")

    def update(self) -> py_trees.common.Status:
        try:
            raw = self._bb.get(self._bb_key)
        except KeyError:
            raw = self._default
            if raw is None:
                self.feedback_message = f"{self._key}: not set"
                return py_trees.common.Status.FAILURE

        # Support dotted sub-key access into dicts
        val = self._resolve_nested(raw, self._key)

        result = self._op_func(val, self._compare_value)
        self.feedback_message = f"{self._key} {self._operator_name} {self._compare_value}: {result}"
        return py_trees.common.Status.SUCCESS if result else py_trees.common.Status.FAILURE

    def _resolve_nested(self, data, key: str):
        """If key has extra dot segments beyond the bb key, traverse into dict."""
        parts = key.split(".")
        # The bb key is the full dotted path mapped to slashes.
        # But if the stored value is a dict, we might need sub-access.
        # e.g., key="audio.state.listening" stored at bb["audio/state"] as {"listening": True}
        # In that case the BlackboardManager stores the full dict at "audio/state",
        # and we need to dig into "listening".
        # Convention: the bb key registered is the full dotted→slash path.
        # If that key doesn't exist but a prefix does, we traverse.
        if isinstance(data, dict):
            # Check if there are sub-segments we need to traverse
            bb_parts = self._bb_key.split("/")
            remaining = parts[len(bb_parts):]
            val = data
            for seg in remaining:
                if isinstance(val, dict) and seg in val:
                    val = val[seg]
                else:
                    return self._default
            return val
        return data


class EventCheck(py_trees.behaviour.Behaviour):
    """Check if a transient MQTT event has arrived and is unconsumed.

    Events on the blackboard are stored as:
        {"data": {...}, "timestamp": float, "consumed": bool}

    Returns SUCCESS if a fresh unconsumed event exists within max_age_sec.
    """

    def __init__(self, name: str, key: str, max_age_sec: float = 5.0,
                 consume: bool = True, **kwargs):
        super().__init__(name=name)
        self._key = key
        self._max_age = max_age_sec
        self._consume = consume
        self._bb_key = key.replace(".", "/")

    def initialise(self):
        self._bb = self.attach_blackboard_client()
        self._bb.register_key(
            key=self._bb_key, access=py_trees.common.Access.WRITE,
        )

    def update(self) -> py_trees.common.Status:
        try:
            event = self._bb.get(self._bb_key)
        except KeyError:
            self.feedback_message = "no event"
            return py_trees.common.Status.FAILURE

        if event is None or event.get("consumed", True):
            self.feedback_message = "no unconsumed event"
            return py_trees.common.Status.FAILURE

        age = time.monotonic() - event.get("timestamp", 0)
        if age > self._max_age:
            self.feedback_message = f"event too old ({age:.1f}s)"
            return py_trees.common.Status.FAILURE

        if self._consume:
            event["consumed"] = True
            self._bb.set(self._bb_key, event)

        self.feedback_message = f"event fresh ({age:.1f}s)"
        return py_trees.common.Status.SUCCESS


class HeartbeatCheck(py_trees.behaviour.Behaviour):
    """Check if a service heartbeat is recent.

    Heartbeats on the blackboard are stored as float (time.monotonic()).
    Returns SUCCESS if within max_age_sec, FAILURE otherwise.
    """

    def __init__(self, name: str, key: str, max_age_sec: float = 5.0,
                 **kwargs):
        super().__init__(name=name)
        self._key = key
        self._max_age = max_age_sec
        self._bb_key = key.replace(".", "/")
        self._bb = self.attach_blackboard_client()
        self._bb.register_key(
            key=self._bb_key, access=py_trees.common.Access.READ,
        )

    def update(self) -> py_trees.common.Status:
        try:
            last_seen = self._bb.get(self._bb_key)
        except KeyError:
            self.feedback_message = "no heartbeat received"
            return py_trees.common.Status.FAILURE

        age = time.monotonic() - last_seen
        if age > self._max_age:
            self.feedback_message = f"stale ({age:.1f}s)"
            return py_trees.common.Status.FAILURE

        self.feedback_message = f"alive ({age:.1f}s)"
        return py_trees.common.Status.SUCCESS
