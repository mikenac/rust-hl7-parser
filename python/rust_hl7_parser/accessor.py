"""
HL7v2 Path Accessor
===================

Pure-Python accessor layer for navigating parsed HL7v2 message dicts using
HL7 path notation (e.g. ``"PID-5.1"``, ``"OBX[2]-5"``).

All field/component/sub-component numbering follows the HL7 convention: 1-based.

Usage::

    from rust_hl7_parser import parse, get, segments, field, all_values, first

    msg = parse("MSH|^~\\\\&|App|Fac||||ADT^A01|1|P|2.3\\rPID|1||12345^^^MRN||Doe^John^M")

    get(msg, "PID-5.1")          # "Doe"
    get(msg, "PID-3.4")          # "MRN"
    get(msg, "MSH-9.1")          # "ADT"
    all_values(msg, "OBX-5")     # list of values across all OBX segments
"""

from __future__ import annotations

import re
from typing import Any

# Path grammar:
#   seg_name [ "[" occurrence "]" ] "-" field_num [ "." component [ "." subcomponent ] ]
# All numbers are 1-based.
_PATH_RE = re.compile(
    r'^([A-Z][A-Z0-9]{0,2})(?:\[(\d+)\])?-(\d+)(?:\.(\d+)(?:\.(\d+))?)?$'
)


