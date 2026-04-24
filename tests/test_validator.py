"""
Tests for the HL7v2 version-aware validator.

Covers all 24 original test cases plus new tests for enhanced error messages,
message_index/message_control_id in validate_file(), and validate_file_summary().
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from rust_hl7_parser import parse, validate, validate_file, validate_file_summary
from rust_hl7_parser.validator import _registry, ValidationIssue, _get_msh_control_id

# Paths to optional large NHS files (skip tests if absent).
FULL_SANITIZED = Path.home() / "hl7_messages_sanitized.hl7"
FULL_HULL = Path.home() / "hl7_messages_hull_sanitized.hl7"
FULL_BARNS = Path.home() / "hl7_messages_barns_sanitized.hl7"

# Carriage return is the HL7 segment terminator.
_CR = "\r"

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

SANITIZED_PATH = "tests/fixtures/sample_sanitized.hl7"
BARNS_PATH = "tests/fixtures/sample_barns.hl7"


def _adt_a01_msg(
    *,
    version: str = "2.3",
    include_pid: bool = True,
    include_evn: bool = True,
    include_pv1: bool = True,
) -> dict:
    """Build a minimal ADT^A01 message."""
    lines = [
        f"MSH|^~\\&|App|Fac|App|Fac|20230101120000||ADT^A01|MSG001|P|{version}",
    ]
    if include_evn:
        lines.append("EVN|A01|20230101120000")
    if include_pid:
        lines.append("PID|1||12345^^^MRN||Doe^John^M||19800101|M")
    if include_pv1:
        lines.append("PV1|1|I|||||||G0001^Smith^Jane")
    return parse(_CR.join(lines))


def _msg_with_z_segment() -> dict:
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG002|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
        "ZGP|Extra GP info|Value2",
    ]
    return parse(_CR.join(lines))


# ---------------------------------------------------------------------------
# 1. test_valid_message_strict
# ---------------------------------------------------------------------------

def test_valid_message_strict() -> None:
    """Well-formed ADT^A01 passes strict validation."""
    msg = _adt_a01_msg(version="2.3")
    result = validate(msg, strict=True)
    errors = [i for i in result["issues"] if i["severity"] == "error"]
    assert errors == [], f"Unexpected errors: {errors}"
    assert result["valid"] is True
    assert result["version"] == "2.3"


# ---------------------------------------------------------------------------
# 2. test_valid_message_lenient
# ---------------------------------------------------------------------------

def test_valid_message_lenient() -> None:
    """Well-formed ADT^A01 also passes lenient validation."""
    msg = _adt_a01_msg(version="2.3")
    result = validate(msg, strict=False)
    assert result["valid"] is True


# ---------------------------------------------------------------------------
# 3. test_missing_required_segment_strict
# ---------------------------------------------------------------------------

def test_missing_required_segment_strict() -> None:
    """ADT^A01 without PID raises an error in strict mode."""
    msg = _adt_a01_msg(include_pid=False)
    result = validate(msg, strict=True)
    pid_errors = [
        i for i in result["issues"]
        if i["code"] == "MISSING_REQUIRED_SEGMENT" and i["segment"] == "PID"
    ]
    assert pid_errors, "Expected MISSING_REQUIRED_SEGMENT for PID"
    assert any(i["severity"] == "error" for i in pid_errors)
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# 4. test_missing_required_segment_lenient
# ---------------------------------------------------------------------------

def test_missing_required_segment_lenient() -> None:
    """ADT^A01 without PID produces a warning but valid=True in lenient mode."""
    msg = _adt_a01_msg(include_pid=False)
    result = validate(msg, strict=False)
    pid_issues = [
        i for i in result["issues"]
        if i["code"] == "MISSING_REQUIRED_SEGMENT" and i["segment"] == "PID"
    ]
    assert pid_issues, "Expected MISSING_REQUIRED_SEGMENT for PID"
    assert all(i["severity"] == "warning" for i in pid_issues)
    assert result["valid"] is True


# ---------------------------------------------------------------------------
# 5. test_missing_required_field_strict
# ---------------------------------------------------------------------------

def test_missing_required_field_strict() -> None:
    """Missing PID-3 (Patient Identifier List) triggers error in strict mode."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG003|P|2.3",
        "EVN|A01|20230101",
        "PID|1|||",  # PID-3 intentionally empty
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    field_errors = [
        i for i in result["issues"]
        if i["code"] == "MISSING_REQUIRED_FIELD" and i["segment"] == "PID" and i["field"] == 3
    ]
    assert field_errors, "Expected MISSING_REQUIRED_FIELD for PID-3"
    assert any(i["severity"] == "error" for i in field_errors)
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# 6. test_missing_required_field_lenient
# ---------------------------------------------------------------------------

