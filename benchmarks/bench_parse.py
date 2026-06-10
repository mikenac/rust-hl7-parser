#!/usr/bin/env python3
"""
Benchmark: rust_hl7_parser vs python-hl7 vs hl7apy

Compares parsing throughput on real-world NHS HL7v2 messages.

Usage:
    python benchmarks/bench_parse.py [--messages N] [--file PATH]

Requirements:
    pip install hl7 hl7apy
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def read_messages(filepath: str, max_messages: int = 5000) -> list[str]:
    """Read an HL7 file and group segments into complete messages."""
    messages: list[str] = []
    current: list[str] = []
    with open(filepath) as f:
        for line in f:
            stripped = line.rstrip("\n").strip("\x0b\x1c\x0d")
            if not stripped:
                if current:
                    messages.append("\r".join(current))
                    current = []
                    if len(messages) >= max_messages:
                        break
            else:
                if stripped.startswith("MSH") and current:
                    messages.append("\r".join(current))
                    current = [stripped]
                    if len(messages) >= max_messages:
                        break
                else:
                    current.append(stripped)
    if current and len(messages) < max_messages:
        messages.append("\r".join(current))
    return messages


def bench_rust_parse(messages: list[str]) -> tuple[float, int, int]:
    from rust_hl7_parser import parse
    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            parse(m, strict=False)
            ok += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_rust_parse_validate(messages: list[str]) -> tuple[float, int, int]:
    from rust_hl7_parser import parse, validate
    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            parsed = parse(m, strict=False)
            validate(parsed, strict=False)
            ok += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_rust_parse_json(messages: list[str]) -> tuple[float, int, int]:
    from rust_hl7_parser import parse_json
    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            parse_json(m, strict=False)
            ok += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_rust_parse_annotated(messages: list[str]) -> tuple[float, int, int]:
    from rust_hl7_parser import parse_annotated
    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            parse_annotated(m, strict=False)
            ok += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_rust_parse_annotated_json(messages: list[str]) -> tuple[float, int, int]:
    from rust_hl7_parser import parse_annotated_json
    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            parse_annotated_json(m, strict=False)
            ok += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_rust_parse_lossless_json(messages: list[str]) -> tuple[float, int, int]:
    from rust_hl7_parser import parse_lossless_json
    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            parse_lossless_json(m, strict=False)
            ok += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_rust_hl7apy_compat(messages: list[str]) -> tuple[float, int, int]:
    from rust_hl7_parser import parse_hl7apy_compat
    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            result = parse_hl7apy_compat(m, strict=False)
            if result.get("status") == "Processed":
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_rust_batch(messages: list[str]) -> tuple[float, int, int]:
    from rust_hl7_parser import parse_batch
    t0 = time.perf_counter()
    try:
        results = parse_batch(messages, strict=False)
        ok = len(results)
        fail = 0
    except Exception:
        ok = 0
        fail = len(messages)
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_rust_file(filepath: str) -> tuple[float, int, int]:
    from rust_hl7_parser import parse_file
    t0 = time.perf_counter()
    try:
        results = parse_file(filepath, strict=False)
        ok = len(results)
        fail = 0
    except Exception:
        ok = 0
        fail = 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_python_hl7(messages: list[str]) -> tuple[float, int, int]:
    try:
        import hl7
    except ImportError:
        return -1.0, 0, 0
    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            hl7.parse(m)
            ok += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_hl7apy(messages: list[str]) -> tuple[float, int, int]:
    try:
        from hl7apy.parser import parse_message
    except ImportError:
        return -1.0, 0, 0
    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            # validation_level=2 is the tolerant/lenient mode; levels 0 and 1
            # reject real-world HL7 messages with non-standard extensions.
            parse_message(m, validation_level=2)
            ok += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def bench_hl7apy_full_extract(messages: list[str]) -> tuple[float, int, int]:
    """Benchmark the full hl7apy extract_message pipeline.

    This replicates what extract_message actually does — not just
    parse_message() but the full segment/field iteration that builds the
    output dict.  This is the apples-to-apples comparison for
    parse_hl7apy_compat().
    """
    try:
        from hl7apy.parser import parse_message
    except ImportError:
        return -1.0, 0, 0

    def _parse_field(field_item, comp_sep, subcomp_sep, is_msh2=False):
        try:
            if is_msh2:
                return field_item.to_er7()
            parts = field_item.to_er7().split(comp_sep)
            if len(parts) > 1:
                return [
                    p.split(subcomp_sep) if subcomp_sep in p else p
                    for p in parts
                ]
            return parts[0]
        except Exception:
            return None

    def _extract(msg_str):
        msg = parse_message(msg_str, find_groups=False, validation_level=2)
        msh2 = msg.msh.msh_2[0].to_er7() if msg.msh.msh_2 else ""
        comp_sep = msh2[0] if msh2 else "^"
        subcomp_sep = msh2[3] if len(msh2) > 3 else "&"
        all_segments = []
        for seg in msg.children:
            seg_dict = {}
            if seg.name.startswith("Z"):
                raw = seg.to_er7()
                for idx, val in enumerate(raw.split("|")[1:], 1):
                    seg_dict[f"{seg.name}_{idx}"] = val or None
            else:
                for field_name in seg.structure_by_name.keys():
                    try:
                        field_list = getattr(seg, field_name.lower(), [])
                    except Exception:
                        seg_dict[field_name.upper()] = None
                        continue
                    if not field_list:
                        seg_dict[field_name.upper()] = None
                        continue
                    is_msh2 = seg.name == "MSH" and field_name.upper() == "MSH_2"
                    values = [_parse_field(f, comp_sep, subcomp_sep, is_msh2) for f in field_list]
                    if len(values) > 1:
                        seg_dict[field_name.upper()] = [
                            v if isinstance(v, list) else [v] for v in values
                        ]
                    else:
                        seg_dict[field_name.upper()] = values[0]
            all_segments.append(seg_dict)
        return all_segments

    ok = fail = 0
    t0 = time.perf_counter()
    for m in messages:
        try:
            _extract(m)
            ok += 1
        except Exception:
            fail += 1
    elapsed = time.perf_counter() - t0
    return elapsed, ok, fail


def print_result(name: str, elapsed: float, ok: int, fail: int, total: int) -> None:
    if elapsed < 0:
        print(f"  {name:25s}  not installed")
        return
    rate = ok / elapsed if elapsed > 0 else 0
    print(f"  {name:25s}  {elapsed:7.3f}s  {ok:5d}/{total} ok  {rate:8.0f} msg/sec")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark HL7 parsers")
    parser.add_argument("--messages", "-n", type=int, default=5000,
                        help="Number of messages to parse (default: 5000)")
    parser.add_argument("--file", "-f", type=str, default=None,
                        help="Path to .hl7 file (default: ~/hl7_messages_sanitized.hl7)")
    args = parser.parse_args()

    if args.file:
        filepath = args.file
    else:
        for candidate in [
            Path.home() / "hl7_messages_sanitized.hl7",
            Path.home() / "hl7_messages_barns.hl7",
            Path(__file__).parent.parent / "tests" / "fixtures" / "sample_sanitized.hl7",
        ]:
            if candidate.exists():
                filepath = str(candidate)
                break
        else:
            print("No HL7 file found. Provide one with --file PATH")
            sys.exit(1)

    print(f"Loading messages from: {filepath}")
    messages = read_messages(filepath, args.messages)
    total = len(messages)
    avg_len = sum(len(m) for m in messages) / total if total else 0
    print(f"Loaded {total} messages (avg {avg_len:.0f} chars)\n")

    # Warmup
    from rust_hl7_parser import parse
    for m in messages[:min(10, total)]:
        try:
            parse(m, strict=False)
        except Exception:
            pass

    # === Benchmark 1: Single-message loop ===
    print(f"=== Single-message parse loop ({total} messages) ===")

    t, ok, fail = bench_rust_parse(messages)
    print_result("rust_hl7_parser (dict)", t, ok, fail, total)
    rust_dict_time = t

    t, ok, fail = bench_rust_parse_validate(messages)
    print_result("rust_hl7 (dict+validate)", t, ok, fail, total)
    rust_validate_time = t

    t, ok, fail = bench_rust_parse_json(messages)
    print_result("rust_hl7_parser (json)", t, ok, fail, total)

    t, ok, fail = bench_rust_batch(messages)
    print_result("rust_hl7_parser (batch)", t, ok, fail, total)
    rust_batch_time = t

    t, ok, fail = bench_rust_parse_annotated(messages)
    print_result("rust_hl7 (annotated dict)", t, ok, fail, total)

    t, ok, fail = bench_rust_parse_annotated_json(messages)
    print_result("rust_hl7 (annotated json)", t, ok, fail, total)

    t, ok, fail = bench_rust_parse_lossless_json(messages)
    print_result("rust_hl7 (lossless json)", t, ok, fail, total)
    rust_lossless_time = t

    t, ok, fail = bench_rust_hl7apy_compat(messages)
    print_result("rust_hl7 (hl7apy compat)", t, ok, fail, total)
    rust_compat_time = t

    t, ok, fail = bench_python_hl7(messages)
    print_result("python-hl7", t, ok, fail, total)
    pyhl7_time = t

    t, ok, fail = bench_hl7apy(messages)
    print_result("hl7apy parse_message()", t, ok, fail, total)
    hl7apy_parse_time = t

    t, ok, fail = bench_hl7apy_full_extract(messages)
    print_result("hl7apy full extract_msg", t, ok, fail, total)
    hl7apy_full_time = t

    # === Speedup summary ===
    print(f"\n=== Speedup Summary ===")
    if pyhl7_time > 0:
        print(f"  rust dict  vs python-hl7:  {pyhl7_time/rust_dict_time:.1f}x")
        print(f"  rust batch vs python-hl7:  {pyhl7_time/rust_batch_time:.1f}x")
    if hl7apy_parse_time > 0 and rust_validate_time > 0:
        print(f"  rust dict+validate vs hl7apy parse_message:  {hl7apy_parse_time/rust_validate_time:.1f}x")
    if hl7apy_full_time > 0 and rust_compat_time > 0:
        print(f"  rust hl7apy_compat vs hl7apy full extract:  {hl7apy_full_time/rust_compat_time:.1f}x")
    if hl7apy_full_time > 0 and rust_lossless_time > 0:
        print(f"  rust lossless_json vs hl7apy full extract:  {hl7apy_full_time/rust_lossless_time:.1f}x")

    # === Benchmark 2: File parsing (if full file available) ===
    if os.path.exists(filepath) and total >= 1000:
        print(f"\n=== File parsing: parse_file() on {os.path.basename(filepath)} ===")
        t, ok, fail = bench_rust_file(filepath)
        print_result("rust parse_file()", t, ok, fail, ok + fail)

    print()


if __name__ == "__main__":
    main()
