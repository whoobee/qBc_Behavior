"""Known MQTT topics catalog for the qB_Companion system.

Used by the BT creator GUI to populate topic dropdowns and
help users build blackboard bindings and action nodes.
"""

# All known input topics (subscribe-able) grouped by subsystem
INPUT_TOPICS = {
    "Audio": {
        "robot/audio/state": {
            "description": "Audio service state (retained)",
            "category": "state",
            "fields": {
                "status": "str (online/offline)",
                "listening": "bool",
                "recording": "bool",
                "playing": "bool",
                "triggered": "bool",
            },
        },
        "robot/audio/wake_word": {
            "description": "Wake word detected event",
            "category": "event",
            "fields": {
                "model": "str",
                "score": "float (0-1)",
            },
        },
        "robot/audio/recording_ready": {
            "description": "Voice recording completed event",
            "category": "event",
            "fields": {
                "file": "str (path to WAV)",
            },
        },
        "robot/system/heartbeat/audio": {
            "description": "Audio service heartbeat (1Hz)",
            "category": "heartbeat",
        },
    },
    "Vision": {
        "robot/vision/state": {
            "description": "Vision service state (retained)",
            "category": "state",
            "fields": {
                "status": "str (online/offline)",
                "streaming": "bool",
                "displaying": "bool",
                "recording_video": "bool",
            },
        },
        "robot/vision/frame_ready": {
            "description": "Frame captured event",
            "category": "event",
            "fields": {
                "file": "str (path to JPEG)",
            },
        },
        "robot/vision/video_ready": {
            "description": "Video recording completed event",
            "category": "event",
            "fields": {
                "file": "str (path to MP4)",
            },
        },
        "robot/system/heartbeat/vision": {
            "description": "Vision service heartbeat (1Hz)",
            "category": "heartbeat",
        },
    },
    "Animation": {
        "robot/animation/state": {
            "description": "Animation service state (retained)",
            "category": "state",
            "fields": {
                "status": "str (online/offline)",
                "expression": "str",
                "color": "str",
            },
        },
        "robot/system/heartbeat/animation": {
            "description": "Animation service heartbeat (1Hz)",
            "category": "heartbeat",
        },
    },
    "Servos": {
        "robot/joints/status": {
            "description": "Joint position status",
            "category": "state",
            "fields": {
                "joint_name": "str",
                "position": "float (degrees)",
                "moving": "bool",
            },
        },
        "robot/system/heartbeat/servos": {
            "description": "Servo service heartbeat (1Hz)",
            "category": "heartbeat",
        },
    },
    "AI": {
        "robot/ai/state": {
            "description": "AI service overall state (retained)",
            "category": "state",
            "fields": {
                "status": "str (online/offline)",
            },
        },
        "robot/ai/voice/state": {
            "description": "AI voice handler state (retained)",
            "category": "state",
            "fields": {
                "status": "str (online/offline)",
                "processing": "bool",
            },
        },
        "robot/ai/explore/state": {
            "description": "AI exploration handler state (retained)",
            "category": "state",
            "fields": {
                "status": "str (online/offline)",
                "processing": "bool",
            },
        },
        "robot/ai/explore/result": {
            "description": "Exploration analysis result event",
            "category": "event",
            "fields": {
                "analysis": "str (VLM description)",
                "frame": "str (path to analyzed JPEG)",
                "timestamp": "float (epoch seconds)",
            },
        },
        "robot/system/heartbeat/ai": {
            "description": "AI service heartbeat (1Hz)",
            "category": "heartbeat",
        },
    },
    "Safety (planned)": {
        "robot/safety/battery": {
            "description": "Battery status (planned)",
            "category": "state",
            "fields": {
                "level": "int (0-100)",
                "charging": "bool",
                "voltage": "float",
            },
        },
        "robot/safety/temperature": {
            "description": "Temperature status (planned)",
            "category": "state",
            "fields": {
                "cpu_temp": "float (celsius)",
                "ambient_temp": "float (celsius)",
            },
        },
        "robot/safety/imu": {
            "description": "IMU data (planned)",
            "category": "state",
            "fields": {
                "accel_x": "float",
                "accel_y": "float",
                "accel_z": "float",
                "tilt_angle": "float (degrees)",
            },
        },
        "robot/safety/distance": {
            "description": "Distance sensor data (planned)",
            "category": "state",
            "fields": {
                "front": "float (cm)",
                "left": "float (cm)",
                "right": "float (cm)",
            },
        },
    },
}

# All known output topics (publish-able) — these are what BT actions can do
OUTPUT_TOPICS = {
    "Animation": {
        "robot/animation/play": {
            "description": "Play animation / set expression",
            "fields": {
                "expression": "str (happy, sad, curious, angry, idle, ...)",
                "duration": "float (seconds, optional)",
                "color": "str (color name, optional)",
                "joints": "dict (joint_name: position, optional)",
            },
        },
    },
    "Audio": {
        "robot/audio/play": {
            "description": "Play audio file",
            "fields": {
                "file": "str (filename)",
                "volume": "int (0-100)",
                "voice": "bool (voice mode, optional)",
            },
        },
        "robot/audio/cmd": {
            "description": "Audio service command",
            "fields": {
                "command": "str (record, stop_recording, stop_playing, clear_trigger)",
            },
        },
    },
    "Servos": {
        "robot/joints/cmd": {
            "description": "Joint movement command",
            "fields": {
                "type": "str (joint_move_request, joint_animate_request)",
                "joint_name": "str (neck, left_ear, right_ear, ...)",
                "target_position": "float (degrees)",
                "duration": "float (seconds, for animate)",
                "speed": "float (deg/s, for move)",
                "movement_type": "str (linear, quadratic, exponential)",
            },
        },
    },
    "Vision": {
        "robot/vision/cmd": {
            "description": "Vision service command",
            "fields": {
                "command": "str (capture_frame, capture_video, start_stream, ...)",
                "duration": "float (for video, optional)",
            },
        },
    },
    "AI": {
        "robot/ai/explore/cmd": {
            "description": "Trigger AI exploration analysis",
            "fields": {
                "command": "str (explore)",
            },
        },
    },
}


def get_all_input_topics() -> list[dict]:
    """Return flat list of all input topics with metadata."""
    result = []
    for group, topics in INPUT_TOPICS.items():
        for topic, info in topics.items():
            result.append({
                "topic": topic,
                "group": group,
                **info,
            })
    return result


def get_all_output_topics() -> list[dict]:
    """Return flat list of all output topics with metadata."""
    result = []
    for group, topics in OUTPUT_TOPICS.items():
        for topic, info in topics.items():
            result.append({
                "topic": topic,
                "group": group,
                **info,
            })
    return result


def get_default_bb_key(topic: str) -> str:
    """Suggest a blackboard key for a topic.

    e.g., 'robot/audio/state' → 'audio.state'
          'robot/audio/wake_word' → 'events.wake_word'
          'robot/system/heartbeat/audio' → 'heartbeat.audio'
    """
    parts = topic.split("/")
    if "heartbeat" in parts:
        return "heartbeat." + parts[-1]

    # Find category from registry
    for topics in INPUT_TOPICS.values():
        if topic in topics and topics[topic].get("category") == "event":
            return "events." + parts[-1]

    # Default: strip 'robot/' prefix and use dots
    if parts[0] == "robot":
        parts = parts[1:]
    return ".".join(parts)