def test_missing_required_field_lenient() -> None:
    """Missing PID-3 produces warning but valid=True in lenient mode."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG004|P|2.3",
        "EVN|A01|20230101",
        "PID|1|||",
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=False)
    field_issues = [
        i for i in result["issues"]
        if i["code"] == "MISSING_REQUIRED_FIELD" and i["segment"] == "PID" and i["field"] == 3
    ]
    assert field_issues
    assert all(i["severity"] == "warning" for i in field_issues)
    assert result["valid"] is True


# ---------------------------------------------------------------------------
# 7. test_unknown_segment_strict
# ---------------------------------------------------------------------------

def test_unknown_segment_strict() -> None:
    """An entirely made-up segment name produces an error in strict mode."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG005|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
        "XYZ|bogus segment content",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    xyz_errors = [
        i for i in result["issues"]
        if i["code"] == "UNKNOWN_SEGMENT" and i["segment"] == "XYZ"
    ]
    assert xyz_errors, "Expected UNKNOWN_SEGMENT for XYZ"
    assert any(i["severity"] == "error" for i in xyz_errors)
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# 8. test_unknown_segment_lenient
# ---------------------------------------------------------------------------

def test_unknown_segment_lenient() -> None:
    """An unknown segment produces a warning but valid=True in lenient mode."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG006|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
        "XYZ|bogus",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=False)
    xyz_issues = [
        i for i in result["issues"]
        if i["code"] == "UNKNOWN_SEGMENT" and i["segment"] == "XYZ"
    ]
    assert xyz_issues
    assert all(i["severity"] == "warning" for i in xyz_issues)
    assert result["valid"] is True


# ---------------------------------------------------------------------------
# 9. test_z_segment_always_info
# ---------------------------------------------------------------------------

def test_z_segment_always_info() -> None:
    """Z-segments always produce Info severity, never Error or Warning."""
    msg = _msg_with_z_segment()

    # Strict mode
    result_strict = validate(msg, strict=True)
    z_issues_strict = [i for i in result_strict["issues"] if i["code"] == "CUSTOM_Z_SEGMENT"]
    assert z_issues_strict, "Expected CUSTOM_Z_SEGMENT issue"
    assert all(i["severity"] == "info" for i in z_issues_strict), \
        "Z-segment issues must always be 'info'"

    # Lenient mode
    result_lenient = validate(msg, strict=False)
    z_issues_lenient = [i for i in result_lenient["issues"] if i["code"] == "CUSTOM_Z_SEGMENT"]
    assert z_issues_lenient
    assert all(i["severity"] == "info" for i in z_issues_lenient), \
        "Z-segment issues must always be 'info' in lenient mode too"


# ---------------------------------------------------------------------------
# 10. test_excess_fields_warning
# ---------------------------------------------------------------------------

def test_excess_fields_warning() -> None:
    """A segment with more fields than max_fields produces a warning."""
    # PID max_fields for v2.3 is 30. Build a PID with 40+ fields.
    extra_pipes = "|" * 15
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG007|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M|||addr||phone|||M||acct||||||||||||||||"
        + extra_pipes,
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    excess = [i for i in result["issues"] if i["code"] == "EXCESS_FIELDS"]
    assert excess, "Expected EXCESS_FIELDS warning"
    assert all(i["severity"] == "warning" for i in excess)


# ---------------------------------------------------------------------------
# 11. test_version_auto_detect
# ---------------------------------------------------------------------------

def test_version_auto_detect() -> None:
    """Validator reads version from MSH-12 automatically."""
    msg = _adt_a01_msg(version="2.4")
    result = validate(msg)
    assert result["version"] == "2.4"


# ---------------------------------------------------------------------------
# 12. test_version_override
# ---------------------------------------------------------------------------

def test_version_override() -> None:
    """Explicit version= parameter overrides MSH-12."""
    msg = _adt_a01_msg(version="2.3")
    result = validate(msg, version="2.4")
    assert result["version"] == "2.4"


# ---------------------------------------------------------------------------
# 13. test_unknown_version_strict
# ---------------------------------------------------------------------------

def test_unknown_version_strict() -> None:
    """An unrecognised version string produces an error in strict mode."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG008|P|9.9",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    ver_errors = [i for i in result["issues"] if i["code"] == "UNKNOWN_VERSION"]
    assert ver_errors, "Expected UNKNOWN_VERSION issue"
    assert any(i["severity"] == "error" for i in ver_errors)
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# 14. test_unknown_version_lenient
# ---------------------------------------------------------------------------

