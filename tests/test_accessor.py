"""Tests for rust_hl7_parser.accessor — HL7 path accessor functions."""

from __future__ import annotations

import pytest

from rust_hl7_parser import parse
from rust_hl7_parser.accessor import all_values, field, first, get, segments

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adt_msg() -> dict:
    return parse(ADT_MSG)


@pytest.fixture
def multi_obx() -> dict:
    return parse(MULTI_OBX)


@pytest.fixture
def repeating_msg() -> dict:
    return parse(REPEATING)


# ---------------------------------------------------------------------------
# get() — simple field access
# ---------------------------------------------------------------------------

def test_get_simple_field(adt_msg: dict) -> None:
    """get() returns a scalar string for a simple field."""
    result = get(adt_msg, "PID-1")
    assert result == "1"


def test_get_component(adt_msg: dict) -> None:
    """get() returns the correct component of a composite field."""
    assert get(adt_msg, "PID-5.1") == "Doe"
    assert get(adt_msg, "PID-5.2") == "John"
    assert get(adt_msg, "PID-5.3") == "M"


def test_get_msh_fields(adt_msg: dict) -> None:
    """get() handles MSH fields correctly."""
    assert get(adt_msg, "MSH-3") == "SendingApp"
    assert get(adt_msg, "MSH-4") == "SendingFac"
    assert get(adt_msg, "MSH-10") == "MSG00001"
    assert get(adt_msg, "MSH-12") == "2.3"


def test_get_msh9_component(adt_msg: dict) -> None:
    """get() with component index on MSG field (MSH-9)."""
    # MSH-9 = "ADT^A01", components: ["ADT", "A01"]
    assert get(adt_msg, "MSH-9.1") == "ADT"
    assert get(adt_msg, "MSH-9.2") == "A01"


def test_get_subcomponent_cx(adt_msg: dict) -> None:
    """get() returns sub-component from CX field (PID-3 = 12345^^^MRN)."""
    # PID-3 = "12345^^^MRN": components [id_number, "", "", assigning_authority]
    assert get(adt_msg, "PID-3.1") == "12345"
    assert get(adt_msg, "PID-3.4") == "MRN"


def test_get_occurrence_first(multi_obx: dict) -> None:
    """get() with implicit first occurrence returns OBX[1] value."""
    assert get(multi_obx, "OBX-5") == "7.2"


def test_get_occurrence_explicit(multi_obx: dict) -> None:
    """get() with explicit occurrence index selects the correct segment."""
    assert get(multi_obx, "OBX[1]-5") == "7.2"
    assert get(multi_obx, "OBX[2]-5") == "4.5"
    assert get(multi_obx, "OBX[3]-5") == "13.8"


def test_get_missing_segment_returns_default(adt_msg: dict) -> None:
    """get() returns default (None) for a segment that is not present."""
    assert get(adt_msg, "ZZZ-1") is None


def test_get_missing_segment_custom_default(adt_msg: dict) -> None:
    """get() returns the supplied default value for a missing segment."""
    assert get(adt_msg, "ZZZ-1", default="MISSING") == "MISSING"


def test_get_out_of_range_field_returns_default(adt_msg: dict) -> None:
    """get() returns default when field index exceeds segment length."""
    # PID has ~8 fields in this message; field 99 should be absent.
    assert get(adt_msg, "PID-99") is None


def test_get_out_of_range_component_returns_default(adt_msg: dict) -> None:
    """get() returns default when component index exceeds available components."""
    # PID-5 has 3 components; requesting component 10 should return default.
    assert get(adt_msg, "PID-5.10") is None


def test_get_out_of_range_occurrence_returns_default(multi_obx: dict) -> None:
    """get() returns default when occurrence index exceeds matching segment count."""
    assert get(multi_obx, "OBX[10]-5") is None


def test_get_invalid_path_raises_value_error(adt_msg: dict) -> None:
    """get() raises ValueError for a syntactically invalid path."""
    with pytest.raises(ValueError, match="Invalid HL7 path"):
        get(adt_msg, "NOT_VALID")

    with pytest.raises(ValueError, match="Invalid HL7 path"):
        get(adt_msg, "PID")  # missing field number

    with pytest.raises(ValueError, match="Invalid HL7 path"):
        get(adt_msg, "pid-5.1")  # lowercase — fails regex


def test_get_pv1_location_components(adt_msg: dict) -> None:
    """get() returns PL components for PV1-3 (ICU^Bed1^Main)."""
    assert get(adt_msg, "PV1-3.1") == "ICU"
    assert get(adt_msg, "PV1-3.2") == "Bed1"
    assert get(adt_msg, "PV1-3.3") == "Main"


# ---------------------------------------------------------------------------
# get() — repeating fields (rep=)
# ---------------------------------------------------------------------------