def segments(msg: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """Return all segment dicts whose ``"name"`` matches *name*.

    Parameters
    ----------
    msg:
        Parsed message dict as returned by ``parse()``.
    name:
        Segment name, e.g. ``"PID"``, ``"OBX"``.

    Returns
    -------
    list[dict]
        Possibly-empty list of matching segment dicts.
    """
    return [s for s in msg.get("segments", []) if s.get("name") == name]


def first(msg: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Return the first segment with the given name, or None.

    Parameters
    ----------
    msg:
        Parsed message dict.
    name:
        Segment name, e.g. ``"PID"``.

    Returns
    -------
    dict | None
    """
    for s in msg.get("segments", []):
        if s.get("name") == name:
            return s
    return None


def field(
    segment: dict[str, Any],
    field_num: int,
    component: int | None = None,
    *,
    subcomponent: int | None = None,
    rep: int | None = None,
) -> Any:
    """Low-level field accessor on a single segment dict.

    All numbering is 1-based (HL7 convention).

    Parameters
    ----------
    segment:
        A segment dict from ``msg["segments"]``.
    field_num:
        1-based field number.
    component:
        1-based component number within the field. When None, return the
        whole field value.
    subcomponent:
        1-based sub-component number. Only meaningful when *component* is
        also given.
    rep:
        1-based repetition index for repeating fields. When None and the
        field has multiple repetitions, returns the first.

    Returns
    -------
    Any
        String value, or None if the field/component is absent.
    """
    fields_list: list[Any] = segment.get("fields", [])
    idx = field_num - 1
    if idx < 0 or idx >= len(fields_list):
        return None

    value: Any = fields_list[idx]

    # --- repetition handling ---
    # The Rust parser returns a list-of-lists when a field has multiple
    # repetitions, each repetition being a list of components (or a single
    # string if it collapsed to a scalar).  A single-repetition composite
    # is a plain list of strings.
    if isinstance(value, list) and value and isinstance(value[0], list):
        # Multi-repetition field: [[comp1, comp2], [comp1, comp2], ...]
        rep_idx = (rep - 1) if rep is not None else 0
        if rep_idx < 0 or rep_idx >= len(value):
            return None
        value = value[rep_idx]
    elif rep is not None and rep != 1:
        # Single-repetition field requested with rep > 1 — out of range.
        return None

    # At this point *value* is either:
    #   - a plain string (scalar field)
    #   - a list of strings (component field, one repetition)

    if component is None:
        # Return the whole field.
        if isinstance(value, list):
            # Return the first component for a pure-scalar request on a
            # composite field (mirrors _extract_field_value behaviour).
            return value[0] if value else None
        return value

    # Component access.
    comp_idx = component - 1
    if isinstance(value, str):
        # Scalar field treated as a single-component field.
        return value if comp_idx == 0 else None
    if not isinstance(value, list):
        return None
    if comp_idx < 0 or comp_idx >= len(value):
        return None

    comp_value: Any = value[comp_idx]

    if subcomponent is None:
        if isinstance(comp_value, list):
            return comp_value[0] if comp_value else None
        return comp_value

    # Sub-component access.
    sub_idx = subcomponent - 1
    if isinstance(comp_value, list):
        if sub_idx < 0 or sub_idx >= len(comp_value):
            return None
        return comp_value[sub_idx]
    # Scalar component: only sub-component 1 is valid.
    return comp_value if sub_idx == 0 else None


def get(
    msg: dict[str, Any],
    path: str,
    *,
    default: Any = None,
    rep: int | None = None,
) -> Any:
    """Access a field in a parsed HL7v2 message by HL7 path notation.

    Path format::

        SEG[-N]-FIELD[.COMPONENT[.SUBCOMPONENT]]

    All numbers are 1-based.  Optional occurrence ``[N]`` selects which
    repetition of the segment to use (default: first).

    Parameters
    ----------
    msg:
        Parsed message dict as returned by ``parse()``.
    path:
        HL7 path string, e.g. ``"PID-5.1"``, ``"OBX[2]-5"``.
    default:
        Value to return when the path exists but the field is absent.
        Defaults to None.
    rep:
        1-based repetition index for repeating *fields* (the ``~``
        separator).  Distinct from the segment occurrence in the path.

    Returns
    -------
    Any
        String value, *default* if absent, or raises ``ValueError`` for an
        invalid path.

    Raises
    ------
    ValueError
        When *path* does not match the expected grammar.
    """
    m = _PATH_RE.match(path)
    if m is None:
        raise ValueError(
            f"Invalid HL7 path: {path!r}. "
            "Expected format: SEG-N, SEG-N.C, SEG[K]-N.C.S, etc."
        )

    seg_name: str = m.group(1)
    occurrence_str: str | None = m.group(2)
    field_num: int = int(m.group(3))
    component_str: str | None = m.group(4)
    subcomponent_str: str | None = m.group(5)

    occurrence: int = int(occurrence_str) if occurrence_str is not None else 1
    component: int | None = int(component_str) if component_str is not None else None
    subcomponent: int | None = int(subcomponent_str) if subcomponent_str is not None else None

    matching = segments(msg, seg_name)
    seg_idx = occurrence - 1
    if seg_idx < 0 or seg_idx >= len(matching):
        return default

    result = field(
        matching[seg_idx],
        field_num,
        component,
        subcomponent=subcomponent,
        rep=rep,
    )
    return result if result is not None else default


def all_values(msg: dict[str, Any], path: str) -> list[Any]:
    """Collect a field value from every occurrence of the named segment.

    Parameters
    ----------
    msg:
        Parsed message dict.
    path:
        HL7 path string.  Any occurrence index (``[N]``) in the path is
        ignored; all occurrences are iterated.

    Returns
    -------
    list
        One entry per matching segment, in document order.  Entries where
        the field is absent are omitted.
    """
    m = _PATH_RE.match(path)
    if m is None:
        raise ValueError(
            f"Invalid HL7 path: {path!r}. "
            "Expected format: SEG-N, SEG-N.C, SEG[K]-N.C.S, etc."
        )

    seg_name: str = m.group(1)
    field_num: int = int(m.group(3))
    component_str: str | None = m.group(4)
    subcomponent_str: str | None = m.group(5)

    component: int | None = int(component_str) if component_str is not None else None
    subcomponent: int | None = int(subcomponent_str) if subcomponent_str is not None else None

    results: list[Any] = []
    for seg in segments(msg, seg_name):
        val = field(seg, field_num, component, subcomponent=subcomponent)
        if val is not None:
            results.append(val)
    return results
