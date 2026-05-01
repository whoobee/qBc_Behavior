"""Action behaviors that publish MQTT commands."""

import json
import time
import logging

import py_trees

from behaviors.random_expr import resolve as resolve_rand

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
        # Resolve {{rand(...)}} placeholders fresh on each activation.
        self._r_expression = resolve_rand(self._expression)
        self._r_duration = resolve_rand(self._duration)
        self._r_color = resolve_rand(self._color)
        self._r_joints = resolve_rand(self._joints)

    def update(self) -> py_trees.common.Status:
        if not self._published:
            payload = {}
            if self._r_expression is not None:
                payload["expression"] = self._r_expression
            if self._r_duration is not None:
                payload["duration"] = self._r_duration
            if self._r_color is not None:
                payload["color"] = self._r_color
            if self._r_joints is not None:
                payload["joints"] = self._r_joints
            self._publish(self.TOPIC, payload)
            self._published = True
            self._start_time = time.monotonic()
            self.feedback_message = f"playing {self._r_expression or 'animation'}"

            if self._r_duration is None or self._r_duration <= 0:
                return py_trees.common.Status.SUCCESS

        elapsed = time.monotonic() - self._start_time
        if elapsed >= self._r_duration:
            self.feedback_message = "done"
            return py_trees.common.Status.SUCCESS

        self.feedback_message = f"{elapsed:.1f}/{self._r_duration:.1f}s"
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

    def initialise(self):
        self._r_file = resolve_rand(self._file)
        self._r_volume = resolve_rand(self._volume)

    def update(self) -> py_trees.common.Status:
        self._publish(self.TOPIC, {
            "file": self._r_file,
            "volume": self._r_volume,
        })
        self.feedback_message = f"play {self._r_file}"
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
        self._r_joint_name = resolve_rand(self._joint_name)
        self._r_target_position = resolve_rand(self._target_position)
        self._r_duration = resolve_rand(self._duration)
        self._r_movement_type = resolve_rand(self._movement_type)

    def update(self) -> py_trees.common.Status:
        if not self._published:
            if self._r_duration is not None and self._r_duration > 0:
                payload = {
                    "type": "joint_animate_request",
                    "joint_name": self._r_joint_name,
                    "target_position": self._r_target_position,
                    "duration": self._r_duration,
                    "movement_type": self._r_movement_type,
                }
            else:
                payload = {
                    "type": "joint_move_request",
                    "joint_name": self._r_joint_name,
                    "target_position": self._r_target_position,
                    "speed": 30.0,
                    "movement_type": self._r_movement_type,
                }
            self._publish(self.TOPIC, payload)
            self._published = True
            self._start_time = time.monotonic()
            self.feedback_message = f"moving {self._r_joint_name}"

            if self._r_duration is None or self._r_duration <= 0:
                return py_trees.common.Status.SUCCESS

        elapsed = time.monotonic() - self._start_time
        if elapsed >= self._r_duration:
            self.feedback_message = "done"
            return py_trees.common.Status.SUCCESS

        self.feedback_message = f"{elapsed:.1f}/{self._r_duration:.1f}s"
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

    def initialise(self):
        self._r_topic = resolve_rand(self._topic)
        self._r_payload = resolve_rand(self._payload)
        self._r_qos = resolve_rand(self._qos)

    def update(self) -> py_trees.common.Status:
        self._publish(self._r_topic, self._r_payload, qos=self._r_qos)
        self.feedback_message = f"sent to {self._r_topic}"
        return py_trees.common.Status.SUCCESS


class DriveWheels(_MqttAction):
    """Continuously drive the wheels in velocity mode.

    Publishes `{left_vel, right_vel}` to robot/wheels/cmd every tick
    (so the motor controller never sees a stale command) and stays in
    RUNNING state forever — the parent (e.g. a Parallel with a Timer
    or obstacle Condition) terminates it. On terminate(), publishes
    `(0, 0)` to bring the wheels to rest.
    """

    TOPIC = "robot/wheels/cmd"

    def __init__(self, name: str, left_vel: float = 0.0,
                 right_vel: float = 0.0, **kwargs):
        super().__init__(name=name)
        self._left_vel = left_vel
        self._right_vel = right_vel

    def initialise(self):
        self._r_left = resolve_rand(self._left_vel)
        self._r_right = resolve_rand(self._right_vel)

    def update(self) -> py_trees.common.Status:
        self._publish(self.TOPIC, {
            "mode": "velocity",
            "left_vel": float(self._r_left),
            "right_vel": float(self._r_right),
        }, qos=0)
        self.feedback_message = f"L={self._r_left:.0f} R={self._r_right:.0f} RPM"
        return py_trees.common.Status.RUNNING

    def terminate(self, new_status):
        # Whatever caused us to stop, leave the wheels at rest.
        self._publish(self.TOPIC, {
            "mode": "velocity", "left_vel": 0.0, "right_vel": 0.0,
        }, qos=0)