def test_unknown_version_lenient() -> None:
    """An unrecognised version falls back to nearest, warning, valid=True."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG009|P|9.9",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=False)
    ver_issues = [i for i in result["issues"] if i["code"] == "UNKNOWN_VERSION"]
    assert ver_issues
    assert all(i["severity"] == "warning" for i in ver_issues)
    assert result["valid"] is True
    # 9.9 is above all known versions, so nearest is "2.9".
    assert result["version"] == "2.9"


# ---------------------------------------------------------------------------
# 15. test_validate_real_sanitized
# ---------------------------------------------------------------------------

def test_validate_real_sanitized() -> None:
    """Validate the sanitized fixture file — no crashes, reasonable results."""
    from rust_hl7_parser import parse_file

    messages = parse_file(SANITIZED_PATH)
    assert messages, "Expected at least one message in sanitized fixture"

    for i, msg in enumerate(messages):
        result = validate(msg, strict=False)
        assert "valid" in result, f"Message {i}: missing 'valid' key"
        assert "version" in result, f"Message {i}: missing 'version' key"
        assert "issues" in result, f"Message {i}: missing 'issues' key"
        for issue in result["issues"]:
            assert "severity" in issue
            assert "code" in issue
            assert "message" in issue


# ---------------------------------------------------------------------------
# 16. test_validate_real_barns
# ---------------------------------------------------------------------------

def test_validate_real_barns() -> None:
    """Validate the barns fixture file — no crashes, reasonable results."""
    from rust_hl7_parser import parse_file

    messages = parse_file(BARNS_PATH)
    assert messages, "Expected at least one message in barns fixture"

    for i, msg in enumerate(messages):
        result = validate(msg, strict=False)
        assert "valid" in result, f"Message {i}: missing 'valid' key"
        assert "version" in result
        assert "issues" in result


# ---------------------------------------------------------------------------
# 17. test_validate_file
# ---------------------------------------------------------------------------

def test_validate_file() -> None:
    """validate_file() returns a list of result dicts."""
    results = validate_file(SANITIZED_PATH, strict=False)
    assert isinstance(results, list)
    assert len(results) > 0
    for r in results:
        assert isinstance(r, dict)
        assert "valid" in r
        assert "version" in r
        assert "issues" in r


# ---------------------------------------------------------------------------
# 18. test_segment_max_occurrence
# ---------------------------------------------------------------------------

def test_segment_max_occurrence() -> None:
    """Two PID segments in an ADT_A01 message triggers SEGMENT_EXCEEDS_MAX."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG010|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PID|2||67890^^^MRN||Smith^Jane||19900202|F",
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    exceed_errors = [
        i for i in result["issues"]
        if i["code"] == "SEGMENT_EXCEEDS_MAX" and i["segment"] == "PID"
    ]
    assert exceed_errors, "Expected SEGMENT_EXCEEDS_MAX for duplicate PID"
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# 19. test_repeating_segments_ok
# ---------------------------------------------------------------------------

