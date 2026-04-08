"""Custom composite behaviors."""

import random
import logging

import py_trees

logger = logging.getLogger(__name__)


class RandomSelector(py_trees.composites.Selector):
    """A Selector that shuffles its children order on each new activation.

    Useful for idle personality behaviors where we want variety --
    each time the selector is entered, it picks a random order to
    try its children, rather than always preferring the first.

    Children order is randomized in initialise() (called when the node
    transitions from a non-RUNNING state). While RUNNING, the shuffled
    order is maintained.
    """

    def __init__(self, name: str, memory: bool = False, **kwargs):
        super().__init__(name=name, memory=memory)
        self._shuffled = False

    def initialise(self):
        super().initialise()
        if not self._shuffled:
            random.shuffle(self.children)
            self._shuffled = True

    def stop(self, new_status: py_trees.common.Status):
        super().stop(new_status)
        self._shuffled = False
