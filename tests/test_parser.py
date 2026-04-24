"""
Python-level tests for rust_hl7_parser.

Run with:
    pytest tests/
"""

from __future__ import annotations

import json

import pytest

from rust_hl7_parser import parse, parse_json

# ---------------------------------------------------------------------------
# Sample messages
# ---------------------------------------------------------------------------

ADT_MSG = (
    "MSH|^~\\&|SendingApp|SendingFac|ReceivingApp|ReceivingFac|"
    "20230101120000||ADT^A01|MSG00001|P|2.3\r"
    "PID|1||12345^^^MRN||Doe^John^M||19800101|M"
)

MULTI_OBX_MSG = (
    "MSH|^~\\&|SendingApp|SendingFac|ReceivingApp|ReceivingFac|"
    "20230101120000||ADT^A01|MSG00001|P|2.3\r"
    "PID|1||12345^^^MRN||Doe^John^M||19800101|M\r"
    "OBX|1|NM|1234^HeartRate||72|bpm|60-100|N|||F\r"
    "OBX|2|NM|5678^Temp||98.6|F|97-99|N|||F"
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def segment_by_name(result: dict, name: str) -> list[dict]:
    """Return all segments with the given name."""
    return [s for s in result["segments"] if s["name"] == name]


# ---------------------------------------------------------------------------
# 1. Basic ADT message
# ---------------------------------------------------------------------------


class TestBasicADT:
    def test_segment_count(self) -> None:
        result = parse(ADT_MSG)
        assert len(result["segments"]) == 2

    def test_segment_names(self) -> None:
        result = parse(ADT_MSG)
        names = [s["name"] for s in result["segments"]]
        assert names == ["MSH", "PID"]

    def test_msh_sending_app(self) -> None:
        result = parse(ADT_MSG)
        msh = result["segments"][0]
        # MSH fields: index 0=MSH-1, 1=MSH-2, 2=MSH-3(SendingApp)
        assert msh["fields"][2] == "SendingApp"

    def test_msh_sending_facility(self) -> None:
        result = parse(ADT_MSG)
        msh = result["segments"][0]
        assert msh["fields"][3] == "SendingFac"

    def test_msh_datetime(self) -> None:
        result = parse(ADT_MSG)
        msh = result["segments"][0]
        assert msh["fields"][6] == "20230101120000"

    def test_pid_patient_id(self) -> None:
        result = parse(ADT_MSG)
        pid = result["segments"][1]
        # PID-1 = "1"
        assert pid["fields"][0] == "1"

    def test_pid_sex(self) -> None:
        result = parse(ADT_MSG)
        pid = result["segments"][1]
        # PID-8 = "M" (sex)
        assert pid["fields"][7] == "M"


# ---------------------------------------------------------------------------
# 2. Multiple OBX segments
# ---------------------------------------------------------------------------


class TestMultipleOBX:
    def test_obx_count(self) -> None:
        result = parse(MULTI_OBX_MSG)
        obx_segs = segment_by_name(result, "OBX")
        assert len(obx_segs) == 2

    def test_obx_sequence_numbers(self) -> None:
        result = parse(MULTI_OBX_MSG)
        obx_segs = segment_by_name(result, "OBX")
        assert obx_segs[0]["fields"][0] == "1"
        assert obx_segs[1]["fields"][0] == "2"

    def test_obx_values(self) -> None:
        result = parse(MULTI_OBX_MSG)
        obx_segs = segment_by_name(result, "OBX")
        # OBX-5 (index 4) = observed value: "72" and "98.6"
        assert obx_segs[0]["fields"][4] == "72"
        assert obx_segs[1]["fields"][4] == "98.6"


# ---------------------------------------------------------------------------
# 3. Component parsing  ("Doe^John^M")
# ---------------------------------------------------------------------------


class TestComponentParsing:
    def test_name_is_list(self) -> None:
        result = parse(ADT_MSG)
        pid = result["segments"][1]
        # PID-5 (index 4): patient name "Doe^John^M" → list of 3 components
        name = pid["fields"][4]
        assert isinstance(name, list)
        assert len(name) == 3

    def test_name_components(self) -> None:
        result = parse(ADT_MSG)
        pid = result["segments"][1]
        name = pid["fields"][4]
        assert name[0] == "Doe"
        assert name[1] == "John"
        assert name[2] == "M"

    def test_composite_msh_event(self) -> None:
        result = parse(ADT_MSG)
        msh = result["segments"][0]
        # MSH-9 (index 8): "ADT^A01" → list
        event = msh["fields"][8]
        assert isinstance(event, list)
        assert event[0] == "ADT"
        assert event[1] == "A01"


# ---------------------------------------------------------------------------
# 4. Repetition parsing  ("val1~val2")
# ---------------------------------------------------------------------------


class TestRepetitionParsing:
    def test_repeated_field_is_list(self) -> None:
        msg = "MSH|^~\\&|A\rTST|val1~val2"
        result = parse(msg)
        tst = result["segments"][1]
        field = tst["fields"][0]
        # Two repetitions → list of two items
        assert isinstance(field, list)
        assert len(field) == 2

    def test_repeated_field_values(self) -> None:
        msg = "MSH|^~\\&|A\rTST|val1~val2"
        result = parse(msg)
        tst = result["segments"][1]
        field = tst["fields"][0]
        assert field[0] == "val1"
        assert field[1] == "val2"

    def test_repeated_composite_field(self) -> None:
        # Each repetition is itself a composite "a^b"
        msg = "MSH|^~\\&|A\rTST|a^b~c^d"
        result = parse(msg)
        tst = result["segments"][1]
        field = tst["fields"][0]
        assert isinstance(field, list)
        assert len(field) == 2
        assert field[0] == ["a", "b"]
        assert field[1] == ["c", "d"]


# ---------------------------------------------------------------------------
# 5. Sub-component parsing  ("a&b")
# ---------------------------------------------------------------------------


class TestSubComponentParsing:
    def test_sub_components_are_list(self) -> None:
        msg = "MSH|^~\\&|A\rTST|a&b"
        result = parse(msg)
        tst = result["segments"][1]
        # The component has two sub-components → list
        field = tst["fields"][0]
        assert isinstance(field, list)
        assert len(field) == 2
        assert field[0] == "a"
        assert field[1] == "b"

    def test_sub_components_in_composite(self) -> None:
        # "a&b^c" → first component has 2 sub-components, second has 1
        msg = "MSH|^~\\&|A\rTST|a&b^c"
        result = parse(msg)
        tst = result["segments"][1]
        field = tst["fields"][0]
        # Field collapses: 2 components → list
        assert isinstance(field, list)
        assert len(field) == 2
        # First component: 2 sub-components → list
        assert field[0] == ["a", "b"]
        # Second component: 1 sub-component → collapses to string
        assert field[1] == "c"


# ---------------------------------------------------------------------------
# 6. Empty fields (consecutive `||`)
# ---------------------------------------------------------------------------


class TestEmptyFields:
    def test_empty_field_is_empty_string(self) -> None:
        msg = "MSH|^~\\&|A\rTST||foo||bar"
        result = parse(msg)
        tst = result["segments"][1]
        assert tst["fields"][0] == ""
        assert tst["fields"][1] == "foo"
        assert tst["fields"][2] == ""
        assert tst["fields"][3] == "bar"

    def test_trailing_empty_fields(self) -> None:
        msg = "MSH|^~\\&|A\rTST|foo||"
        result = parse(msg)
        tst = result["segments"][1]
        assert tst["fields"][0] == "foo"
        assert tst["fields"][1] == ""
        assert tst["fields"][2] == ""


# ---------------------------------------------------------------------------
# 7. Strict mode — malformed input raises ValueError
# ---------------------------------------------------------------------------


class TestStrictMode:
    def test_raises_on_missing_msh(self) -> None:
        with pytest.raises(ValueError):
            parse("PID|1||12345")

    def test_raises_on_empty_input(self) -> None:
        with pytest.raises(ValueError):
            parse("")

    def test_raises_on_short_msh(self) -> None:
        with pytest.raises(ValueError):
            parse("MSH")

    def test_raises_on_bad_encoding_chars(self) -> None:
        # MSH-2 only has 2 chars instead of 4
        with pytest.raises(ValueError):
            parse("MSH|^~|SendingApp")

    def test_strict_is_default(self) -> None:
        with pytest.raises(ValueError):
            parse("NOTAVALIDMESSAGE")


# ---------------------------------------------------------------------------
# 8. Lenient mode — malformed input returns result with warnings
# ---------------------------------------------------------------------------


class TestLenientMode:
    def test_bad_segment_skipped(self) -> None:
        # Segment "12" has a non-alpha name — should be skipped
        msg = "MSH|^~\\&|A\r12|bad_seg\rPID|1"
        result = parse(msg, strict=False)
        names = [s["name"] for s in result["segments"]]
        assert "MSH" in names
        assert "PID" in names
        assert "12" not in names

    def test_warnings_present(self) -> None:
        msg = "MSH|^~\\&|A\r12|bad_seg\rPID|1"
        result = parse(msg, strict=False)
        assert "warnings" in result
        assert len(result["warnings"]) > 0

    def test_no_warnings_key_when_clean(self) -> None:
        result = parse(ADT_MSG, strict=False)
        assert "warnings" not in result

    def test_lenient_returns_dict(self) -> None:
        msg = "MSH|^~\\&|A\r12|bad_seg\rPID|1"
        result = parse(msg, strict=False)
        assert isinstance(result, dict)
        assert "segments" in result


# ---------------------------------------------------------------------------
# 9. parse_json
# ---------------------------------------------------------------------------


class TestParseJson:
    def test_returns_string(self) -> None:
        result = parse_json(ADT_MSG)
        assert isinstance(result, str)

    def test_valid_json(self) -> None:
        result = parse_json(ADT_MSG)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_same_structure_as_parse(self) -> None:
        dict_result = parse(ADT_MSG)
        json_result = json.loads(parse_json(ADT_MSG))
        assert dict_result == json_result

    def test_json_lenient_includes_warnings(self) -> None:
        msg = "MSH|^~\\&|A\r12|bad_seg\rPID|1"
        result = json.loads(parse_json(msg, strict=False))
        assert "warnings" in result

    def test_json_strict_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_json("")


# ---------------------------------------------------------------------------
# 10. MSH special handling
# ---------------------------------------------------------------------------


class TestMSHSpecialHandling:
    def test_msh1_is_pipe(self) -> None:
        result = parse(ADT_MSG)
        msh = result["segments"][0]
        assert msh["fields"][0] == "|"

    def test_msh2_is_encoding_chars(self) -> None:
        result = parse(ADT_MSG)
        msh = result["segments"][0]
        assert msh["fields"][1] == "^~\\&"

    def test_msh_field_count(self) -> None:
        result = parse(ADT_MSG)
        msh = result["segments"][0]
        # 12 fields in the test ADT MSH (MSH-1 through MSH-12)
        assert len(msh["fields"]) == 12

    def test_msh_version(self) -> None:
        result = parse(ADT_MSG)
        msh = result["segments"][0]
        # MSH-12 (index 11) = "2.3"
        assert msh["fields"][11] == "2.3"


# ---------------------------------------------------------------------------
# 11. Different line endings
# ---------------------------------------------------------------------------


class TestLineEndings:
    BASE = (
        "MSH|^~\\&|SendingApp|SendingFac|ReceivingApp|ReceivingFac|"
        "20230101120000||ADT^A01|MSG00001|P|2.3"
        "{sep}"
        "PID|1||12345^^^MRN||Doe^John^M||19800101|M"
    )

    def _check(self, sep: str) -> None:
        msg = self.BASE.format(sep=sep)
        result = parse(msg)
        assert len(result["segments"]) == 2
        assert result["segments"][0]["name"] == "MSH"
        assert result["segments"][1]["name"] == "PID"

    def test_cr_only(self) -> None:
        self._check("\r")

    def test_lf_only(self) -> None:
        self._check("\n")

    def test_crlf(self) -> None:
        self._check("\r\n")