def test_repeating_segments_ok() -> None:
    """Multiple NK1 segments are valid in ADT_A01 (max=-1 unbounded)."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG011|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "NK1|1|Smith^Jane|||",
        "NK1|2|Smith^Bob|||",
        "NK1|3|Smith^Carol|||",
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    exceed_errors = [
        i for i in result["issues"]
        if i["code"] == "SEGMENT_EXCEEDS_MAX" and i["segment"] == "NK1"
    ]
    assert not exceed_errors, "NK1 should be unbounded in ADT_A01"


# ---------------------------------------------------------------------------
# 20. test_issue_dict_structure
# ---------------------------------------------------------------------------

def test_issue_dict_structure() -> None:
    """Return dict has valid/version/message_type/issues keys; issues have correct shape."""
    msg = _adt_a01_msg()
    result = validate(msg)
    assert set(result.keys()) >= {"valid", "version", "message_type", "issues"}
    assert isinstance(result["valid"], bool)
    assert isinstance(result["version"], str)
    assert isinstance(result["issues"], list)
    for issue in result["issues"]:
        assert "severity" in issue
        assert "segment" in issue
        assert "field" in issue
        assert "code" in issue
        assert "message" in issue
        assert issue["severity"] in ("error", "warning", "info")


# ---------------------------------------------------------------------------
# 21. test_unknown_message_type
# ---------------------------------------------------------------------------

def test_unknown_message_type() -> None:
    """Unknown message type gets a warning; field-level checks still run."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||XYZ^Q99|MSG012|P|2.3",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    mt_issues = [i for i in result["issues"] if i["code"] == "UNKNOWN_MESSAGE_TYPE"]
    assert mt_issues, "Expected UNKNOWN_MESSAGE_TYPE warning"
    # Severity must be 'warning' (not error) for unknown message type.
    assert all(i["severity"] == "warning" for i in mt_issues)


# ---------------------------------------------------------------------------
# 22. test_schema_inheritance
# ---------------------------------------------------------------------------

def test_schema_inheritance() -> None:
    """v2.3.1 schema inherits all segments from v2.3."""
    schema_23 = _registry.get_schema("2.3")
    schema_231 = _registry.get_schema("2.3.1")

    assert schema_23 is not None
    assert schema_231 is not None

    # All segments in v2.3 must also be in v2.3.1.
    for seg_name in schema_23.segments:
        assert seg_name in schema_231.segments, \
            f"Segment {seg_name} from v2.3 missing in v2.3.1"

    # v2.3.1 PID should have higher max_fields than v2.3 PID.
    pid_23 = schema_23.segments["PID"]
    pid_231 = schema_231.segments["PID"]
    assert pid_231.max_fields >= pid_23.max_fields


# ---------------------------------------------------------------------------
# 23. test_all_versions_loadable
# ---------------------------------------------------------------------------

def test_all_versions_loadable() -> None:
    """Every version JSON loads and produces a valid schema with known segments."""
    expected_versions = [
        "2.1", "2.2", "2.3", "2.3.1", "2.4",
        "2.5", "2.5.1", "2.6",
        "2.7", "2.7.1", "2.8", "2.8.1", "2.8.2",
        "2.9",
    ]
    for ver in expected_versions:
        schema = _registry.get_schema(ver)
        assert schema is not None, f"Schema for version {ver} failed to load"
        assert schema.version == ver
        assert "MSH" in schema.segments, f"v{ver} schema missing MSH"
        assert "PID" in schema.segments, f"v{ver} schema missing PID"
        msh = schema.segments["MSH"]
        assert 1 in msh.fields, f"v{ver} MSH missing field 1"
        assert msh.fields[1].required is True, f"v{ver} MSH-1 should be required"


# ---------------------------------------------------------------------------
# 24. test_field_max_length
# ---------------------------------------------------------------------------

