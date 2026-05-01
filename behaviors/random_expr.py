"""Random-expression resolution for action params.

Action params may embed `{{expr}}` placeholders that are evaluated either
at tree load time or at action initialisation, depending on which set of
functions the expression uses.

Two kinds:
  - DYNAMIC (rand, randint, uniform, choice, gauss): re-evaluated every
    time the action node initialises, producing fresh values per tick
    re-entry. Used for live variability.
  - STATIC  (srand, srandint, suniform, schoice, sgauss): evaluated once
    at tree load time and baked into the descriptor / built node. Used
    when you want a random *but stable* value for the lifetime of a run.

Examples:
    "{{rand(0, 100)}}"           -> fresh float each activation
    "{{srand(0, 100)}}"          -> one float, frozen at load time
    "{{schoice(['a','b'])}}"     -> one string, frozen at load time
    "head_{{srandint(1,3)}}"     -> e.g. "head_2", frozen at load time

If the *whole* string is a single `{{expr}}`, the resolved value keeps
its native type. Otherwise each placeholder is stringified and spliced
into the surrounding text. Dicts and lists are walked recursively so
nested params (e.g. SendCommand.payload) are supported.
"""

import logging
import random
import re

logger = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{\{(.+?)\}\}")
_FULL_MATCH = re.compile(r"^\s*\{\{(.+?)\}\}\s*$")

_DYNAMIC_NAMES = {
    "rand":    random.uniform,
    "randint": random.randint,
    "uniform": random.uniform,
    "choice":  random.choice,
    "gauss":   random.gauss,
}

_STATIC_NAMES = {
    "srand":    random.uniform,
    "srandint": random.randint,
    "suniform": random.uniform,
    "schoice":  random.choice,
    "sgauss":   random.gauss,
}

# Set of static identifiers — used to decide whether a placeholder is
# resolved at load time or skipped until runtime.
_STATIC_KEYS = set(_STATIC_NAMES.keys())
_STATIC_TOKEN_RE = re.compile(r"\b(" + "|".join(_STATIC_KEYS) + r")\s*\(")


def _is_static_expr(expr: str) -> bool:
    return bool(_STATIC_TOKEN_RE.search(expr))


def _eval_expr(expr: str, names: dict):
    """Evaluate a single expression against a sandboxed namespace."""
    try:
        return eval(  # noqa: S307 — sandboxed by globals/locals
            expr, {"__builtins__": {}}, names,
        )
    except Exception as e:
        raise ValueError(f"Failed to evaluate '{{{{ {expr} }}}}': {e}") from e


def _resolve(value, names: dict, only_static: bool):
    if isinstance(value, str):
        full = _FULL_MATCH.match(value)
        if full:
            expr = full.group(1).strip()
            if only_static and not _is_static_expr(expr):
                return value
            return _eval_expr(expr, names)
        if _PLACEHOLDER.search(value):
            def _sub(m):
                expr = m.group(1).strip()
                if only_static and not _is_static_expr(expr):
                    return m.group(0)
                return str(_eval_expr(expr, names))
            return _PLACEHOLDER.sub(_sub, value)
        return value
    if isinstance(value, dict):
        return {k: _resolve(v, names, only_static) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, names, only_static) for v in value]
    return value


def resolve(value):
    """Resolve dynamic `{{rand(...)}}` placeholders. Called at runtime
    (action initialise()). Static `{{srand(...)}}` placeholders should
    have already been resolved at load time and won't appear here, but
    we accept both namespaces so a stray static token still works."""
    return _resolve(value, {**_DYNAMIC_NAMES, **_STATIC_NAMES},
                    only_static=False)


def resolve_static(value):
    """Resolve only static `{{srand(...)}}` placeholders, leaving dynamic
    ones untouched. Called by the tree loader on every action's params
    so the descriptor handed to the action constructor has fixed values
    where the YAML asked for srand/schoice/etc."""
    return _resolve(value, _STATIC_NAMES, only_static=True)
