# rust-hl7-parser

A fast HL7v2 message parser written in Rust, exposed to Python via PyO3 and maturin.

## Purpose

Parse HL7v2 pipe-delimited messages into structured Python objects. Designed for
healthcare data pipelines where parsing throughput or correctness guarantees matter.

## Stack

| Layer       | Technology                                    |
|-------------|-----------------------------------------------|
| Parser      | Rust 2021 + `str::split` (no combinator libs) |
| Python API  | PyO3 0.28 + maturin (optional `python` feature) |
| Serialise   | serde + serde_json                            |
| Tests       | pytest (Python), built-in `#[test]` (Rust)    |

## Build

### Prerequisites

- Rust stable toolchain
- Python 3.9+ with maturin installed in the active venv (`pip install maturin`)

### Development build (installs into the active venv)

```bash
maturin develop
pytest tests/
```

### Release wheel

```bash
maturin build --release
```

### Notes on the build configuration

The `python` Cargo feature (default) pulls in pyo3 with `extension-module` and
compiles `src/python_bindings.rs`. Disable it for a pure-Rust library build:

```bash
cargo build --no-default-features
```

`pyo3/abi3-py313` is passed by maturin via `pyproject.toml` and produces a
single `_native.abi3.so` compatible with all CPython 3.13+ versions. If a
stale `_native.cpython-XYZ-darwin.so` from a previous non-abi3 build exists
alongside it, Python will prefer the versioned file and crash if it was linked
against a different libpython. Delete any such stale files or run
`maturin develop` again which overwrites them.

**`.cargo/config.toml` — macOS linker flags for bare `cargo test`**

PyO3's `extension-module` feature suppresses the implicit `libpython` link so
that abi3 wheels are not bound to a specific interpreter version.  This is
correct for `maturin build`, but it means a plain `cargo test` invocation
produces a binary with undefined symbols that the macOS static linker rejects.

`.cargo/config.toml` sets:

```toml
[target.aarch64-apple-darwin]
rustflags = ["-C", "link-arg=-undefined", "-C", "link-arg=dynamic_lookup"]
```

`-undefined dynamic_lookup` is the standard macOS workaround: it defers symbol
resolution to load time, at which point the test binary is running inside the
active Python interpreter and all `libpython` symbols are already present.
maturin overrides these flags with its own linker invocation when producing
wheels, so the flag has no effect on release builds.

## Test

### Rust unit tests

```bash
maturin develop && cargo test
```

`maturin develop` must run first so that the active venv contains a built
`_native` extension.  The bare `cargo test` step is then able to resolve PyO3
symbols at runtime via the `-undefined dynamic_lookup` linker flag configured
in `.cargo/config.toml` (see "Notes on the build configuration" below).

### Python integration tests

```bash
pytest tests/
```

`tests/test_parser.py` covers all parsing rules and edge cases for single-message
parsing. `tests/test_file_parsing.py` covers `parse_file`, `parse_file_json`, and
`parse_batch` against real NHS fixture data in `tests/fixtures/`.

## Architecture

```
src/
  types.rs    — pub: Rust data model: Hl7Message / Hl7Segment / Hl7Field /
                Hl7Repetition / Hl7Component. All types derive serde::Serialize.

  error.rs    — pub: ParseError, ParseMode (Strict / Lenient), LenientResult<T>.

  parser.rs   — pub: Bottom-up parser using str::split (no Winnow combinators):
                  sub_component → component → repetition → field → segment → message
                MSH is handled specially (MSH-1 = field sep, MSH-2 = encoding chars).
                Escape-sequence expansion (\F\, \S\, \R\, \E\, \T\).
                split_lines() accepts \r, \n, \r\n; strips MLLP framing bytes.
                parse_strict() / parse_lenient() / parse() public entry points.
                group_message_lines() — splits file content into borrowed line-slice
                  groups, one group per message. Handles blank-line separators,
                  MSH-restart detection, and MLLP framing.
                parse_message_groups() — batch-parses pre-grouped messages;
                  returns Vec of results, one per message.

  lib.rs      — Crate root. Re-exports pub mod error / parser / types.
                Conditionally includes python_bindings under the `python` feature.
                Rust consumers depend on this crate with default-features = false.

  python_bindings.rs — Compiled only with the `python` feature.
                Defines the `_native` PyO3 extension module with six exported
                functions: parse(), parse_json(), parse_lossless_json(),
                parse_file(), parse_file_json(), parse_batch().
                Implements structure-collapsing: single sub-component → str,
                single component → collapsed, single repetition → collapsed.
                Direct JSON write path (no serde_json::Value intermediates).

python/
  rust_hl7_parser/
    __init__.py   — Re-exports all five functions from _native, module
                    docstring, __all__, __version__.
    py.typed      — PEP 561 marker (signals the package ships type information).

tests/
  test_parser.py       — pytest suite covering all single-message parsing rules
                         and edge cases.
  test_file_parsing.py — pytest suite for parse_file, parse_file_json, and
                         parse_batch against fixture data and synthetic messages.
  fixtures/
    sample_sanitized.hl7 — 20 sanitized NHS ADT messages (HL7 v2.3).
    sample_barns.hl7     — 20 Barnsley NHS ADT messages (HL7 v2.4, 3-part MSH-9).
```

