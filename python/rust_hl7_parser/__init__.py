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
    Uses the same collapsing logic as parse().

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
    Requires the orjson extra: pip install rust-hl7-parser[orjson]

parse_file_to_json(path, strict=True) -> bytes
    Parse an HL7v2 file and return orjson-encoded bytes.
    Combines the Rust file-parsing path with orjson serialisation.
    Requires the orjson extra: pip install rust-hl7-parser[orjson]

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

try:
    import orjson as _orjson
    _ORJSON_AVAILABLE = True
except ImportError:
    _orjson = None  # type: ignore[assignment]
    _ORJSON_AVAILABLE = False

from rust_hl7_parser._native import parse, parse_json, parse_file, parse_file_json, parse_batch  # type: ignore[import]
from rust_hl7_parser.validator import validate, validate_file, validate_file_summary

_ORJSON_INSTALL_HINT = (
    "The orjson extra is required for this function. "
    "Install it with: pip install rust-hl7-parser[orjson]"
)


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

    Raises
    ------
    ImportError
        If the ``orjson`` extra is not installed.
    """
    if not _ORJSON_AVAILABLE:
        raise ImportError(_ORJSON_INSTALL_HINT)
    return _orjson.dumps(parse(message, strict=strict))  # type: ignore[union-attr]


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

    Raises
    ------
    ImportError
        If the ``orjson`` extra is not installed.
    """
    if not _ORJSON_AVAILABLE:
        raise ImportError(_ORJSON_INSTALL_HINT)
    return _orjson.dumps(parse_file(path, strict=strict))  # type: ignore[union-attr]


__all__ = [
    "parse",
    "parse_json",
    "parse_file",
    "parse_file_json",
    "parse_batch",
    "parse_to_json",
    "parse_file_to_json",
    "validate",
    "validate_file",
    "validate_file_summary",
]
__version__ = "0.1.0"