# Wheel geometry. delta_deg = distance_mm * 360 / (pi * wheel_diameter_mm)
WHEEL_DIAMETER_MM = 74.5
_MM_PER_WHEEL_DEG = (3.141592653589793 * WHEEL_DIAMETER_MM) / 360.0

# DDSM210 mode-3 (position) accepts an absolute 0-360 target and takes
# the shortest path. To force a direction we cap each chunk to <180 deg
# of wheel rotation (we use 170 to leave headroom). Longer moves are
# split into N sequential chunks issued from update().
_MAX_CHUNK_DEG = 170.0


class DriveDistance(_MqttAction):
    """Drive forward (or backward) a fixed distance using wheel position
    mode.

    The total wheel rotation needed is split into ≤170-degree chunks so
    each individual setPosition call rotates in the intended direction.
    Chunks are issued sequentially over the action's lifetime, with an
    estimated per-chunk duration (derived from speed_rpm) governing how
    long we wait before sending the next one. A parent obstacle check
    (via Parallel SuccessOnOne) can preempt the move, in which case
    our terminate() publishes a velocity-mode (0,0) — that both halts
    the wheels and signals the firmware to reset its position
    accumulator so the next move re-syncs against the encoder.
    """

    TOPIC = "robot/wheels/cmd"

    def __init__(self, name: str, distance_mm: float = 0.0,
                 speed_rpm: float = 30.0,
                 curvature: float = 0.0,
                 timeout_safety_factor: float = 1.6, **kwargs):
        super().__init__(name=name)
        self._distance_mm = distance_mm
        self._speed_rpm = speed_rpm
        self._curvature = curvature
        self._safety_factor = timeout_safety_factor

    def initialise(self):
        import math
        self._r_distance = float(resolve_rand(self._distance_mm))
        self._r_speed = float(resolve_rand(self._speed_rpm))
        # `curvature` biases per-wheel travel: 0 = straight, +1 = pure
        # in-place spin to the right (right wheel idle), -1 = spin left.
        # Clamp to [-1, 1] so a typo can't reverse one wheel.
        c = max(-1.0, min(1.0, float(resolve_rand(self._curvature))))
        self._r_curvature = c
        total_deg = (self._r_distance / _MM_PER_WHEEL_DEG) if _MM_PER_WHEEL_DEG else 0.0
        # Asymmetric wheel deltas. The faster wheel governs chunk count
        # so neither side ever exceeds the 170-deg shortest-path cap.
        self._left_total_deg  = total_deg * (1.0 + c)
        self._right_total_deg = total_deg * (1.0 - c)
        max_abs = max(abs(self._left_total_deg), abs(self._right_total_deg))
        n_chunks = max(1, int(math.ceil(max_abs / _MAX_CHUNK_DEG)))
        self._left_chunk_deg  = self._left_total_deg  / n_chunks
        self._right_chunk_deg = self._right_total_deg / n_chunks
        self._total_chunks = n_chunks
        self._chunks_sent = 0
        self._chunk_start_time = None
        # Per-chunk wait paced by the FASTER wheel (max abs delta).
        chunk_max_abs = max(abs(self._left_chunk_deg),
                            abs(self._right_chunk_deg))
        speed_deg_per_sec = max(1e-3, abs(self._r_speed) * 6.0)
        self._chunk_duration = (
            chunk_max_abs / speed_deg_per_sec * self._safety_factor
        )

    def update(self) -> py_trees.common.Status:
        import time
        now = time.monotonic()

        if self._chunks_sent == 0:
            self._publish_chunk()
            self._chunks_sent = 1
            self._chunk_start_time = now
            self._update_feedback()
            return py_trees.common.Status.RUNNING

        elapsed = now - self._chunk_start_time
        if elapsed < self._chunk_duration:
            self._update_feedback(elapsed)
            return py_trees.common.Status.RUNNING

        # Current chunk window has elapsed
        if self._chunks_sent >= self._total_chunks:
            self.feedback_message = "done"
            return py_trees.common.Status.SUCCESS

        # Send the next chunk
        self._publish_chunk()
        self._chunks_sent += 1
        self._chunk_start_time = now
        self._update_feedback()
        return py_trees.common.Status.RUNNING

    def _publish_chunk(self):
        self._publish(self.TOPIC, {
            "mode": "position",
            "left_delta_deg":  self._left_chunk_deg,
            "right_delta_deg": self._right_chunk_deg,
        }, qos=0)

    def _update_feedback(self, elapsed: float = 0.0):
        self.feedback_message = (
            f"chunk {self._chunks_sent}/{self._total_chunks} "
            f"({self._r_distance:.0f}mm c={self._r_curvature:+.2f})"
        )

    def terminate(self, new_status):
        # On any non-SUCCESS exit (e.g. obstacle preempt) bring wheels
        # to rest and reset the firmware position accumulator.
        if self._chunks_sent > 0 and new_status != py_trees.common.Status.SUCCESS:
            self._publish(self.TOPIC, {
                "mode": "velocity", "left_vel": 0.0, "right_vel": 0.0,
            }, qos=0)
