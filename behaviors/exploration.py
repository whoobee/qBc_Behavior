"""Exploration behaviors — sense, decide, drive primitives.

Currently provides:
  PickFreeDirection — read ToF distances from the blackboard, pick the
                      cardinal direction with the most free space, and
                      write the result back so a downstream Selector
                      can dispatch on it.
"""

import logging

import py_trees

logger = logging.getLogger(__name__)


class PickFreeDirection(py_trees.behaviour.Behaviour):
    """Choose the freest cardinal direction from ToF sensors.

    Reads the dict at the configured blackboard key (default
    `sensors.tof`, expecting `{front_mm, left_mm, right_mm, back_mm}`)
    and writes the picked heading + distance back to the blackboard:
        explore.heading       -> "front" | "left" | "right" | "back"
        explore.distance_mm   -> the picked sensor's reading

    Returns SUCCESS when a direction with `>= min_clearance_mm` is
    found. Returns FAILURE when every direction is blocked — the
    caller can then react (back up, play 'stuck' animation, etc.).
    Sensors with missing/None values are skipped.
    """

    _DIRECTIONS = ("front", "left", "right", "back")

    def __init__(self, name: str,
                 source_key: str = "sensors.tof",
                 output_key: str = "explore",
                 min_clearance_mm: float = 250.0,
                 **kwargs):
        super().__init__(name=name)
        self._source_key = source_key.replace(".", "/")
        self._output_key = output_key.replace(".", "/")
        self._min_clearance = float(min_clearance_mm)

        self._bb = self.attach_blackboard_client()
        self._bb.register_key(
            key=self._source_key, access=py_trees.common.Access.READ,
        )
        self._bb.register_key(
            key=self._output_key, access=py_trees.common.Access.WRITE,
        )

    def update(self) -> py_trees.common.Status:
        try:
            tof = self._bb.get(self._source_key)
        except KeyError:
            self.feedback_message = "no ToF data"
            return py_trees.common.Status.FAILURE

        if not isinstance(tof, dict):
            self.feedback_message = "ToF not a dict"
            return py_trees.common.Status.FAILURE

        candidates = []
        for direction in self._DIRECTIONS:
            d = tof.get(f"{direction}_mm")
            if d is None:
                continue
            try:
                d = float(d)
            except (TypeError, ValueError):
                continue
            if d >= self._min_clearance:
                candidates.append((d, direction))

        if not candidates:
            self.feedback_message = "all blocked"
            self._bb.set(self._output_key, {
                "heading": None, "distance_mm": 0.0, "all_blocked": True,
            })
            return py_trees.common.Status.FAILURE

        candidates.sort(reverse=True)   # max distance first
        best_dist, best_dir = candidates[0]
        self._bb.set(self._output_key, {
            "heading": best_dir,
            "distance_mm": best_dist,
            "all_blocked": False,
        })
        self.feedback_message = f"{best_dir} ({best_dist:.0f} mm)"
        return py_trees.common.Status.SUCCESS
