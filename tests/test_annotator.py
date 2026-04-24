"""Tests for rust_hl7_parser.annotator — annotated JSON output."""

from __future__ import annotations

import json
from typing import Any

import pytest

from rust_hl7_parser import parse_annotated, parse_annotated_json

# ---------------------------------------------------------------------------
# Shared test messages
# ---------------------------------------------------------------------------

ADT_MSG = (
    "MSH|^~\\&|SendingApp|SendingFac|RecvApp|RecvFac|20230101120000||ADT^A01|MSG00001|P|2.3\r"
    "PID|1||12345^^^MRN||Doe^John^M||19800101|M\r"
    "PV1|1|I|ICU^Bed1^Main"
)

MULTI_OBX = (
    "MSH|^~\\&|Lab|Fac||||ORU^R01|1|P|2.3\r"
    "PID|1||12345\r"
    "OBX|1|NM|WBC||7.2|10*3/uL\r"
    "OBX|2|NM|RBC||4.5|10*6/uL\r"
    "OBX|3|NM|HGB||13.8|g/dL"
)

REPEATING = (
    "MSH|^~\\&|App|Fac||||ADT^A01|1|P|2.3\r"
    "NK1|1|Smith^Jane~Jones^Bob|SPO~EMC"
)

UNKNOWN_SEG = (
    "MSH|^~\\&|App|Fac||||ADT^A01|1|P|2.3\r"
    "ZZZ|custom|data|fields"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_field(seg: dict[str, Any], position: str) -> dict[str, Any] | None:
    """Return the annotated field entry matching *position*, or None."""
    for f in seg.get("fields", []):
        if f["position"] == position:
            return f
    return None


def _seg(ann: dict[str, Any], name: str, occurrence: int = 1) -> dict[str, Any]:
    """Return the N-th (1-based) segment with the given name."""
    count = 0
    for s in ann["segments"]:
        if s["name"] == name:
            count += 1
            if count == occurrence:
                return s
    raise KeyError(f"Segment {name!r} occurrence {occurrence} not found")


# ---------------------------------------------------------------------------
# Scalar fields
# ---------------------------------------------------------------------------

def test_scalar_field_has_name_position_value() -> None:
    """Scalar fields produce a dict with name, position, and string value."""
    ann = parse_annotated(ADT_MSG)
    pid = _seg(ann, "PID")
    f1 = _find_field(pid, "PID-1")
    assert f1 is not None
    assert f1["name"] == "set_id"
    assert f1["position"] == "PID-1"
    assert f1["value"] == "1"


def test_scalar_sex_field() -> None:
    """Administrative sex (PID-8) returns as a scalar string."""
    ann = parse_annotated(ADT_MSG)
    pid = _seg(ann, "PID")
    f8 = _find_field(pid, "PID-8")
    assert f8 is not None
    assert f8["value"] == "M"


# ---------------------------------------------------------------------------
# Composite fields (components)
# ---------------------------------------------------------------------------

def test_composite_field_has_components() -> None:
    """Composite fields (XPN etc.) produce a components list."""
    ann = parse_annotated(ADT_MSG)
    pid = _seg(ann, "PID")
    f5 = _find_field(pid, "PID-5")
    assert f5 is not None
    assert f5["name"] == "patient_name"
    value = f5["value"]
    assert "components" in value


def test_composite_field_component_names_from_datatype() -> None:
    """Component names come from the datatypes.json XPN mapping."""
    ann = parse_annotated(ADT_MSG)
    pid = _seg(ann, "PID")
    f5 = _find_field(pid, "PID-5")
    assert f5 is not None
    components = f5["value"]["components"]
    # XPN: family_name, given_name, middle_name, ...
    assert components[0]["name"] == "family_name"
    assert components[1]["name"] == "given_name"
    assert components[2]["name"] == "middle_name"


def test_composite_field_component_values() -> None:
    """Component values match the parsed message data."""
    ann = parse_annotated(ADT_MSG)
    pid = _seg(ann, "PID")
    f5 = _find_field(pid, "PID-5")
    assert f5 is not None
    components = f5["value"]["components"]
    assert components[0]["value"] == "Doe"
    assert components[1]["value"] == "John"
    assert components[2]["value"] == "M"


def test_composite_field_component_positions() -> None:
    """Component position strings are formatted as 'SEG-N.C'."""
    ann = parse_annotated(ADT_MSG)
    pid = _seg(ann, "PID")
    f5 = _find_field(pid, "PID-5")
    assert f5 is not None
    components = f5["value"]["components"]
    assert components[0]["position"] == "PID-5.1"
    assert components[1]["position"] == "PID-5.2"
    assert components[2]["position"] == "PID-5.3"


def test_cx_field_components() -> None:
    """CX fields (PID-3) produce components named from the CX datatype."""
    ann = parse_annotated(ADT_MSG)
    pid = _seg(ann, "PID")
    f3 = _find_field(pid, "PID-3")
    assert f3 is not None
    value = f3["value"]
    # Could be wrapped in repetitions since PID-3 is repeating and CX is composite.
    if "repetitions" in value:
        components = value["repetitions"][0]["components"]
    else:
        components = value["components"]
    # CX: id_number, check_digit, check_digit_scheme, assigning_authority, ...
    assert components[0]["name"] == "id_number"
    assert components[0]["value"] == "12345"
    assert components[3]["name"] == "assigning_authority"
    assert components[3]["value"] == "MRN"


# ---------------------------------------------------------------------------
# MSH special fields
# ---------------------------------------------------------------------------

def test_msh1_is_field_separator() -> None:
    """MSH-1 is always named 'field_separator' regardless of schema."""
    ann = parse_annotated(ADT_MSG)
    msh = _seg(ann, "MSH")
    f1 = _find_field(msh, "MSH-1")
    assert f1 is not None
    assert f1["name"] == "field_separator"
    assert f1["value"] == "|"


def test_msh2_is_encoding_characters() -> None:
    """MSH-2 is always named 'encoding_characters' regardless of schema."""
    ann = parse_annotated(ADT_MSG)
    msh = _seg(ann, "MSH")
    f2 = _find_field(msh, "MSH-2")
    assert f2 is not None
    assert f2["name"] == "encoding_characters"
    assert f2["value"] == "^~\\&"


def test_msh9_message_type_field() -> None:
    """MSH-9 (Message Type) has component names from MSG/CM datatype."""
    ann = parse_annotated(ADT_MSG)
    msh = _seg(ann, "MSH")
    f9 = _find_field(msh, "MSH-9")
    assert f9 is not None
    value = f9["value"]
    assert "components" in value
    comps = value["components"]
    assert comps[0]["name"] == "message_code"
    assert comps[0]["value"] == "ADT"
    assert comps[1]["name"] == "trigger_event"
    assert comps[1]["value"] == "A01"


# ---------------------------------------------------------------------------
# Repeating fields
# ---------------------------------------------------------------------------

def test_repeating_composite_field_gets_repetitions_wrapper() -> None:
    """Repeating composite fields (e.g. NK1-2 with ~) get a repetitions key."""
    ann = parse_annotated(REPEATING)
    nk1 = _seg(ann, "NK1")
    f2 = _find_field(nk1, "NK1-2")
    assert f2 is not None
    value = f2["value"]
    assert "repetitions" in value, f"Expected 'repetitions' key, got: {list(value.keys())}"


def test_repeating_field_correct_values() -> None:
    """Each repetition in a repeating field contains correct component values."""
    ann = parse_annotated(REPEATING)
    nk1 = _seg(ann, "NK1")
    f2 = _find_field(nk1, "NK1-2")
    assert f2 is not None
    reps = f2["value"]["repetitions"]
    assert len(reps) == 2
    # First rep: Smith^Jane
    assert reps[0]["components"][0]["value"] == "Smith"
    assert reps[0]["components"][1]["value"] == "Jane"
    # Second rep: Jones^Bob
    assert reps[1]["components"][0]["value"] == "Jones"
    assert reps[1]["components"][1]["value"] == "Bob"


def test_repeating_field_component_names() -> None:
    """Repetition components carry XPN datatype names."""
    ann = parse_annotated(REPEATING)
    nk1 = _seg(ann, "NK1")
    f2 = _find_field(nk1, "NK1-2")
    assert f2 is not None
    first_rep = f2["value"]["repetitions"][0]
    assert first_rep["components"][0]["name"] == "family_name"
    assert first_rep["components"][1]["name"] == "given_name"


# ---------------------------------------------------------------------------
# Multiple segments of the same type
# ---------------------------------------------------------------------------

def test_multiple_obx_segments_annotated_independently() -> None:
    """Each OBX segment is annotated independently with correct values."""
    ann = parse_annotated(MULTI_OBX)
    obx_segs = [s for s in ann["segments"] if s["name"] == "OBX"]
    assert len(obx_segs) == 3

    # OBX-5 for each (value field)
    values = []
    for obx in obx_segs:
        f5 = _find_field(obx, "OBX-5")
        assert f5 is not None
        v = f5["value"]
        # Might be wrapped as composite or scalar
        if isinstance(v, str):
            values.append(v)
        elif "components" in v:
            values.append(v["components"][0]["value"])
        else:
            values.append(str(v))
    assert values == ["7.2", "4.5", "13.8"]


# ---------------------------------------------------------------------------
# Version auto-detection
# ---------------------------------------------------------------------------

def test_version_auto_detected_from_msh12() -> None:
    """Version is auto-detected from MSH-12 and used for schema lookup."""
    msg_24 = (
        "MSH|^~\\&|App|Fac||||ADT^A01|1|P|2.4\r"
        "PID|1||12345^^^MRN||Smith^Jane^A"
    )
    ann = parse_annotated(msg_24)
    pid = _seg(ann, "PID")
    f5 = _find_field(pid, "PID-5")
    assert f5 is not None
    # Should still get family_name from XPN
    assert f5["value"]["components"][0]["name"] == "family_name"


def test_version_override_parameter() -> None:
    """version= parameter overrides MSH-12 for schema lookup."""
    ann = parse_annotated(ADT_MSG, version="2.4")
    pid = _seg(ann, "PID")
    f5 = _find_field(pid, "PID-5")
    assert f5 is not None
    assert f5["value"]["components"][0]["name"] == "family_name"


# ---------------------------------------------------------------------------
# Unknown / custom segments
# ---------------------------------------------------------------------------

def test_unknown_segment_gets_fallback_field_names() -> None:
    """Fields in unknown segments fall back to positional 'field_N' names."""
    ann = parse_annotated(UNKNOWN_SEG, strict=False)
    zzz = _seg(ann, "ZZZ")
    f1 = _find_field(zzz, "ZZZ-1")
    assert f1 is not None
    assert f1["name"] == "field_1"
    assert f1["value"] == "custom"


# ---------------------------------------------------------------------------
# parse_annotated_json()
# ---------------------------------------------------------------------------

def test_parse_annotated_json_returns_string() -> None:
    """parse_annotated_json() returns a str."""
    result = parse_annotated_json(ADT_MSG)
    assert isinstance(result, str)


def test_parse_annotated_json_is_valid_json() -> None:
    """parse_annotated_json() output is parseable as JSON."""
    result = parse_annotated_json(ADT_MSG)
    data = json.loads(result)
    assert "segments" in data


def test_parse_annotated_json_roundtrip() -> None:
    """parse_annotated_json() and parse_annotated() produce equivalent data."""
    ann_dict = parse_annotated(ADT_MSG)
    ann_json = json.loads(parse_annotated_json(ADT_MSG))
    assert ann_dict == ann_json


def test_parse_annotated_json_pid5_components() -> None:
    """JSON output contains correct PID-5 components via round-trip."""
    data = json.loads(parse_annotated_json(ADT_MSG))
    pid = next(s for s in data["segments"] if s["name"] == "PID")
    f5 = next(f for f in pid["fields"] if f["position"] == "PID-5")
    comps = f5["value"]["components"]
    assert comps[0]["name"] == "family_name"
    assert comps[0]["value"] == "Doe"


# ---------------------------------------------------------------------------
# Lenient mode
# ---------------------------------------------------------------------------

def test_lenient_mode_does_not_raise_on_unknown_segment() -> None:
    """strict=False does not raise for unknown segments."""
    ann = parse_annotated(UNKNOWN_SEG, strict=False)
    segs = [s["name"] for s in ann["segments"]]
    assert "ZZZ" in segs


# ---------------------------------------------------------------------------
# PV1 location field (PL datatype)
# ---------------------------------------------------------------------------

def test_pv1_location_pl_components() -> None:
    """PV1-3 uses PL datatype and produces correct component names."""
    ann = parse_annotated(ADT_MSG)
    pv1 = _seg(ann, "PV1")
    f3 = _find_field(pv1, "PV1-3")
    assert f3 is not None
    value = f3["value"]
    assert "components" in value
    comps = value["components"]
    # PL: point_of_care, room, bed, ...
    assert comps[0]["name"] == "point_of_care"
    assert comps[0]["value"] == "ICU"
    assert comps[1]["name"] == "room"
    assert comps[1]["value"] == "Bed1"
    assert comps[2]["name"] == "bed"
    assert comps[2]["value"] == "Main"
