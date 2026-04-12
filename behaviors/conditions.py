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

    Supports dotted sub-key access: key="navigation.state.nav_state" will
    look up bb["navigation/state"] (a dict) and traverse into ["nav_state"].
    The correct blackboard prefix is resolved at runtime by trying
    progressively shorter prefixes until one returns data.
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

        # Pre-compute all possible prefix keys and register them all.
        # At runtime we'll try each until one has data.
        parts = key.split(".")
        self._candidates = []
        for depth in range(len(parts), 0, -1):
            bb_key = "/".join(parts[:depth])
            sub_keys = parts[depth:]
            self._bb.register_key(
                key=bb_key, access=py_trees.common.Access.READ,
            )
            self._candidates.append((bb_key, sub_keys))

        # Cache: once we find the working prefix, remember it
        self._resolved = None  # (bb_key, sub_keys) or None

    def update(self) -> py_trees.common.Status:
        raw, sub_keys = self._fetch()

        if raw is None:
            if self._default is None:
                self.feedback_message = f"{self._key}: not set"
                return py_trees.common.Status.FAILURE
            raw = self._default
            sub_keys = []

        # Traverse sub-keys into nested dict
        val = raw
        if sub_keys and isinstance(val, dict):
            for seg in sub_keys:
                if isinstance(val, dict) and seg in val:
                    val = val[seg]
                else:
                    val = self._default
                    break

        result = self._op_func(val, self._compare_value)
        self.feedback_message = f"{self._key} {self._operator_name} {self._compare_value}: {result}"
        return py_trees.common.Status.SUCCESS if result else py_trees.common.Status.FAILURE

    def _fetch(self):
        """Try candidate bb keys until one has data. Cache the winner."""
        # Fast path: use cached resolution
        if self._resolved is not None:
            bb_key, sub_keys = self._resolved
            try:
                return self._bb.get(bb_key), sub_keys
            except KeyError:
                # Data disappeared — re-resolve
                self._resolved = None

        # Slow path: try each candidate from longest to shortest
        for bb_key, sub_keys in self._candidates:
            try:
                val = self._bb.get(bb_key)
                self._resolved = (bb_key, sub_keys)
                return val, sub_keys
            except KeyError:
                continue

        return None, []


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
