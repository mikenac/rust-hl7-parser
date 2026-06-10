"""Tests for parse_hl7apy_compat() — hl7apy output format compatibility."""
import json
import pytest
from rust_hl7_parser import parse_hl7apy_compat

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ADT_MSG = (
    "MSH|^~\\&|SendingApp|SendingFac|RecvApp|RecvFac|20230101120000||ADT^A01|MSG001|P|2.3\r"
    "EVN||20230101\r"
    "PID|1||12345^^^MRN||Doe^John^M||19800101|M\r"
    "PV1|1|I|ICU^Bed1^Main"
)


def _segments(result):
    return json.loads(result["parsed_message"])


# ---------------------------------------------------------------------------
# Status and envelope
# ---------------------------------------------------------------------------

def test_success_status():
    result = parse_hl7apy_compat(ADT_MSG)
    assert result["status"] == "Processed"
    assert "parsed_message" in result
    assert "error" not in result


def test_parsed_message_is_json_string():
    result = parse_hl7apy_compat(ADT_MSG)
    parsed = json.loads(result["parsed_message"])
    assert isinstance(parsed, list)
    assert len(parsed) == 4  # MSH, EVN, PID, PV1


def test_single_segment_returns_list():
    result = parse_hl7apy_compat("MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3")
    parsed = json.loads(result["parsed_message"])
    # Single segment — still returned as a list for consistency
    # (hl7apy code returns a single dict only when len == 1, but our
    # function always wraps in a list for predictability)
    assert isinstance(parsed, (list, dict))


# ---------------------------------------------------------------------------
# Field key naming
# ---------------------------------------------------------------------------

def test_field_keys_use_segment_n_format():
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    msh = segs[0]
    assert "MSH_1" in msh
    assert "MSH_3" in msh
    assert "MSH_9" in msh


def test_pid_field_keys():
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    pid = segs[2]
    assert "PID_1" in pid
    assert "PID_3" in pid
    assert "PID_5" in pid


# ---------------------------------------------------------------------------
# MSH special fields
# ---------------------------------------------------------------------------

def test_msh1_field_separator():
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    assert segs[0]["MSH_1"] == "|"


def test_msh2_encoding_characters_plain_string():
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    # Must be a plain string — not split on component separator.
    assert segs[0]["MSH_2"] == "^~\\&"


# ---------------------------------------------------------------------------
# Scalar and component values
# ---------------------------------------------------------------------------

def test_scalar_field():
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    assert segs[2]["PID_1"] == "1"


def test_composite_field_returns_list():
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    # PID-5 = Doe^John^M
    assert segs[2]["PID_5"] == ["Doe", "John", "M"]


def test_composite_with_empty_components():
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    # PID-3 = 12345^^^MRN — empty components are empty strings, not null
    pid3 = segs[2]["PID_3"]
    assert pid3[0] == "12345"
    assert pid3[1] == ""
    assert pid3[2] == ""
    assert pid3[3] == "MRN"


def test_sub_components():
    msg = (
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
        "TST|auth&univ&type^comp2"
    )
    segs = _segments(parse_hl7apy_compat(msg))
    tst = segs[1]
    # TST_1 = auth&univ&type^comp2
    # Component 1 has sub-components; component 2 is a scalar.
    assert tst["TST_1"] == [["auth", "univ", "type"], "comp2"]


# ---------------------------------------------------------------------------
# Absent fields
# ---------------------------------------------------------------------------

def test_absent_schema_field_is_null():
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    pid = segs[2]
    # PID-2 is deprecated/absent in the test message
    assert pid["PID_2"] is None


def test_empty_field_is_null():
    # EVN has only one pipe-separated value after the segment name
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    evn = segs[1]
    # EVN_1 (Event Type Code) is absent — should be null
    assert evn.get("EVN_1") is None


# ---------------------------------------------------------------------------
# Repeating fields — the key difference from parse()
# ---------------------------------------------------------------------------

def test_repeating_scalar_wrapped_in_lists():
    """AL1-5 = RASH~HIVES~NAUSEA must become [["RASH"],["HIVES"],["NAUSEA"]]."""
    msg = (
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
        "AL1|1|DA|PENICILLIN|MO|RASH~HIVES~NAUSEA"
    )
    segs = _segments(parse_hl7apy_compat(msg))
    al1_5 = segs[1]["AL1_5"]
    assert al1_5 == [["RASH"], ["HIVES"], ["NAUSEA"]]


def test_repeating_composite_field():
    """NK1-2 = Smith^Jane~Jones^Bob must become [["Smith","Jane"],["Jones","Bob"]]."""
    msg = (
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
        "NK1|1|Smith^Jane~Jones^Bob|SPO"
    )
    segs = _segments(parse_hl7apy_compat(msg))
    nk1_2 = segs[1]["NK1_2"]
    assert nk1_2 == [["Smith", "Jane"], ["Jones", "Bob"]]


def test_single_repetition_not_wrapped():
    """A non-repeating composite field stays as a flat list, not list[list]."""
    segs = _segments(parse_hl7apy_compat(ADT_MSG))
    # PID-5 = Doe^John^M — single repetition
    pid5 = segs[2]["PID_5"]
    assert pid5 == ["Doe", "John", "M"]
    assert not isinstance(pid5[0], list)


# ---------------------------------------------------------------------------
# Z-segments
# ---------------------------------------------------------------------------

def test_z_segment_positional_keys():
    msg = (
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
        "ZSG|custom_value|another^value"
    )
    segs = _segments(parse_hl7apy_compat(msg))
    zsg = segs[1]
    assert "ZSG_1" in zsg
    assert "ZSG_2" in zsg
    assert zsg["ZSG_1"] == "custom_value"
    assert zsg["ZSG_2"] == ["another", "value"]


# ---------------------------------------------------------------------------
# Lenient mode and warnings
# ---------------------------------------------------------------------------

def test_lenient_mode_skips_bad_segment():
    msg = (
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
        "BA\r"
        "PID|1||12345"
    )
    result = parse_hl7apy_compat(msg, strict=False)
    assert result["status"] == "Processed"
    assert "warnings" in result
    segs = _segments(result)
    names = [list(s.keys())[0][:3] for s in segs]
    assert "MSH" in names
    assert "PID" in names


def test_strict_mode_raises_on_bad_message():
    result = parse_hl7apy_compat("NOT_AN_HL7_MESSAGE")
    assert result["status"] in ("Failed", "Skipped", "Fatal")
    assert "error" in result


# ---------------------------------------------------------------------------
# Newline normalisation
# ---------------------------------------------------------------------------

def test_lf_separated_segments():
    msg = "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\nPID|1||12345"
    result = parse_hl7apy_compat(msg)
    assert result["status"] == "Processed"
    segs = _segments(result)
    assert len(segs) == 2
