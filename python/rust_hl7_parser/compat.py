"""
HL7v2 hl7apy-compatible output
===============================

Produces output in the same format as the hl7apy-based ``extract_message``
Foundry function, making this library a fast drop-in replacement for
applications already consuming that format.

Output schema
-------------

On success::

    {
        "parsed_message": "<JSON string>",
        "status": "Processed"
    }

``parsed_message`` is a JSON-encoded list (one dict per segment, in message
order).  Each segment dict uses ``SEGMENT_N`` keys where *N* is the 1-based
HL7 field number (e.g. ``MSH_3``, ``PID_5``).

Field value encoding
--------------------

+---------------------------------------------------+-----------------------------+
| HL7 field content                                 | Python / JSON value         |
+===================================================+=============================+
| Absent or effectively empty                       | ``null``                    |
+---------------------------------------------------+-----------------------------+
| Single scalar value                               | ``"string"``                |
+---------------------------------------------------+-----------------------------+
| Multiple components (``A^B^C``)                   | ``["A", "B", "C"]``         |
+---------------------------------------------------+-----------------------------+
| Component with sub-components (``A&B^C``)         | ``[["A", "B"], "C"]``       |
+---------------------------------------------------+-----------------------------+
| Repeating scalar (``A~B~C``)                      | ``[["A"], ["B"], ["C"]]``   |
+---------------------------------------------------+-----------------------------+
| Repeating composite (``A^B~C^D``)                 | ``[["A","B"], ["C","D"]]``  |
+---------------------------------------------------+-----------------------------+

The repeating-scalar wrapping (``[["A"], ["B"]]`` rather than ``["A", "B"]``)
is the key difference from ``parse()``.  ``parse_hl7apy_compat()`` uses the
lossless internal representation to distinguish repetitions from components
unambiguously, so it is correct even for fields where the collapsed output is
ambiguous.

MSH-2 (encoding characters) is always returned as a plain string.

Z-segments have no schema definition and are keyed positionally:
``ZSG_1``, ``ZSG_2``, etc.

Schema-defined fields that are absent from the message are ``null``; fields
present in the message but beyond the schema definition are included
positionally.

On failure::

    {"error": "<message>", "status": "Failed" | "Skipped" | "Fatal"}

Notes
-----

The original hl7apy-based function applies two pre-processing steps that are
caller responsibilities here:

1. ``hl7_str.encode("utf-8").decode("unicode_escape")`` — decodes
   double-escaped strings from some Foundry sources.
2. ``normalize_hl7_version(hl7_str)`` — rewrites legacy version strings.

Apply those transforms before calling this function if your input requires
them.
"""

from __future__ import annotations

import json
from typing import Any

from rust_hl7_parser._native import parse_lossless_json as _parse_lossless  # type: ignore[import]
from rust_hl7_parser.validator import SchemaRegistry

_registry = SchemaRegistry()


# ---------------------------------------------------------------------------
# Internal value converters
# ---------------------------------------------------------------------------

def _component_value(sub_components: list[str]) -> str | list[str]:
    """Scalar string for a single sub-component; list for multiple."""
    if len(sub_components) == 1:
        return sub_components[0]
    return sub_components


def _repetition_value(components: list[dict[str, Any]]) -> str | list:
    """Collapse a single repetition to its Python value.

    Single component  → scalar string (or sub-component list).
    Multiple components → list of per-component values.
    """
    if len(components) == 1:
        return _component_value(components[0]["sub_components"])
    return [_component_value(c["sub_components"]) for c in components]


def _field_to_hl7apy(
    lossless_field: dict[str, Any],
    *,
    is_msh2: bool = False,
) -> Any:
    """Convert a single lossless field dict to the hl7apy-compatible value.

    Mirrors the logic of ``parse_field`` + ``parse_segment`` in the original
    hl7apy-based function:

    - Single repetition   → scalar or component list (same as before)
    - Multiple repetitions → list[list]; scalar reps are wrapped in ``[val]``
    - MSH-2               → plain string regardless of structure
    - Effectively empty   → ``None``
    """
    repetitions: list[dict[str, Any]] = lossless_field["repetitions"]

    if not repetitions:
        return None

    if is_msh2:
        # Return encoding characters as a plain string — do not split on
        # component separator, which is itself one of those characters.
        sub = repetitions[0]["components"][0]["sub_components"]
        return sub[0] if sub else ""

    if len(repetitions) == 1:
        val = _repetition_value(repetitions[0]["components"])
        return None if val == "" else val

    # Multiple repetitions: scalars are wrapped in a single-element list so
    # the result is always list[list], matching the hl7apy normalisation step.
    result: list[Any] = []
    for rep in repetitions:
        val = _repetition_value(rep["components"])
        result.append(val if isinstance(val, list) else [val])
    return result


