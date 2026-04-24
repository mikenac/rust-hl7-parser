# rust-hl7-parser

A fast HL7v2 message parser written in Rust with Python bindings.

<!-- badges: PyPI and CI badges will go here once published -->

## Features

- **10x faster than python-hl7, 160x faster than hl7apy** (parse + validate) — see benchmarks below
- **Zero-copy Rust parser via PyO3** — returns native Python dicts with no intermediate representations
- **Lenient mode** skips malformed segments and reports structured warnings instead of raising
- **JSON output path** (`parse_json`, `parse_file_json`) avoids Python dict construction overhead entirely
- **File parsing** with automatic message splitting: blank-line separation, MSH-restart detection, MLLP framing stripped automatically
- **Batch parsing** for in-memory message lists via `parse_batch`
- **HL7v2 version-aware validation** covering versions 2.1 through 2.9, 16 message types, ~40 segments per version
- **PEP 561 typed** — ships `py.typed`, full type annotations
- **Single abi3 wheel** compatible with CPython 3.13+

## Installation

```
pip install rust-hl7-parser
```

### Development

```bash
pip install maturin
git clone https://github.com/mike-nacey/rust-hl7-parser
cd rust-hl7-parser
maturin develop
pytest tests/
```

The optional `orjson` extra enables the `parse_to_json` and `parse_file_to_json`
functions, which return `bytes` directly and are faster for downstream serialisation:

```
pip install rust-hl7-parser[orjson]
```

## Quick start

### 1. Parse a single message to a dict

```python
from rust_hl7_parser import parse

msg = parse(
    "MSH|^~\\&|SendingApp|SendingFac|RecvApp|RecvFac|"
    "20230101120000||ADT^A01|MSG00001|P|2.3\r"
    "PID|1||12345^^^MRN||Doe^John^M||19800101|M\r"
    "PV1|1|I|ICU^Bed1^Main"
)

print(msg["segments"][0]["name"])      # "MSH"
print(msg["segments"][1]["fields"][4]) # ["Doe", "John", "M"]
```

### 2. Lenient mode — skip bad segments, collect warnings

```python
from rust_hl7_parser import parse

msg = parse("MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\rBAD\rPID|1", strict=False)

# The message still parses; BAD segment is skipped
print(msg.get("warnings"))  # ["Skipped segment: BAD"]
```

### 3. JSON string output — no dict construction

```python
from rust_hl7_parser import parse_json
import json

json_str = parse_json(
    "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\rPID|1||12345"
)
data = json.loads(json_str)
```

### 4. Parse a multi-message .hl7 file

```python
from rust_hl7_parser import parse_file

messages = parse_file("messages.hl7", strict=False)
print(len(messages))                         # number of messages parsed
print(messages[0]["segments"][0]["name"])    # "MSH"
```

### 5. Batch-parse in-memory message strings

```python
from rust_hl7_parser import parse_batch

raw = [
    "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\rPID|1||11111",
    "MSH|^~\\&|App|Fac|App|Fac|20230102||ADT^A08|2|P|2.3\rPID|1||22222",
]
results = parse_batch(raw, strict=True)
```

### 6. Validate a parsed message

```python
from rust_hl7_parser import parse, validate

msg = parse(
    "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
    "EVN||20230101\r"
    "PID|1||12345|||Doe^John\r"
    "PV1|1|I"
)
result = validate(msg, strict=False)

print(result["valid"])    # True or False
print(result["version"])  # "2.3"
for issue in result["issues"]:
    print(f"[{issue['severity']}] {issue['code']}: {issue['message']}")
```

### 7. Validate an entire file — summary stats

```python
from rust_hl7_parser import validate_file_summary

summary = validate_file_summary("messages.hl7", strict=False)
print(f"{summary['total_messages']} total, {summary['valid_messages']} valid")
print(f"Issue breakdown: {summary['issue_counts']}")
# Issue breakdown: {'EXCESS_FIELDS': 12, 'MISSING_REQUIRED_FIELD': 3}
```

## API Reference

| Function | Returns | Description |
|----------|---------|-------------|
| `parse(message, strict=True)` | `dict` | Parse single HL7v2 message |
| `parse_json(message, strict=True)` | `str` | Parse to JSON string |
| `parse_file(path, strict=True)` | `list[dict]` | Parse a .hl7 file containing one or more messages |
| `parse_file_json(path, strict=True)` | `str` | Parse file, return JSON array string |
| `parse_batch(messages, strict=True)` | `list[dict]` | Parse a list of message strings |
| `parse_to_json(message, strict=True)` | `bytes` | Parse and return orjson bytes (requires `[orjson]` extra) |
| `parse_file_to_json(path, strict=True)` | `bytes` | Parse file and return orjson bytes (requires `[orjson]` extra) |
| `validate(message_dict, strict=True, version=None)` | `dict` | Validate a parsed message dict |
| `validate_file(path, strict=True)` | `list[dict]` | Validate all messages in a file |
| `validate_file_summary(path, strict=True)` | `dict` | Summary stats for all messages in a file |

## Benchmarks

Benchmarked against 5,000 real NHS HL7v2 messages (average 1,792 characters each):

```
Parser                          Throughput     Relative
rust_hl7_parser (json)          31,190 msg/s   1.2x faster than dict
rust_hl7_parser (dict)          26,494 msg/s   baseline
rust_hl7_parser (dict+validate) 16,407 msg/s   parse + validate combined
python-hl7                       2,530 msg/s   10.2x slower
hl7apy (tolerant)                  102 msg/s   160x slower (parse+validate)
```

Run the benchmark yourself:

```bash
python benchmarks/bench_parse.py
```

## Parsing rules

### Separators

| Separator | Default | Purpose |
|-----------|---------|---------|
| `\r` | — | Segment terminator |
| `\|` | MSH-1 | Field separator |
| `^` | MSH-2[0] | Component separator |
| `~` | MSH-2[1] | Repetition separator |
| `\` | MSH-2[2] | Escape character |
| `&` | MSH-2[3] | Sub-component separator |

Escape sequences `\F\`, `\S\`, `\R\`, `\E\`, and `\T\` are expanded to their
respective separator characters.

### MSH field numbering

The `fields` list in the `MSH` segment is zero-indexed. `fields[0]` is the field
separator character (`|`), `fields[1]` is the encoding characters (`^~\&`),
`fields[2]` is MSH-3 (Sending Application), and so on.

## Lenient mode

By default (`strict=True`) any malformed segment raises `ValueError` with a
description of the problem. In lenient mode (`strict=False`) malformed segments
are silently skipped and a `"warnings"` key is added to the returned dict listing
each skipped segment. If no issues are encountered the `"warnings"` key is omitted
entirely. This makes lenient mode safe to use in production pipelines where
occasional dirty data is expected.

## License

MIT — Copyright 2024-2026 Mike Nacey