## Parsing Rules (HL7v2 quick reference)

| Separator | Default | Purpose                        |
|-----------|---------|--------------------------------|
| `\r`      | —       | Segment terminator             |
| `|`       | MSH-1   | Field separator                |
| `^`       | MSH-2[0]| Component separator            |
| `~`       | MSH-2[1]| Repetition separator           |
| `\`       | MSH-2[2]| Escape character               |
| `&`       | MSH-2[3]| Sub-component separator        |

MSH field numbering in the parsed output (zero-indexed `fields` list):

| Index | HL7 name | Example value  |
|-------|----------|----------------|
| 0     | MSH-1    | `\|`            |
| 1     | MSH-2    | `^~\&`         |
| 2     | MSH-3    | SendingApp     |
| 3     | MSH-4    | SendingFac     |
| ...   | ...      | ...            |

## Lenient Mode

Call `parse(msg, strict=False)` or `parse_json(msg, strict=False)`.

Malformed segments are skipped. The returned dict gains a `"warnings"` key
listing every issue encountered. If the message is well-formed the key is
omitted.

## File Parsing

Use `parse_file` or `parse_file_json` to parse `.hl7` files containing one or
more messages.

**File format understood:**

- One segment per line, segments separated by `\n`
- Messages separated by blank lines, or a new `MSH` line with no blank line
- Single-line messages with `\r` between segments also work
- MLLP framing bytes (`\x0B` start-of-block, `\x1C` end-of-block) are stripped
  automatically from each line

**Example:**

```python
from rust_hl7_parser import parse_file, parse_file_json, parse_batch
import json

# Parse a file — returns list of dicts
messages = parse_file("messages.hl7", strict=True)
print(len(messages))                        # number of messages
print(messages[0]["segments"][0]["name"])   # "MSH"

# Parse a file — returns JSON array string (faster for downstream serialisation)
json_str = parse_file_json("messages.hl7", strict=False)
messages = json.loads(json_str)

# Parse a list of message strings already loaded in memory
raw = ["MSH|^~\\&|...\rPID|1", "MSH|^~\\&|...\rPID|2"]
results = parse_batch(raw, strict=True)
```

In strict mode any malformed message raises `ValueError` listing which messages
failed. In lenient mode each parsed dict may contain a `"warnings"` key.

## HL7v2 Version-Aware Validator

A pure-Python post-parse validation layer at `python/rust_hl7_parser/validator.py`.
Validates parsed message dicts against version-specific HL7 schemas.

### Usage

```python
from rust_hl7_parser import parse, validate, validate_file, validate_file_summary