def test_get_repeating_field_rep1(repeating_msg: dict) -> None:
    """get() with rep=1 returns first repetition of NK1-2."""
    # NK1-2 = "Smith^Jane~Jones^Bob" — two repetitions of XPN
    val = get(repeating_msg, "NK1-2.1", rep=1)
    assert val == "Smith"


def test_get_repeating_field_rep2(repeating_msg: dict) -> None:
    """get() with rep=2 returns second repetition of NK1-2."""
    val = get(repeating_msg, "NK1-2.1", rep=2)
    assert val == "Jones"


def test_get_repeating_field_out_of_range(repeating_msg: dict) -> None:
    """get() with out-of-range rep returns default."""
    val = get(repeating_msg, "NK1-2.1", rep=99)
    assert val is None


# ---------------------------------------------------------------------------
# segments()
# ---------------------------------------------------------------------------

def test_segments_returns_list(multi_obx: dict) -> None:
    """segments() returns a list of matching segment dicts."""
    obx_segs = segments(multi_obx, "OBX")
    assert isinstance(obx_segs, list)
    assert len(obx_segs) == 3


def test_segments_empty_for_missing(adt_msg: dict) -> None:
    """segments() returns an empty list when no matching segment exists."""
    result = segments(adt_msg, "OBX")
    assert result == []


def test_segments_all_have_correct_name(multi_obx: dict) -> None:
    """Every dict returned by segments() has the requested name."""
    for seg in segments(multi_obx, "OBX"):
        assert seg["name"] == "OBX"


# ---------------------------------------------------------------------------
# field()
# ---------------------------------------------------------------------------

def test_field_1based_numbering(adt_msg: dict) -> None:
    """field() uses 1-based field numbering."""
    pid = first(adt_msg, "PID")
    assert pid is not None
    # PID-1 is set_id = "1"
    assert field(pid, 1) == "1"


def test_field_component_access(adt_msg: dict) -> None:
    """field() with component parameter returns the right component."""
    pid = first(adt_msg, "PID")
    assert pid is not None
    # PID-5 = "Doe^John^M"
    assert field(pid, 5, 1) == "Doe"
    assert field(pid, 5, 2) == "John"
    assert field(pid, 5, 3) == "M"


def test_field_out_of_range_returns_none(adt_msg: dict) -> None:
    """field() returns None for out-of-range field or component."""
    pid = first(adt_msg, "PID")
    assert pid is not None
    assert field(pid, 999) is None
    assert field(pid, 5, 50) is None


def test_field_rep_parameter(repeating_msg: dict) -> None:
    """field() rep= parameter selects the correct repetition."""
    nk1 = first(repeating_msg, "NK1")
    assert nk1 is not None
    # NK1-2 = "Smith^Jane~Jones^Bob"
    assert field(nk1, 2, 1, rep=1) == "Smith"
    assert field(nk1, 2, 1, rep=2) == "Jones"


# ---------------------------------------------------------------------------
# all_values()
# ---------------------------------------------------------------------------

def test_all_values_collects_across_segments(multi_obx: dict) -> None:
    """all_values() returns one value per matching segment."""
    vals = all_values(multi_obx, "OBX-5")
    assert vals == ["7.2", "4.5", "13.8"]


def test_all_values_empty_when_no_segment(adt_msg: dict) -> None:
    """all_values() returns empty list when no matching segment exists."""
    assert all_values(adt_msg, "OBX-5") == []


def test_all_values_invalid_path_raises(adt_msg: dict) -> None:
    """all_values() raises ValueError for an invalid path."""
    with pytest.raises(ValueError, match="Invalid HL7 path"):
        all_values(adt_msg, "bad-path!")


def test_all_values_with_component(multi_obx: dict) -> None:
    """all_values() works with component index in path."""
    obs_ids = all_values(multi_obx, "OBX-3.1")
    # OBX-3 = CE field: identifier^text^coding_system
    # In this message OBX-3 values are "WBC", "RBC", "HGB" (scalars)
    assert obs_ids == ["WBC", "RBC", "HGB"]


# ---------------------------------------------------------------------------
# first()
# ---------------------------------------------------------------------------

def test_first_returns_first_match(multi_obx: dict) -> None:
    """first() returns the first matching segment dict."""
    seg = first(multi_obx, "OBX")
    assert seg is not None
    assert seg["name"] == "OBX"
    # First OBX has set_id "1"
    assert seg["fields"][0] == "1"


def test_first_returns_none_for_missing(adt_msg: dict) -> None:
    """first() returns None when no segment with the given name exists."""
    assert first(adt_msg, "OBX") is None


def test_first_msh(adt_msg: dict) -> None:
    """first() retrieves the MSH segment."""
    msh = first(adt_msg, "MSH")
    assert msh is not None
    assert msh["name"] == "MSH"
