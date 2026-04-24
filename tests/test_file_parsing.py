"""Tests for file and batch parsing of real-world HL7v2 messages.

Run with:
    pytest tests/test_file_parsing.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rust_hl7_parser import parse, parse_batch, parse_file, parse_file_json

FIXTURES = Path(__file__).parent / "fixtures"
SANITIZED = FIXTURES / "sample_sanitized.hl7"
BARNS = FIXTURES / "sample_barns.hl7"

# Full source files (for performance tests, may not exist)
FULL_SANITIZED = Path.home() / "hl7_messages_sanitized.hl7"
FULL_BARNS = Path.home() / "hl7_messages_barns.hl7"


def segment_names(result: dict) -> list[str]:
    return [s["name"] for s in result["segments"]]


def segments_by_name(result: dict, name: str) -> list[dict]:
    return [s for s in result["segments"] if s["name"] == name]


# --- parse_file strict ---

class TestParseFileStrict:
    def test_sanitized_count(self) -> None:
        msgs = parse_file(str(SANITIZED), strict=True)
        assert len(msgs) == 20

    def test_barns_count(self) -> None:
        msgs = parse_file(str(BARNS), strict=True)
        assert len(msgs) == 20

    def test_sanitized_all_have_segments(self) -> None:
        msgs = parse_file(str(SANITIZED), strict=True)
        for m in msgs:
            assert "segments" in m
            assert len(m["segments"]) >= 2  # at least MSH + one other

    def test_barns_all_have_segments(self) -> None:
        msgs = parse_file(str(BARNS), strict=True)
        for m in msgs:
            assert "segments" in m
            assert len(m["segments"]) >= 2


# --- parse_file lenient ---

class TestParseFileLenient:
    def test_no_warnings_on_clean_data(self) -> None:
        msgs = parse_file(str(SANITIZED), strict=False)
        for m in msgs:
            assert "warnings" not in m, f"Unexpected warnings: {m.get('warnings')}"

    def test_barns_no_warnings(self) -> None:
        msgs = parse_file(str(BARNS), strict=False)
        for m in msgs:
            assert "warnings" not in m, f"Unexpected warnings: {m.get('warnings')}"


# --- MSH field validation ---

class TestMSHFields:
    def test_sanitized_msh1_is_pipe(self) -> None:
        msgs = parse_file(str(SANITIZED), strict=True)
        assert msgs[0]["segments"][0]["fields"][0] == "|"

    def test_sanitized_msh2_encoding_chars(self) -> None:
        msgs = parse_file(str(SANITIZED), strict=True)
        assert msgs[0]["segments"][0]["fields"][1] == "^~\\&"

    def test_sanitized_version_23(self) -> None:
        msgs = parse_file(str(SANITIZED), strict=True)
        msh = msgs[0]["segments"][0]
        assert msh["fields"][11] == "2.3"

    def test_barns_version_24(self) -> None:
        msgs = parse_file(str(BARNS), strict=True)
        msh = msgs[0]["segments"][0]
        assert msh["fields"][11] == "2.4"

    def test_barns_3part_message_type(self) -> None:
        """Barnsley uses 3-part MSH-9 like ADT^A21^ADT_A21"""
        msgs = parse_file(str(BARNS), strict=True)
        msh9 = msgs[0]["segments"][0]["fields"][8]
        assert isinstance(msh9, list)
        assert len(msh9) == 3  # e.g., ["ADT", "A21", "ADT_A21"]

    def test_sanitized_message_type(self) -> None:
        msgs = parse_file(str(SANITIZED), strict=True)
        msh9 = msgs[0]["segments"][0]["fields"][8]
        assert isinstance(msh9, list)
        assert msh9[0] == "ADT"


# --- Segment content ---

class TestSegmentContent:
    def test_segment_names_present(self) -> None:
        """MSH, PID, EVN should appear across the fixture messages."""
        msgs = parse_file(str(SANITIZED), strict=True)
        all_names: set[str] = set()
        for m in msgs:
            all_names.update(segment_names(m))
        assert {"MSH", "PID", "EVN"}.issubset(all_names)

    def test_z_segments_preserved(self) -> None:
        """Z-segments (custom) should be parsed, not skipped."""
        msgs = parse_file(str(SANITIZED), strict=True)
        all_names: set[str] = set()
        for m in msgs:
            all_names.update(segment_names(m))
        # Sanitized file contains ZGP, ZU1, ZU4
        z_segs = {n for n in all_names if n.startswith("Z")}
        assert len(z_segs) >= 1, f"Expected Z-segments, found: {all_names}"

    def test_multiple_al1_segments(self) -> None:
        """Messages with multiple AL1 (allergy) segments should retain all."""
        msgs = parse_file(str(SANITIZED), strict=True)
        # Find a message with multiple AL1s
        for m in msgs:
            al1_segs = segments_by_name(m, "AL1")
            if len(al1_segs) >= 2:
                assert al1_segs[0]["fields"][0] == "1"
                assert al1_segs[1]["fields"][0] == "2"
                return
        # If no message has multiple AL1s in sanitized, check barns
        msgs = parse_file(str(BARNS), strict=True)
        for m in msgs:
            al1_segs = segments_by_name(m, "AL1")
            if len(al1_segs) >= 2:
                return
        pytest.skip("No message with multiple AL1 segments found in fixtures")

    def test_patient_name_parsed(self) -> None:
        """PID-5 (patient name) should parse as components."""
        msgs = parse_file(str(SANITIZED), strict=True)
        pid = segments_by_name(msgs[0], "PID")[0]
        name = pid["fields"][4]  # PID-5
        # Should be a list of components (e.g., ["Fuller", "Eoin", ...])
        assert isinstance(name, list)
        assert len(name) >= 2  # at least family and given name

    def test_escape_sequence_expansion(self) -> None:
        r"""Fields containing \T\ should expand to &."""
        # The sanitized data contains A\T\E sequences in ZU1 segments
        # which should be expanded to A&E by the parser
        msgs = parse_file(str(SANITIZED), strict=True)
        found = False
        for m in msgs:
            for seg in m["segments"]:
                fields_str = json.dumps(seg["fields"])
                if "A&E" in fields_str:
                    found = True
                    break
            if found:
                break
        # If not found in sanitized, check barns
        if not found:
            msgs = parse_file(str(BARNS), strict=True)
            for m in msgs:
                for seg in m["segments"]:
                    fields_str = json.dumps(seg["fields"])
                    if "A&E" in fields_str:
                        found = True
                        break
                if found:
                    break
        # If not in fixtures, test with synthetic message
        if not found:
            result = parse("MSH|^~\\&|A\rTST|A\\T\\E test", strict=True)
            tst = result["segments"][1]
            assert "A&E" in tst["fields"][0]
        else:
            assert found, "Expected A&E escape expansion in fixture data"


# --- parse_batch ---

class TestParseBatch:
    def test_basic(self) -> None:
        msg1 = "MSH|^~\\&|A|B|C|D|20230101||ADT^A01|1|P|2.3\rPID|1"
        msg2 = "MSH|^~\\&|X|Y|Z|W|20230102||ADT^A01|2|P|2.3\rPID|2"
        results = parse_batch([msg1, msg2], strict=True)
        assert len(results) == 2
        assert results[0]["segments"][0]["name"] == "MSH"
        assert results[1]["segments"][0]["name"] == "MSH"

    def test_empty_list(self) -> None:
        results = parse_batch([], strict=True)
        assert results == []

    def test_matches_individual_parse(self) -> None:
        """parse_batch results should match individual parse() calls."""
        msg = "MSH|^~\\&|A|B|C|D|20230101||ADT^A01|1|P|2.3\rPID|1"
        batch_result = parse_batch([msg], strict=True)
        single_result = parse(msg, strict=True)
        assert batch_result[0] == single_result


# --- parse_file_json ---

class TestParseFileJson:
    def test_returns_valid_json(self) -> None:
        result = parse_file_json(str(SANITIZED), strict=True)
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 20

    def test_matches_parse_file(self) -> None:
        dict_result = parse_file(str(SANITIZED), strict=True)
        json_result = json.loads(parse_file_json(str(SANITIZED), strict=True))
        assert len(dict_result) == len(json_result)
        # Compare first message
        assert dict_result[0] == json_result[0]

    def test_file_not_found(self) -> None:
        with pytest.raises(OSError):
            parse_file_json("/nonexistent/path.hl7")


# --- MLLP handling ---

class TestMLLP:
    def test_mllp_framing_stripped(self, tmp_path: Path) -> None:
        """Messages wrapped in MLLP framing should parse in strict mode."""
        msg = "\x0bMSH|^~\\&|A|B|C|D|20230101||ADT^A01|1|P|2.3\nPID|1\n\x1c\n"
        filepath = tmp_path / "mllp_test.hl7"
        filepath.write_text(msg)
        result = parse_file(str(filepath), strict=True)
        assert len(result) == 1
        assert result[0]["segments"][0]["name"] == "MSH"

    def test_blank_line_separator(self, tmp_path: Path) -> None:
        msg = "MSH|^~\\&|A\nPID|1\n\nMSH|^~\\&|B\nPID|2\n"
        filepath = tmp_path / "blank_sep.hl7"
        filepath.write_text(msg)
        result = parse_file(str(filepath), strict=True)
        assert len(result) == 2

    def test_msh_restart_separator(self, tmp_path: Path) -> None:
        """Two messages with no blank line — MSH detection splits them."""
        msg = "MSH|^~\\&|A\nPID|1\nMSH|^~\\&|B\nPID|2\n"
        filepath = tmp_path / "msh_restart.hl7"
        filepath.write_text(msg)
        result = parse_file(str(filepath), strict=True)
        assert len(result) == 2


# --- Performance ---

class TestPerformance:
    @pytest.mark.slow
    @pytest.mark.skipif(
        not FULL_SANITIZED.exists(),
        reason="Full sanitized HL7 file not present"
    )
    def test_performance_10k_messages(self) -> None:
        """Parse 10,000 messages in under 10 seconds."""
        import time
        # Read and group first 10k messages
        messages = []
        current: list[str] = []
        with open(FULL_SANITIZED) as f:
            for line in f:
                stripped = line.rstrip("\n").strip("\x0b\x1c\x0d")
                if not stripped:
                    if current:
                        messages.append("\r".join(current))
                        current = []
                        if len(messages) >= 10000:
                            break
                else:
                    if stripped.startswith("MSH") and current:
                        messages.append("\r".join(current))
                        current = [stripped]
                        if len(messages) >= 10000:
                            break
                    else:
                        current.append(stripped)

        t0 = time.perf_counter()
        results = parse_batch(messages, strict=False)
        elapsed = time.perf_counter() - t0

        assert len(results) == len(messages)
        assert elapsed < 10.0, f"Took {elapsed:.1f}s, expected <10s"
        print(f"\nParsed {len(results)} messages in {elapsed:.2f}s ({len(results)/elapsed:.0f} msg/sec)")