# Validate a single parsed message (auto-detects version from MSH-12)
msg = parse("MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\rPID|1||12345|||Doe^John\rPV1|1|I\rEVN||20230101")
result = validate(msg, strict=True)
print(result["valid"], result["version"], len(result["issues"]), "issues")
for issue in result["issues"]:
    print(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")

# Override version
result = validate(msg, version="2.4")

# Lenient mode — valid=True always, errors downgraded to warnings
result = validate(msg, strict=False)

# Validate an entire file (includes message_index and message_control_id per result)
results = validate_file("messages.hl7", strict=False)
print(f"{len(results)} messages validated")
for r in results:
    print(r["message_index"], r["message_control_id"], r["valid"])

# High-level file summary
summary = validate_file_summary("messages.hl7", strict=False)
print(f"{summary['total_messages']} total, {summary['valid_messages']} valid")
print(f"Issue breakdown: {summary['issue_counts']}")
```

### Return structure

`validate()` returns:

```python
{
    "valid": True,
    "version": "2.4",
    "message_type": "ADT_A01",
    "issues": [
        {
            "severity": "warning",   # "error" | "warning" | "info"
            "segment": "PV2",
            "field": None,
            "code": "EXCESS_FIELDS",
            "message": "PV2 has 49 fields but HL7v2.4 defines a maximum of 38 fields for this segment. Extra fields may indicate a version mismatch or custom extension."
        }
    ]
}
```

`validate_file()` returns a list of the above dicts, each extended with:

```python
{
    ...,
    "message_index": 0,               # 0-based position in the file
    "message_control_id": "MSG00001"  # MSH-10 value, or None if absent
}
```

`validate_file_summary()` returns:

```python
{
    "file": "messages.hl7",
    "total_messages": 42,
    "valid_messages": 40,
    "invalid_messages": 2,
    "issue_counts": {
        "EXCESS_FIELDS": 15,
        "UNKNOWN_MESSAGE_TYPE": 2
    },
    "results": [...]   # full validate_file() output
}
```

### Validation checks

| # | Code | Strict | Lenient |
|---|------|--------|---------|
| 1 | `UNKNOWN_VERSION` | Error | Warning (falls back to nearest) |
| 2 | `UNKNOWN_SEGMENT` | Error | Warning |
| 3 | `MISSING_REQUIRED_SEGMENT` | Error | Warning |
| 4 | `SEGMENT_EXCEEDS_MAX` | Error | Warning |
| 5 | `UNEXPECTED_SEGMENT` | Warning | Info |
| 6 | `MISSING_REQUIRED_FIELD` | Error | Warning |
| 7 | `EXCESS_FIELDS` | Warning | Info |
| 8 | `FIELD_TOO_LONG` | Warning | Warning |
| 9 | `CUSTOM_Z_SEGMENT` | Info | Info |
| 10 | `UNKNOWN_MESSAGE_TYPE` | Warning | Info |

### Schema coverage

Schemas in `python/rust_hl7_parser/schemas/`:

- **Versions**: 2.1, 2.2, 2.3, 2.3.1, 2.4, 2.5, 2.5.1, 2.6, 2.7, 2.7.1, 2.8, 2.8.1, 2.8.2, 2.9
- **Segments**: ~40 segments per version — MSH, EVN, PID, PD1, PV1, PV2, NK1, AL1, DG1, PR1, OBR, OBX, ORC, IN1, IN2, GT1, ACC, ROL, RF1, PRD, SCH, AIG, AIL, AIP, AIS, MFI, MFE, STF, MRG, SPM, TQ1, TQ2, SFT, UAC, ERR, QRD, QAK, RXD, RXR, RXA, RXE, RXO, NTE, MSA
- **Message types**: ADT_A01/02/03/04/05/08/11/14/21/31, ORM_O01, ORU_R01, REF_I12, RRD_O14, SIU_S12, MDM_T02
- Minor versions (2.3.1, 2.5.1, 2.7.1, 2.8.1, 2.8.2) use `"inherits"` to define only deltas

### Architecture

```
python/rust_hl7_parser/
  validator.py              — SchemaRegistry, validate(), validate_file(),
                              validate_file_summary(), _get_msh_control_id()
  schemas/
    __init__.py             — empty (package marker)
    v2_1.json … v2_9.json  — per-version segment/field schemas
    message_types.json      — 16 message type segment-composition rules
tests/
  test_validator.py         — 40+ tests covering all validation checks,
                              enhanced messages, validate_file_summary,
                              and optional real NHS file tests (@pytest.mark.slow)
```

## Benchmarks

```bash
python benchmarks/bench_parse.py
```

Benchmarked against real HL7 data:

- ~2.2x faster than `python-hl7`
- ~4,400 messages/second throughput
