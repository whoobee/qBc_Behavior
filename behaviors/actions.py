"""Action behaviors that publish MQTT commands."""

import json
import time
import logging

import py_trees

logger = logging.getLogger(__name__)


class _MqttAction(py_trees.behaviour.Behaviour):
    """Base class for behaviors that publish to MQTT.

    Subclasses set self._mqtt_topic and self._mqtt_payload in initialise().
    The MQTT client is injected via set_mqtt_client() after tree construction.
    """

    def __init__(self, name: str, **kwargs):
        super().__init__(name=name)
        self._mqtt_client = None

    def set_mqtt_client(self, client):
        self._mqtt_client = client

    def _publish(self, topic: str, payload: dict, qos: int = 1):
        if self._mqtt_client is None:
            logger.warning("%s: no MQTT client, cannot publish", self.name)
            return
        self._mqtt_client.publish(topic, json.dumps(payload), qos=qos)


class PlayAnimation(_MqttAction):
    """Publish an animation command to robot/animation/play.

    On first tick: publishes the command and starts tracking duration.
    Returns RUNNING while duration elapses, then SUCCESS.
    If no duration: returns SUCCESS immediately after publish.
    """

    TOPIC = "robot/animation/play"

    def __init__(self, name: str, expression: str = None,
                 duration: float = None, color: str = None,
                 joints: dict = None, **kwargs):
        super().__init__(name=name)
        self._expression = expression
        self._duration = duration
        self._color = color
        self._joints = joints
        self._start_time = None
        self._published = False

    def initialise(self):
        self._start_time = None
        self._published = False

    def update(self) -> py_trees.common.Status:
        if not self._published:
            payload = {}
            if self._expression is not None:
                payload["expression"] = self._expression
            if self._duration is not None:
                payload["duration"] = self._duration
            if self._color is not None:
                payload["color"] = self._color
            if self._joints is not None:
                payload["joints"] = self._joints
            self._publish(self.TOPIC, payload)
            self._published = True
            self._start_time = time.monotonic()
            self.feedback_message = f"playing {self._expression or 'animation'}"

            if self._duration is None or self._duration <= 0:
                return py_trees.common.Status.SUCCESS

        elapsed = time.monotonic() - self._start_time
        if elapsed >= self._duration:
            self.feedback_message = "done"
            return py_trees.common.Status.SUCCESS

        self.feedback_message = f"{elapsed:.1f}/{self._duration:.1f}s"
        return py_trees.common.Status.RUNNING


class PlayAudio(_MqttAction):
    """Publish a play audio command to robot/audio/play.

    Returns SUCCESS immediately after publishing.
    """

    TOPIC = "robot/audio/play"

    def __init__(self, name: str, file: str = "",
                 volume: int = 50, **kwargs):
        super().__init__(name=name)
        self._file = file
        self._volume = volume

    def update(self) -> py_trees.common.Status:
        self._publish(self.TOPIC, {
            "file": self._file,
            "volume": self._volume,
        })
        self.feedback_message = f"play {self._file}"
        return py_trees.common.Status.SUCCESS


class MoveJoint(_MqttAction):
    """Publish a joint movement command to robot/joints/cmd.

    On first tick: publishes the command.
    Returns RUNNING while duration elapses, then SUCCESS.
    If no duration: returns SUCCESS immediately.
    """

    TOPIC = "robot/joints/cmd"

    def __init__(self, name: str, joint_name: str = "",
                 target_position: float = 0.0, duration: float = None,
                 movement_type: str = "linear", **kwargs):
        super().__init__(name=name)
        self._joint_name = joint_name
        self._target_position = target_position
        self._duration = duration
        self._movement_type = movement_type
        self._start_time = None
        self._published = False

    def initialise(self):
        self._start_time = None
        self._published = False

    def update(self) -> py_trees.common.Status:
        if not self._published:
            if self._duration is not None and self._duration > 0:
                payload = {
                    "type": "joint_animate_request",
                    "joint_name": self._joint_name,
                    "target_position": self._target_position,
                    "duration": self._duration,
                    "movement_type": self._movement_type,
                }
            else:
                payload = {
                    "type": "joint_move_request",
                    "joint_name": self._joint_name,
                    "target_position": self._target_position,
                    "speed": 30.0,
                    "movement_type": self._movement_type,
                }
            self._publish(self.TOPIC, payload)
            self._published = True
            self._start_time = time.monotonic()
            self.feedback_message = f"moving {self._joint_name}"

            if self._duration is None or self._duration <= 0:
                return py_trees.common.Status.SUCCESS

        elapsed = time.monotonic() - self._start_time
        if elapsed >= self._duration:
            self.feedback_message = "done"
            return py_trees.common.Status.SUCCESS

        self.feedback_message = f"{elapsed:.1f}/{self._duration:.1f}s"
        return py_trees.common.Status.RUNNING


class SendCommand(_MqttAction):
    """Generic MQTT publish behavior for arbitrary commands.

    Returns SUCCESS immediately after publishing.
    This is the escape hatch for commands not covered by specialized behaviors.
    """

    def __init__(self, name: str, topic: str = "",
                 payload: dict = None, qos: int = 1, **kwargs):
        super().__init__(name=name)
        self._topic = topic
        self._payload = payload or {}
        self._qos = qos

    def update(self) -> py_trees.common.Status:
        self._publish(self._topic, self._payload, qos=self._qos)
        self.feedback_message = f"sent to {self._topic}"
        return py_trees.common.Status.SUCCESS