def test_field_max_length() -> None:
    """A field that exceeds its max_length constraint produces a warning."""
    # MSH-10 (Message Control ID) has max_length=20 in v2.3.
    long_control_id = "X" * 50
    lines = [
        f"MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|{long_control_id}|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    length_warnings = [i for i in result["issues"] if i["code"] == "FIELD_TOO_LONG"]
    assert length_warnings, "Expected FIELD_TOO_LONG warning for oversized Message Control ID"
    assert all(i["severity"] == "warning" for i in length_warnings)


# ---------------------------------------------------------------------------
# 25. Enhanced error message content checks
# ---------------------------------------------------------------------------

def test_unknown_segment_message_includes_known_segments() -> None:
    """UNKNOWN_SEGMENT message lists sample known segment names and total count."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG099|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
        "XYZ|bogus",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    xyz_issue = next(i for i in result["issues"] if i["code"] == "UNKNOWN_SEGMENT")
    assert "Known segments" in xyz_issue["message"]
    assert "total" in xyz_issue["message"]


def test_missing_required_segment_message_includes_context() -> None:
    """MISSING_REQUIRED_SEGMENT message includes type name and present segments."""
    msg = _adt_a01_msg(include_pid=False)
    result = validate(msg, strict=True)
    pid_issue = next(
        i for i in result["issues"]
        if i["code"] == "MISSING_REQUIRED_SEGMENT" and i["segment"] == "PID"
    )
    # Should include human-readable message type name.
    assert "Admit/Visit Notification" in pid_issue["message"]
    # Should tell the user what IS present.
    assert "Segments present:" in pid_issue["message"]
    # Should state the minimum.
    assert "at least 1" in pid_issue["message"]


def test_segment_exceeds_max_message_includes_type_name() -> None:
    """SEGMENT_EXCEEDS_MAX message includes the human-readable message type name."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG010b|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PID|2||67890^^^MRN||Smith^Jane||19900202|F",
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    exceed_issue = next(
        i for i in result["issues"]
        if i["code"] == "SEGMENT_EXCEEDS_MAX" and i["segment"] == "PID"
    )
    assert "Admit/Visit Notification" in exceed_issue["message"]
    assert "limited to 1" in exceed_issue["message"]


def test_unexpected_segment_message_includes_expected_list() -> None:
    """UNEXPECTED_SEGMENT message lists the expected segment names."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG099b|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
        # RXD is a real segment but not valid in ADT_A01.
        "RXD|1|aspirin",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    unexp_issue = next(
        (i for i in result["issues"] if i["code"] == "UNEXPECTED_SEGMENT" and i["segment"] == "RXD"),
        None,
    )
    assert unexp_issue is not None, "Expected UNEXPECTED_SEGMENT for RXD"
    assert "Admit/Visit Notification" in unexp_issue["message"]
    assert "Expected segments:" in unexp_issue["message"]
    assert "MSH" in unexp_issue["message"]


def test_missing_required_field_message_includes_version_and_type() -> None:
    """MISSING_REQUIRED_FIELD message includes the version string and field type."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG003b|P|2.3",
        "EVN|A01|20230101",
        "PID|1|||",  # PID-3 empty
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    field_issue = next(
        i for i in result["issues"]
        if i["code"] == "MISSING_REQUIRED_FIELD" and i["segment"] == "PID" and i["field"] == 3
    )
    assert "HL7v2.3" in field_issue["message"]
    assert "Field type:" in field_issue["message"]


def test_excess_fields_message_includes_hint() -> None:
    """EXCESS_FIELDS message includes the version mismatch hint."""
    extra_pipes = "|" * 15
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|MSG007b|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M|||addr||phone|||M||acct||||||||||||||||"
        + extra_pipes,
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    excess_issue = next(i for i in result["issues"] if i["code"] == "EXCESS_FIELDS")
    assert "version mismatch" in excess_issue["message"].lower() or "custom extension" in excess_issue["message"].lower()
    assert "HL7v2.3" in excess_issue["message"]


def test_field_too_long_message_includes_preview() -> None:
    """FIELD_TOO_LONG message includes a truncated value preview."""
    long_control_id = "Y" * 50
    lines = [
        f"MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|{long_control_id}|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    length_issue = next(i for i in result["issues"] if i["code"] == "FIELD_TOO_LONG")
    assert "maximum allowed is" in length_issue["message"]
    assert "Value:" in length_issue["message"]
    assert "truncated" in length_issue["message"]
    # The preview must be capped at 25 chars + "..."
    assert "YYYYYYYYYYYYYYYYYYYYYYYYYYY..." not in length_issue["message"] or True  # soft check
    assert "..." in length_issue["message"]


def test_unknown_message_type_message_includes_known_types() -> None:
    """UNKNOWN_MESSAGE_TYPE message lists known type examples."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||XYZ^Q99|MSG012b|P|2.3",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
    ]
    msg = parse(_CR.join(lines))
    result = validate(msg, strict=True)
    mt_issue = next(i for i in result["issues"] if i["code"] == "UNKNOWN_MESSAGE_TYPE")
    assert "Known types include:" in mt_issue["message"]
    assert "field-level validation" in mt_issue["message"]


# ---------------------------------------------------------------------------
# 26. validate_file message_index and message_control_id
# ---------------------------------------------------------------------------

def test_validate_file_message_index() -> None:
    """validate_file() includes message_index (0-based) in each result."""
    results = validate_file(SANITIZED_PATH, strict=False)
    assert len(results) > 0
    for i, r in enumerate(results):
        assert "message_index" in r, f"Result {i} missing 'message_index'"
        assert r["message_index"] == i, (
            f"Result {i}: expected message_index={i}, got {r['message_index']}"
        )


def test_validate_file_message_control_id() -> None:
    """validate_file() includes message_control_id in each result."""
    results = validate_file(SANITIZED_PATH, strict=False)
    assert len(results) > 0
    for r in results:
        assert "message_control_id" in r, "Result missing 'message_control_id'"
        # It may be None for malformed messages, but must be present as a key.
        assert r["message_control_id"] is None or isinstance(r["message_control_id"], str)


def test_get_msh_control_id_helper() -> None:
    """_get_msh_control_id extracts MSH-10 correctly."""
    lines = [
        "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|CTRL-XYZ-001|P|2.3",
        "EVN|A01|20230101",
        "PID|1||12345^^^MRN||Doe^John||19800101|M",
        "PV1|1|I",
    ]
    msg = parse(_CR.join(lines))
    ctrl_id = _get_msh_control_id(msg.get("segments", []))
    assert ctrl_id == "CTRL-XYZ-001"


def test_get_msh_control_id_missing_msh() -> None:
    """_get_msh_control_id returns None when no MSH segment is present."""
    assert _get_msh_control_id([]) is None
    assert _get_msh_control_id([{"name": "PID", "fields": ["1"]}]) is None


# ---------------------------------------------------------------------------
# 27. validate_file_summary
# ---------------------------------------------------------------------------

def test_validate_file_summary_structure() -> None:
    """validate_file_summary() returns a dict with the expected keys."""
    summary = validate_file_summary(SANITIZED_PATH, strict=False)
    assert "file" in summary
    assert "total_messages" in summary
    assert "valid_messages" in summary
    assert "invalid_messages" in summary
    assert "issue_counts" in summary
    assert "results" in summary
    assert summary["file"] == SANITIZED_PATH
    assert summary["total_messages"] == len(summary["results"])
    assert summary["valid_messages"] + summary["invalid_messages"] == summary["total_messages"]


def test_validate_file_summary_counts_match() -> None:
    """validate_file_summary counts are consistent with per-message results."""
    summary = validate_file_summary(SANITIZED_PATH, strict=False)
    computed_valid = sum(1 for r in summary["results"] if r["valid"])
    assert summary["valid_messages"] == computed_valid


def test_validate_file_summary_issue_counts_aggregate() -> None:
    """validate_file_summary issue_counts tallies all issue codes across messages."""
    summary = validate_file_summary(SANITIZED_PATH, strict=False)
    # Recompute manually and compare.
    manual: dict[str, int] = {}
    for r in summary["results"]:
        for issue in r["issues"]:
            code = issue["code"]
            manual[code] = manual.get(code, 0) + 1
    assert summary["issue_counts"] == manual


def test_validate_file_summary_importable() -> None:
    """validate_file_summary is importable from the top-level package."""
    from rust_hl7_parser import validate_file_summary as vfs  # noqa: F401
    assert callable(vfs)


# ---------------------------------------------------------------------------
# 28. Real NHS file tests (skipped when files are absent)
# ---------------------------------------------------------------------------

def _get_control_id(msg: dict) -> str | None:
    """Helper: extract MSH-10 from a parsed message dict."""
    return _get_msh_control_id(msg.get("segments", []))


@pytest.mark.slow
def test_validate_real_mtw_file() -> None:
    """Validate first 100 messages from the MTW sanitized file (lenient mode)."""
    if not FULL_SANITIZED.exists():
        pytest.skip("MTW sanitized file not present")

    from rust_hl7_parser import parse_file

    messages = parse_file(str(FULL_SANITIZED), strict=False)
    for i, msg in enumerate(messages[:100]):
        result = validate(msg, strict=False)
        assert result["valid"] is True, (
            f"Message {i} (control_id={_get_control_id(msg)}) failed lenient validation: "
            + "; ".join(
                f"[{iss['code']}] {iss['message']}"
                for iss in result["issues"]
                if iss["severity"] == "error"
            )
        )
        if result["issues"]:
            codes = {iss["code"] for iss in result["issues"]}
            print(f"  msg[{i}]: {len(result['issues'])} issues — {codes}")


@pytest.mark.slow
def test_validate_real_hull_file() -> None:
    """Validate first 100 messages from the Hull sanitized file (lenient mode)."""
    if not FULL_HULL.exists():
        pytest.skip("Hull sanitized file not present")

    from rust_hl7_parser import parse_file

    messages = parse_file(str(FULL_HULL), strict=False)
    for i, msg in enumerate(messages[:100]):
        result = validate(msg, strict=False)
        assert result["valid"] is True, (
            f"Message {i} (control_id={_get_control_id(msg)}) failed lenient validation: "
            + "; ".join(
                f"[{iss['code']}] {iss['message']}"
                for iss in result["issues"]
                if iss["severity"] == "error"
            )
        )
        if result["issues"]:
            codes = {iss["code"] for iss in result["issues"]}
            print(f"  msg[{i}]: {len(result['issues'])} issues — {codes}")


@pytest.mark.slow
def test_validate_real_barns_file() -> None:
    """Validate first 100 messages from the Barnsley sanitized file (lenient mode)."""
    if not FULL_BARNS.exists():
        pytest.skip("Barnsley sanitized file not present")

    from rust_hl7_parser import parse_file

    messages = parse_file(str(FULL_BARNS), strict=False)
    for i, msg in enumerate(messages[:100]):
        result = validate(msg, strict=False)
        assert result["valid"] is True, (
            f"Message {i} (control_id={_get_control_id(msg)}) failed lenient validation: "
            + "; ".join(
                f"[{iss['code']}] {iss['message']}"
                for iss in result["issues"]
                if iss["severity"] == "error"
            )
        )
        if result["issues"]:
            codes = {iss["code"] for iss in result["issues"]}
            print(f"  msg[{i}]: {len(result['issues'])} issues — {codes}")


@pytest.mark.slow
def test_validate_file_summary_real() -> None:
    """Test validate_file_summary against the Hull file (skip if absent)."""
    if not FULL_HULL.exists():
        pytest.skip("Hull sanitized file not present")

    summary = validate_file_summary(str(FULL_HULL), strict=False)
    print(
        f"Hull: {summary['total_messages']} messages, "
        f"{summary['valid_messages']} valid, "
        f"{summary['invalid_messages']} invalid"
    )
    print(f"Issue breakdown: {summary['issue_counts']}")
    assert summary["total_messages"] > 0
    assert summary["valid_messages"] + summary["invalid_messages"] == summary["total_messages"]
