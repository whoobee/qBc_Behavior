# qBc_Behavior

Behavior Tree Engine MQTT Service for the qB-Companion robot. This module is responsible for the robot's high-level decision making, personality, and reaction routines.

![Python](https://img.shields.io/badge/Python-3.13-blue) ![py_trees](https://img.shields.io/badge/Lib-py__trees-yellowgreen)

## Overview

The behavior service uses the `py_trees` library to evaluate a tree of conditions and actions at a fixed tick rate (~30Hz). 

The tree logic is completely decoupled from the code. It is defined in a declarative YAML format. The engine subscribes to various MQTT sensor topics, stores this state in a centralized "Blackboard", and evaluates the tree nodes. Action nodes can then publish commands back to MQTT (e.g., instructing `qBc_Animation` to show a happy face, or `qBc_Servos` to move an ear).

## Architecture

- **`behavior_service.py`**: The main execution engine. Runs the 30Hz tick loop, manages the MQTT connection, and calculates diffs for the visualizer.
- **`loader/`**: Contains `tree_loader.py` which parses YAML tree configurations into instantiated `py_trees` nodes.
- **`behaviors/`**: Contains custom nodes (`mqtt_behaviors.py`) such as:
  - `BlackboardManager`: Maps incoming MQTT payloads to variables on the behavior blackboard.
  - Custom Actions: `PlayAnimation`, `MoveJoint`, `PlayAudio`, `SendCommand`.
  - Custom Conditions: `BlackboardCondition`, `EventCheck`.
- **`trees/`**: Directory containing `.yaml` behavior definitions.

## Usage

```bash
# Setup
cd qBc_Behavior
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run
python3 behavior_service.py --tree trees/default.yaml
```

## MQTT Interface

### Subscribed Topics

- `robot/behavior/cmd`: Accepts commands to manipulate the tree engine.
  - `{"command": "reload"}`: Hot-reloads the current tree from disk.
  - `{"command": "load", "tree": "path/to/other.yaml"}`: Loads a new tree.
- *Dynamic Subscriptions*: The `BlackboardManager` automatically subscribes to any topic required by the YAML configuration to populate the blackboard.

### Published Topics

- `robot/behavior/state`: High-level engine state (`{"status": "online", "tree_name": "...", "tick_rate_actual": 30.1}`).
- `robot/behavior/current_state`: Human-readable state (`running`, `loading_tree`).
- `robot/behavior/tree_state`: A highly specialized topic that broadcasts structural diffs of the behavior tree on every tick. This is consumed by the **BT Visualizer** in `qBc_ConfigurationManager` to render a live, animating graph of the node execution.
- `robot/system/heartbeat/behavior`: 1 Hz keepalive.

## Tree Definition (YAML)

Trees define how the robot reacts. For example:

```yaml
name: "Default Personality"
tick_rate_hz: 30
blackboard:
  - topic: "robot/vision/state"
    key: "vision_online"
    field: "status"

root:
  type: Sequence
  name: "Main Loop"
  children:
    - type: BlackboardCondition
      name: "Is Vision Online?"
      variable: "vision_online"
      operator: "=="
      value: "online"
    - type: PlayAnimation
      name: "Look Happy"
      expression: "happy"
```

Use the **BT Creator** interface in the `qBc_ConfigurationManager` web dashboard to visually design these trees instead of writing YAML by hand.
