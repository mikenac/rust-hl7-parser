"""
rust_hl7_parser
===============

A fast HL7v2 message parser implemented in Rust and exposed to Python via PyO3.

Quick start
-----------
>>> from rust_hl7_parser import parse, parse_json
>>>
>>> msg = parse(
...     "MSH|^~\\\\&|SendingApp|SendingFac|ReceivingApp|ReceivingFac|"
...     "20230101120000||ADT^A01|MSG00001|P|2.3\\r"
...     "PID|1||12345^^^MRN||Doe^John^M||19800101|M"
... )
>>> msg["segments"][0]["name"]
'MSH'

Functions
---------
parse(message, strict=True) -> dict
    Parse an HL7v2 message string and return a nested Python dict.

parse_json(message, strict=True) -> str
    Parse an HL7v2 message string and return a JSON-serialised string.
    Uses the same collapsing logic as parse(). Lossy: components,
    repetitions, and sub-components may all collapse to identical lists.

parse_lossless_json(message, strict=True) -> str
    Parse an HL7v2 message and return a fully lossless JSON string that
    preserves the complete Field → Repetition → Component → SubComponent
    hierarchy. Use for round-trip serialisation, diff tools, and HL7
    editors. More verbose than parse_json().

parse_file(path, strict=True) -> list[dict]
    Parse an HL7v2 file containing one or more messages.
    Handles blank-line separation, MSH-restart separation, and MLLP framing.
    Returns a list of parsed message dicts.

parse_file_json(path, strict=True) -> str
    Parse an HL7v2 file and return a JSON array string.
    Same as parse_file but returns serialized JSON.

parse_batch(messages, strict=True) -> list[dict]
    Parse a list of HL7v2 message strings.
    Returns a list of parsed message dicts, one per input message.

parse_to_json(message, strict=True) -> bytes
    Parse an HL7v2 message and return orjson-encoded bytes.
    Faster than parse_json() for downstream serialisation because orjson
    avoids intermediate Python string allocation.

parse_file_to_json(path, strict=True) -> bytes
    Parse an HL7v2 file and return orjson-encoded bytes.
    Combines the Rust file-parsing path with orjson serialisation.

get(msg, path, *, default=None, rep=None)
    Access a field by HL7 path notation, e.g. get(msg, "PID-5.1").
    Returns only the first repetition for repeating fields; use
    field_reps() to get all repetitions.

field_reps(msg, path) -> list
    Return all repetitions of a repeating field as a list.
    Useful for fields like AL1-5 (reaction codes), IN1-3 (insurer IDs).

segments(msg, name) -> list[dict]
    Return all segment dicts with the given segment name.

field(segment, field_num, component=None, *, subcomponent=None, rep=None)
    Low-level field access on a segment dict (1-based numbering).

all_values(msg, path) -> list
    Collect a field value from every occurrence of the named segment.

first(msg, name) -> dict | None
    Return the first segment with the given name, or None.

parse_annotated(message, *, strict=True, version=None) -> dict
    Parse an HL7v2 message and return an annotated dict with HL7 field names.

parse_annotated_json(message, *, strict=True, version=None) -> str
    Parse an HL7v2 message and return annotated JSON with HL7 field names.

parse_hl7apy_compat(message, *, strict=True) -> dict
    Parse an HL7v2 message and return output compatible with the hl7apy-based
    ``extract_message`` Foundry function.  Field keys use the ``SEGMENT_N``
    convention (e.g. ``PID_5``).  Repeating scalar fields are wrapped as
    ``[["A"], ["B"]]`` to match the hl7apy normalisation.  Returns
    ``{"parsed_message": "<JSON>", "status": "Processed"}`` on success or
    ``{"error": "...", "status": "..."}`` on failure.

All functions accept an optional ``strict`` keyword argument (default
``True``).  When ``strict=False`` the parser operates in lenient mode:
malformed segments are skipped and a ``"warnings"`` key is added to the
returned dict / JSON object listing what was skipped.

Returned structure
------------------
Simple scalar fields collapse to plain strings::

    "SendingApp"          # single string

Fields with multiple components return a list::

    ["Doe", "John", "M"]  # components of "Doe^John^M"

Repeated fields (``~`` separator) keep the full list of repetitions.

The top-level dict always has a ``"segments"`` key whose value is a list of
segment dicts, each with ``"name"`` and ``"fields"`` keys.
"""

from __future__ import annotations

import orjson

from rust_hl7_parser._native import parse, parse_json, parse_lossless_json, parse_file, parse_file_json, parse_batch  # type: ignore[import]
from rust_hl7_parser.validator import validate, validate_file, validate_file_summary
from rust_hl7_parser.accessor import get, segments, field, field_reps, all_values, first
from rust_hl7_parser.annotator import parse_annotated, parse_annotated_json
from rust_hl7_parser.compat import parse_hl7apy_compat


def parse_to_json(message: str, *, strict: bool = True) -> bytes:
    """Parse an HL7v2 message and return orjson-encoded bytes.

    This is a convenience wrapper that calls :func:`parse` and serialises the
    result with ``orjson``, which is significantly faster than the standard
    ``json`` module for large structures.

    Parameters
    ----------
    message:
        The raw HL7v2 message text.
    strict:
        When ``True`` (default) raise ``ValueError`` on any parse error.
        When ``False``, operate in lenient mode.

    Returns
    -------
    bytes
        UTF-8-encoded JSON bytes.
    """
    return orjson.dumps(parse(message, strict=strict))


def parse_file_to_json(path: str, *, strict: bool = True) -> bytes:
    """Parse an HL7v2 file and return orjson-encoded bytes.

    Reads the file via the Rust extension (same logic as :func:`parse_file`),
    then serialises the resulting list of message dicts with ``orjson``.

    Parameters
    ----------
    path:
        Path to the ``.hl7`` file.
    strict:
        When ``True`` (default) raise ``ValueError`` on any parse error.
        When ``False``, operate in lenient mode.

    Returns
    -------
    bytes
        UTF-8-encoded JSON bytes (a JSON array of message objects).
    """
    return orjson.dumps(parse_file(path, strict=strict))


__all__ = [
    "parse",
    "parse_json",
    "parse_lossless_json",
    "parse_file",
    "parse_file_json",
    "parse_batch",
    "parse_to_json",
    "parse_file_to_json",
    "validate",
    "validate_file",
    "validate_file_summary",
    "get",
    "field_reps",
    "segments",
    "field",
    "all_values",
    "first",
    "parse_annotated",
    "parse_annotated_json",
    "parse_hl7apy_compat",
]
__version__ = "0.1.0"
