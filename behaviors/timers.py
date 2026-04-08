"""Timer-based behaviors and decorators."""

import time
import logging

import py_trees

logger = logging.getLogger(__name__)


class WaitForEvent(py_trees.behaviour.Behaviour):
    """Return RUNNING until an event arrives on the blackboard, then SUCCESS.

    Returns FAILURE if timeout_sec elapses without an event.
    On initialise(), marks any existing event as consumed so we only
    react to new events arriving after this node starts.
    """

    def __init__(self, name: str, key: str, timeout_sec: float = 10.0,
                 **kwargs):
        super().__init__(name=name)
        self._key = key
        self._timeout = timeout_sec
        self._bb_key = key.replace(".", "/")
        self._start_time = None
        self._bb = self.attach_blackboard_client()
        self._bb.register_key(
            key=self._bb_key, access=py_trees.common.Access.WRITE,
        )

    def initialise(self):
        self._start_time = time.monotonic()
        # Mark any existing event as consumed
        try:
            event = self._bb.get(self._bb_key)
            if event is not None and not event.get("consumed", True):
                event["consumed"] = True
                self._bb.set(self._bb_key, event)
        except KeyError:
            pass

    def update(self) -> py_trees.common.Status:
        elapsed = time.monotonic() - self._start_time

        # Check for new unconsumed event
        try:
            event = self._bb.get(self._bb_key)
            if event is not None and not event.get("consumed", True):
                # Only accept events that arrived after we started
                if event.get("timestamp", 0) >= self._start_time:
                    event["consumed"] = True
                    self._bb.set(self._bb_key, event)
                    self.feedback_message = f"event received ({elapsed:.1f}s)"
                    return py_trees.common.Status.SUCCESS
        except KeyError:
            pass

        if elapsed >= self._timeout:
            self.feedback_message = f"timeout ({self._timeout:.1f}s)"
            return py_trees.common.Status.FAILURE

        self.feedback_message = f"waiting ({elapsed:.1f}/{self._timeout:.1f}s)"
        return py_trees.common.Status.RUNNING


class TimerBehavior(py_trees.behaviour.Behaviour):
    """Return RUNNING for a specified duration, then SUCCESS.

    Useful as a delay/cooldown between actions in a sequence.
    """

    def __init__(self, name: str, duration_sec: float = 1.0, **kwargs):
        super().__init__(name=name)
        self._duration = duration_sec
        self._start_time = None

    def initialise(self):
        self._start_time = time.monotonic()

    def update(self) -> py_trees.common.Status:
        elapsed = time.monotonic() - self._start_time
        if elapsed >= self._duration:
            self.feedback_message = "done"
            return py_trees.common.Status.SUCCESS
        self.feedback_message = f"{elapsed:.1f}/{self._duration:.1f}s"
        return py_trees.common.Status.RUNNING


class CooldownGuard(py_trees.decorators.Decorator):
    """Prevents child from running again within a cooldown period.

    If the cooldown has not elapsed since the child last completed,
    returns FAILURE without ticking the child. Otherwise, passes
    through to the child normally.
    """

    def __init__(self, name: str, child: py_trees.behaviour.Behaviour = None,
                 cooldown_sec: float = 5.0, **kwargs):
        super().__init__(name=name, child=child or py_trees.behaviours.Failure(name="placeholder"))
        self._cooldown = cooldown_sec
        self._last_completion = None

    def tick(self):
        """Override tick to skip child ticking during cooldown."""
        if self.status != py_trees.common.Status.RUNNING:
            self.initialise()

        now = time.monotonic()
        if self._last_completion is not None:
            elapsed = now - self._last_completion
            if elapsed < self._cooldown:
                self.feedback_message = f"cooling down ({elapsed:.1f}/{self._cooldown:.1f}s)"
                new_status = py_trees.common.Status.FAILURE
                self.stop(new_status)
                self.status = new_status
                yield self
                return

        # Not in cooldown — tick child normally, then run update()
        for node in self.decorated.tick():
            yield node

        new_status = self.update()
        if new_status != py_trees.common.Status.RUNNING:
            self.stop(new_status)
        self.status = new_status
        yield self

    def update(self) -> py_trees.common.Status:
        """Pass through child status and track completion time."""
        status = self.decorated.status

        if status in (py_trees.common.Status.SUCCESS, py_trees.common.Status.FAILURE):
            self._last_completion = time.monotonic()

        self.feedback_message = self.decorated.feedback_message
        return status
