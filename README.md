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

## Output structure

Both `parse()` and `parse_json()` return the same structure. Fields are
**automatically collapsed** so simple values surface as plain strings, while
complex structures remain as nested lists.

### Collapsing rules

The parser applies these rules innermost-first:

| HL7 structure | Single item | Multiple items |
|---------------|-------------|----------------|
| Sub-components (`&`) | `"value"` | `["a", "b"]` |
| Components (`^`) | collapsed sub-component | `["Doe", "John", "M"]` |
| Repetitions (`~`) | collapsed component | `["val1", "val2"]` |
| Field | collapsed repetition | list of repetitions |

### Example: ADT^A01 with components and sub-components

**Input:**
```
MSH|^~\&|SendingApp|SendingFac|RecvApp|RecvFac|20230101120000||ADT^A01|MSG00001|P|2.3
PID|1||12345^^^MRN||Doe^John^M||19800101|M
PV1|1|I|ICU^Bed1^Main
```

**Output (formatted JSON):**
```json
{
  "segments": [
    {
      "name": "MSH",
      "fields": [
        "|",
        "^~\\&",
        "SendingApp",
        "SendingFac",
        "RecvApp",
        "RecvFac",
        "20230101120000",
        "",
        ["ADT", "A01"],
        "MSG00001",
        "P",
        "2.3"
      ]
    },
    {
      "name": "PID",
      "fields": [
        "1",
        "",
        ["12345", "", "", "MRN"],
        "",
        ["Doe", "John", "M"],
        "",
        "19800101",
        "M"
      ]
    },
    {
      "name": "PV1",
      "fields": [
        "1",
        "I",
        ["ICU", "Bed1", "Main"]
      ]
    }
  ]
}
```

Key observations:
- **Simple fields** like `"SendingApp"` → plain string
- **Components** like `ADT^A01` → `["ADT", "A01"]`
- **Sub-components** like `12345^^^MRN` → `["12345", "", "", "MRN"]` (empty strings preserved)
- **MSH-1** is always `"|"`, **MSH-2** is always `"^~\\&"` (stored as literal strings, not parsed)

### Example: repeating fields (`~` separator)

**Input:**
```
MSH|^~\&|App|Fac||||ADT^A01|1|P|2.3
NK1|1|Smith^Jane~Jones^Bob|SPO~EMC|123 Main St~456 Oak Ave
```

**Output:**
```json
{
  "segments": [
    { "name": "MSH", "fields": ["...(abbreviated)"] },
    {
      "name": "NK1",
      "fields": [
        "1",
        [["Smith", "Jane"], ["Jones", "Bob"]],
        ["SPO", "EMC"],
        ["123 Main St", "456 Oak Ave"]
      ]
    }
  ]
}
```

NK1-2 has **repeating composite fields**: two repetitions of `name^name`, so it
becomes a list of lists: `[["Smith", "Jane"], ["Jones", "Bob"]]`.

NK1-3 has **repeating simple fields**: `SPO~EMC` → `["SPO", "EMC"]`.

Note: a repeating simple field and a multi-component field both produce a flat list
of strings — the parser collapses them identically because the underlying HL7
structure is the same (single sub-component per component).

### Example: repeating segments (multiple OBX)

Repeating segments like OBX, NK1, DG1, or AL1 appear as **separate entries** in the
`segments` list — they are not grouped or merged:

**Input:**
```
MSH|^~\&|Lab|Fac||||ORU^R01|1|P|2.3
PID|1||12345
OBR|1|||CBC
OBX|1|NM|WBC||7.2|10*3/uL
OBX|2|NM|RBC||4.5|10*6/uL
OBX|3|NM|HGB||13.8|g/dL
```

**Output:**
```json
{
  "segments": [
    { "name": "MSH", "fields": ["|", "^~\\&", "Lab", "Fac", "", "", "", "", ["ORU", "R01"], "1", "P", "2.3"] },
    { "name": "PID", "fields": ["1", "", "12345"] },
    { "name": "OBR", "fields": ["1", "", "", "CBC"] },
    { "name": "OBX", "fields": ["1", "NM", "WBC", "", "7.2", "10*3/uL"] },
    { "name": "OBX", "fields": ["2", "NM", "RBC", "", "4.5", "10*6/uL"] },
    { "name": "OBX", "fields": ["3", "NM", "HGB", "", "13.8", "g/dL"] }
  ]
}
```

To extract all OBX segments from a parsed message:

```python
obx_segments = [s for s in msg["segments"] if s["name"] == "OBX"]
for obx in obx_segments:
    test_name = obx["fields"][2]   # OBX-3: observation identifier
    value     = obx["fields"][4]   # OBX-5: observation value
    units     = obx["fields"][5]   # OBX-6: units
    print(f"{test_name}: {value} {units}")
# WBC: 7.2 10*3/uL
# RBC: 4.5 10*6/uL
# HGB: 13.8 g/dL
```

### Example: sub-components (`&` separator)

**Input:** `TST|auth_id&universal_id&universal_type`

**Output:**
```json
{ "name": "TST", "fields": [["auth_id", "universal_id", "universal_type"]] }
```

Sub-components and components both collapse to a list of strings when there is only
one level of nesting. A field with both components *and* sub-components produces
nested lists:

**Input:** `TST|a&b^c` (first component has 2 sub-components, second has 1)

**Output:**
```json
{ "name": "TST", "fields": [[["a", "b"], "c"]] }
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