# ---------------------------------------------------------------------------
# Segment converter
# ---------------------------------------------------------------------------

def _segment_to_hl7apy(
    seg: dict[str, Any],
    schema: Any,
) -> dict[str, Any]:
    seg_name: str = seg["name"]
    raw_fields: list[dict[str, Any]] = seg["fields"]
    result: dict[str, Any] = {}

    # Z-segments: no schema, positional keys only.
    if seg_name.startswith("Z"):
        for i, field in enumerate(raw_fields):
            result[f"{seg_name}_{i + 1}"] = _field_to_hl7apy(field)
        return result

    # Standard segment: use schema to determine field count.
    seg_def = schema.segments.get(seg_name) if schema else None
    schema_max = max(seg_def.fields.keys()) if (seg_def and seg_def.fields) else 0
    # Include all schema-defined fields, plus any extra fields actually present.
    max_field = max(schema_max, len(raw_fields))

    for field_num in range(1, max_field + 1):
        key = f"{seg_name}_{field_num}"
        idx = field_num - 1

        if idx >= len(raw_fields):
            # Defined in schema but absent from the message.
            result[key] = None
        else:
            is_msh2 = seg_name == "MSH" and field_num == 2
            result[key] = _field_to_hl7apy(raw_fields[idx], is_msh2=is_msh2)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_hl7apy_compat(hl7_str: str, *, strict: bool = True) -> dict[str, Any]:
    """Parse an HL7v2 message and return output compatible with the hl7apy-based
    ``extract_message`` Foundry function.

    Parameters
    ----------
    hl7_str:
        Raw HL7v2 message text.  ``\\n`` is normalised to ``\\r`` automatically.
        Double-escaped strings (``\\\\r``) and version normalisation are the
        caller's responsibility — apply before calling this function if needed.
    strict:
        When ``True`` (default) raise on any parse error, returning
        ``{"error": ..., "status": "Failed"}``.
        When ``False``, skip malformed segments and continue.

    Returns
    -------
    dict
        ``{"parsed_message": "<JSON str>", "status": "Processed"}`` on success.

        ``{"error": "<message>", "status": "Failed" | "Skipped" | "Fatal"}``
        on failure.

    Examples
    --------
    >>> result = parse_hl7apy_compat(
    ...     "MSH|^~\\\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\\r"
    ...     "PID|1||12345^^^MRN||Doe^John^M||19800101|M"
    ... )
    >>> result["status"]
    'Processed'
    >>> import json
    >>> segments = json.loads(result["parsed_message"])
    >>> segments[1]["PID_5"]        # patient name components
    ['Doe', 'John', 'M']
    >>> segments[1]["PID_2"]        # absent field
    None
    """
    try:
        hl7_str = hl7_str.strip().replace("\n", "\r")

        # Use the lossless representation so repetitions and components are
        # always distinguishable — parse() collapses both to a flat list.
        lossless_str = _parse_lossless(hl7_str, strict=strict)
        msg = json.loads(lossless_str)

        # Detect HL7 version from MSH-12 (lossless field index 11, 0-based).
        version = "2.3"
        for seg in msg.get("segments", []):
            if seg["name"] == "MSH":
                fields = seg["fields"]
                if len(fields) >= 12:
                    reps = fields[11].get("repetitions", [])
                    if reps:
                        v = reps[0]["components"][0]["sub_components"][0]
                        version = v.strip() or "2.3"
                break

        schema = _registry.get_schema(version)
        if schema is None:
            schema = _registry.get_schema(_registry.nearest_version(version))

        warnings: list[str] = msg.get("warnings", [])
        all_segments = [
            _segment_to_hl7apy(seg, schema)
            for seg in msg.get("segments", [])
        ]

        parsed = all_segments[0] if len(all_segments) == 1 else all_segments
        output: dict[str, Any] = {
            "parsed_message": json.dumps(parsed, indent=2),
            "status": "Processed",
        }
        if warnings:
            output["warnings"] = warnings
        return output

    except ValueError as exc:
        return {"error": str(exc), "status": "Failed"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "status": "Fatal"}
