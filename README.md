# rust-hl7-parser

A fast HL7v2 message parser written in Rust with Python bindings.

<!-- badges: PyPI and CI badges will go here once published -->

## Features

- **10x faster than python-hl7, 255x faster than hl7apy** (parse + validate) — see benchmarks below
- **Zero-copy Rust parser via PyO3** — returns native Python dicts with no intermediate representations
- **Usable as a pure Rust library** — `pub mod parser / types / error`; PyO3 bindings are opt-in via the `python` feature
- **Lenient mode** skips malformed segments and reports structured warnings instead of raising
- **JSON output path** (`parse_json`, `parse_file_json`) avoids Python dict construction overhead entirely
- **Lossless JSON output** (`parse_lossless_json`) preserves the full Field → Repetition → Component → SubComponent tree for round-trip and diff use cases
- **Typed annotated JSON output** (`parse_annotated_json`) embeds HL7 field names, type codes, and flat component dicts in every value for self-describing JSON
- **HL7 path accessor** (`get(msg, "PID-5.1")`) — extract fields using standard HL7 notation
- **All-repetitions accessor** (`field_reps(msg, "AL1-5")`) — returns every `~`-separated repetition of a field
- **File parsing** with automatic message splitting: blank-line separation, MSH-restart detection, MLLP framing stripped automatically
- **Batch parsing** for in-memory message lists via `parse_batch`
- **HL7v2 version-aware validation** covering versions 2.1 through 2.9, 16 message types, ~40 segments per version
- **PEP 561 typed** — ships `py.typed`, full type annotations
- **Single abi3 wheel** compatible with CPython 3.13+

## Installation

### Python

```
pip install rust-hl7-parser
```

### Development

```bash
pip install maturin
git clone https://github.com/mikenac/rust-hl7-parser
cd rust-hl7-parser
maturin develop
pytest tests/
```

### Rust library

To use the parser from Rust without the Python bindings, disable the default
`python` feature:

```toml
# Cargo.toml
[dependencies]
rust-hl7-parser = { git = "https://github.com/mikenac/rust-hl7-parser", default-features = false }
```

## Rust quick start

The three public modules mirror the internal structure exactly:

| Module | Contents |
|--------|----------|
| `rust_hl7_parser::parser` | `parse()`, `parse_lenient()`, `group_message_lines()`, `parse_message_groups()` |
| `rust_hl7_parser::types` | `Hl7Message`, `Hl7Segment`, `Hl7Field`, `Hl7Repetition`, `Hl7Component` |
| `rust_hl7_parser::error` | `ParseMode`, `ParseError`, `LenientResult` |

### Basic parse

```rust
use rust_hl7_parser::{parser, error::ParseMode};

let raw = "MSH|^~\\&|SendingApp|SendingFac|RecvApp|RecvFac|20230101||ADT^A01|MSG001|P|2.3\r\
           PID|1||12345^^^MRN||Doe^John^M||19800101|M\r\
           PV1|1|I|ICU^Bed1^Main";

let (msg, _warnings) = parser::parse(raw, ParseMode::Strict).unwrap();

println!("{}", msg.segments[0].name);   // "MSH"
println!("{}", msg.segments.len());     // 3
```

### Navigating the type tree

The Rust representation is always fully structured — no collapsing:

```rust
use rust_hl7_parser::{parser, error::ParseMode};

let raw = "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r\
           PID|1||12345^^^MRN||Doe^John^M";

let (msg, _) = parser::parse(raw, ParseMode::Strict).unwrap();

let pid = &msg.segments[1];

// PID-5 = Doe^John^M: one repetition, three components, each a scalar sub-component
let pid5 = &pid.fields[4];                              // zero-indexed
let rep   = &pid5.repetitions[0];
let family = rep.components[0].sub_components[0].as_ref(); // "Doe"
let given  = rep.components[1].sub_components[0].as_ref(); // "John"

// PID-3 = 12345^^^MRN: CX datatype — four components, sub-component [0] each
let pid3      = &pid.fields[2];
let id_number = pid3.repetitions[0].components[0].sub_components[0].as_ref(); // "12345"
let authority = pid3.repetitions[0].components[3].sub_components[0].as_ref(); // "MRN"
```

### Lenient mode and warnings

```rust
use rust_hl7_parser::{parser, error::ParseMode};

let raw = "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r\
           BA\r\
           PID|1||12345";

let (msg, warnings) = parser::parse(raw, ParseMode::Lenient).unwrap();

println!("{}", msg.segments.len());   // 2 — MSH + PID (BA skipped)
println!("{}", warnings[0]);          // "Skipping malformed segment..."
```

### Repeating fields

```rust
use rust_hl7_parser::{parser, error::ParseMode};

let raw = "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r\
           AL1|1|DA|PENICILLIN|MO|RASH~HIVES~NAUSEA";

let (msg, _) = parser::parse(raw, ParseMode::Strict).unwrap();

let al1   = &msg.segments[1];
let al1_5 = &al1.fields[4];   // zero-indexed

// Three repetitions, each a scalar
for rep in &al1_5.repetitions {
    let reaction = rep.components[0].sub_components[0].as_ref();
    println!("{}", reaction);   // RASH, then HIVES, then NAUSEA
}
```

### Batch and file parsing

```rust
use rust_hl7_parser::{parser, error::ParseMode};

// Parse a multi-message file
let content = std::fs::read_to_string("messages.hl7").unwrap();
let groups  = parser::group_message_lines(&content);
let results = parser::parse_message_groups(&groups, ParseMode::Lenient);

for (i, result) in results.into_iter().enumerate() {
    let (msg, warnings) = result.unwrap();
    println!("Message {}: {} segments, {} warnings", i, msg.segments.len(), warnings.len());
}
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

### 8. Extract fields using HL7 path notation

```python
from rust_hl7_parser import parse, get, all_values

msg = parse(
    "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
    "PID|1||12345^^^MRN||Doe^John^M\r"
    "OBX|1|NM|WBC||7.2\r"
    "OBX|2|NM|RBC||4.5"
)

print(get(msg, "MSH-9.1"))        # "ADT"
print(get(msg, "PID-5.1"))        # "Doe"
print(get(msg, "PID-3.4"))        # "MRN"
print(get(msg, "OBX[2]-5"))       # "4.5"  (second OBX segment)
print(all_values(msg, "OBX-5"))   # ["7.2", "4.5"]
```

### 9. Get all repetitions of a repeating field

`get()` returns only the first repetition of a repeating field. Use
`field_reps()` when a single segment field holds multiple values separated
by `~`, such as allergy reaction codes or repeating insurance identifiers.

```python
from rust_hl7_parser import parse, field_reps, get

msg = parse(
    "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
    "AL1|1|DA|PENICILLIN^Penicillin|MO|RASH~HIVES~NAUSEA\r"
    "AL1|2|FA|PEANUTS^Peanut allergy|SV|ANAPHYLAXIS"
)

# All reaction codes from the first AL1 segment
reactions = field_reps(msg, "AL1-5")   # ["RASH", "HIVES", "NAUSEA"]

# get() silently returns only the first
get(msg, "AL1-5")                       # "RASH"

# For the second AL1 segment (single reaction — still returns a list)
field_reps(msg, "AL1[2]-5")            # ["ANAPHYLAXIS"]
```

For a segment with a repeating composite field (multiple structured values
per field), `field_reps()` returns a list of component lists:

```python
msg = parse(
    "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
    "NK1|1|Smith^Jane~Jones^Bob|SPO"
)

reps = field_reps(msg, "NK1-2")
# [["Smith", "Jane"], ["Jones", "Bob"]]

# Iterate over all next-of-kin names
for name in reps:
    print(name[0], name[1])   # family, given
```

### 10. Annotated JSON — self-describing output with HL7 field names

```python
from rust_hl7_parser import parse_annotated_json
import json

annotated = parse_annotated_json(
    "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r"
    "PID|1||12345^^^MRN||Doe^John^M",
    strict=False
)
data = json.loads(annotated)

pid_fields = data["segments"][1]["fields"]
pid5 = next(f for f in pid_fields if f["position"] == "PID-5")
print(pid5["name"])                    # "patient_name"
print(pid5["type"])                    # "XPN"
print(pid5["value"]["family_name"])    # "Doe"
print(pid5["value"]["given_name"])     # "John"
```

## Choosing an output format

| Function | Returns | Throughput | Best for |
|----------|---------|------------|----------|
| `parse_json()` | JSON string (positional, lossy) | ~6,300 msg/s | Maximum speed; downstream knows HL7 field positions |
| `parse()` | Python dict (positional, lossy) | ~6,500 msg/s | Python code that needs to inspect/transform fields |
| `parse()` + `get()` | Python values via HL7 path | ~6,000 msg/s | Python code using HL7 notation (`"PID-5.1"`) |
| `parse()` + `validate()` | dict + validation result | ~5,300 msg/s | When you need schema validation |
| `parse_annotated_json()` | Self-describing JSON (semantic, not round-trip lossless) | ~3,300 msg/s | Downstream systems that need field names in JSON |
| `parse_lossless_json()` | Structural JSON (lossless) | ~1,450 msg/s | Round-trip serialisation, diff/edit tools |
| `parse_hl7apy_compat()` | hl7apy-format dict + JSON | ~1,160 msg/s | Drop-in replacement for hl7apy `extract_message` |
| hl7apy `extract_message` | hl7apy-format dict + JSON | ~90 msg/s | (baseline — 13× slower than `parse_hl7apy_compat`) |

### Lossy vs lossless

`parse()` and `parse_json()` apply a **collapsing rule** at the Python
boundary: single-item wrappers are unwrapped so that simple values surface
as plain strings rather than nested structures. This makes the common case
ergonomic but loses structural information:

| HL7 input | Python output | Ambiguous? |
|-----------|---------------|------------|
| `A` | `"A"` | No |
| `A^B^C` (components) | `["A", "B", "C"]` | Yes — same as below |
| `A~B~C` (repetitions) | `["A", "B", "C"]` | Yes — same as above |
| `A&B&C` (sub-components) | `["A", "B", "C"]` | Yes — same as above |
| `A^B~C^D` (repeating composite) | `[["A","B"],["C","D"]]` | No |

**Use `parse_annotated_json()`** when you need field names and types for
downstream consumption. Note it is *not* lossless: sub-components are
collapsed to their first element, and composite values are mapped to named
dicts rather than preserved as positional arrays. **Use
`parse_lossless_json()`** when you need to know *which* separator was used
or want to reconstruct the original HL7 text exactly.

**`get()` and `all_values()`** are safe when used with explicit HL7 path
notation — `get(msg, "PID-5.1")`, `get(msg, "PV1-3.4")`, and similar always
return the correct value regardless of how the underlying field was
represented. Ambiguity only arises when code inspects the raw collapsed
Python structures directly (e.g. indexing `msg["segments"][n]["fields"][m]`
by hand on a field that could be either repeating or composite). Use the
`rep=` parameter on `get()` for explicit repetition access, and `field_reps()`
to retrieve all repetitions of a repeating field.

**`field_reps()`** returns all repetitions of a field as a list. It is the
correct tool for fields like `AL1-5` (allergy reaction codes), `IN1-3`
(insurance company IDs), and any other field that repeats within a single
segment. `get()` and `all_values()` return only the first repetition.

All numbers from 5,000 real NHS HL7v2 messages (avg 1,792 chars). For comparison:
- python-hl7: ~2,500 msg/s (parse only, no JSON output, no validation)
- hl7apy: ~100 msg/s (parse + validate, no JSON output)

**Fast path (positional):** Use `parse_json()` when throughput matters and your downstream system already understands HL7 field positions. The JSON structure uses positional arrays — `fields[8]` is MSH-9, `fields[4]` is PID-5. See "Output structure" below for the full mapping.

**Self-describing path (annotated):** Use `parse_annotated_json()` when the JSON will be consumed by systems or teams that don't want to memorize HL7 field positions. Every field carries its HL7 name, position, type code, and value. Composite values are flat dicts keyed by component name — access `pid5["value"]["family_name"]` directly. ~6x slower than the fast path but still 47x faster than hl7apy.

**Python accessor path:** Use `parse()` + `get(msg, "PID-5.1")` when you're building Python objects (Pydantic models, dataclasses) and want HL7-native field notation without the overhead of annotated JSON.

## Output structure

### Positional output (`parse()` / `parse_json()`)

Both `parse()` and `parse_json()` return the same structure. Fields are
**automatically collapsed** so simple values surface as plain strings, while
complex structures remain as nested lists.

#### Collapsing rules

The parser applies these rules innermost-first:

| HL7 structure | Single item | Multiple items |
|---------------|-------------|----------------|
| Sub-components (`&`) | `"value"` | `["a", "b"]` |
| Components (`^`) | collapsed sub-component | `["Doe", "John", "M"]` |
| Repetitions (`~`) | collapsed component | `["val1", "val2"]` |
| Field | collapsed repetition | list of repetitions |

#### Example: ADT^A01 with components and sub-components

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
- **Simple fields** like `"SendingApp"` — plain string
- **Components** like `ADT^A01` — `["ADT", "A01"]`
- **Sub-components** like `12345^^^MRN` — `["12345", "", "", "MRN"]` (empty strings preserved)
- **MSH-1** is always `"|"`, **MSH-2** is always `"^~\\&"` (stored as literal strings, not parsed)

#### Cross-reference: raw Python access vs. `get()` accessor

| HL7 path | Raw Python access | `get()` call |
|----------|-------------------|--------------|
| `MSH-9.1` | `msg["segments"][0]["fields"][8][0]` | `get(msg, "MSH-9.1")` |
| `PID-5.1` | `pid["fields"][4][0]` | `get(msg, "PID-5.1")` |
| `PID-3.4` | `pid["fields"][2][3]` | `get(msg, "PID-3.4")` |
| `OBX[2]-5` | `segments(msg, "OBX")[1]["fields"][4]` | `get(msg, "OBX[2]-5")` |

#### Example: repeating fields (`~` separator)

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

NK1-3 has **repeating simple fields**: `SPO~EMC` — `["SPO", "EMC"]`.

Note: a repeating simple field and a multi-component field both produce a flat list
of strings — the parser collapses them identically because the underlying HL7
structure is the same (single sub-component per component).

#### Example: repeating segments (multiple OBX)

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

Using `get()` and `all_values()` for the same result:

```python
from rust_hl7_parser import get, all_values, segments

test_names = all_values(msg, "OBX-3")   # ["WBC", "RBC", "HGB"]
values     = all_values(msg, "OBX-5")   # ["7.2", "4.5", "13.8"]
```

#### Example: sub-components (`&` separator)

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

---

### Annotated output (`parse_annotated()` / `parse_annotated_json()`)

Annotated output transforms the positional arrays into self-describing objects. Every
field carries its `name` (the HL7 field name from the schema), `position` (the HL7
path string), `type` (the HL7 datatype code, e.g. `"XPN"`, `"CX"`, `"PL"`), and
`value`. Composite field values are flat dicts keyed by component name from the HL7
datatype definition. Repeating fields have their value as a list of such dicts and
carry `"repeating": true`.

This format is ~6x slower than positional output but still 47x faster than hl7apy,
and it eliminates the need for consumers to know HL7 field positions.

#### Example: ADT^A01 (MSH + PID + PV1)

**Input:**
```
MSH|^~\&|SendingApp|SendingFac|RecvApp|RecvFac|20230101120000||ADT^A01|MSG00001|P|2.3
PID|1||12345^^^MRN||Doe^John^M||19800101|M
PV1|1|I|ICU^Bed1^Main
```

**Output (trimmed for readability):**
```json
{
  "segments": [
    {
      "name": "MSH",
      "fields": [
        {"name": "field_separator",    "position": "MSH-1",  "type": "ST",  "value": "|"},
        {"name": "encoding_characters","position": "MSH-2",  "type": "ST",  "value": "^~\\&"},
        {"name": "sending_application","position": "MSH-3",  "type": "HD",  "value": {"namespace_id": "SendingApp", "universal_id": "", "universal_id_type": ""}},
        {"name": "sending_facility",   "position": "MSH-4",  "type": "HD",  "value": {"namespace_id": "SendingFac", "universal_id": "", "universal_id_type": ""}},
        {"name": "security",           "position": "MSH-8",  "type": "ST",  "value": ""},
        {
          "name": "message_type",
          "position": "MSH-9",
          "type": "CM",
          "value": {"message_code": "ADT", "trigger_event": "A01", "message_structure": ""}
        },
        {"name": "message_control_id", "position": "MSH-10", "type": "ST",  "value": "MSG00001"},
        {"name": "version_id",         "position": "MSH-12", "type": "ID",  "value": "2.3"}
      ]
    },
    {
      "name": "PID",
      "fields": [
        {"name": "set_id", "position": "PID-1", "type": "SI", "value": "1"},
        {
          "name": "patient_identifier_list",
          "position": "PID-3",
          "type": "CX",
          "value": {
            "id_number": "12345",
            "check_digit": "",
            "check_digit_scheme": "",
            "assigning_authority": "MRN",
            "identifier_type_code": "",
            "assigning_facility": ""
          }
        },
        {
          "name": "patient_name",
          "position": "PID-5",
          "type": "XPN",
          "value": {
            "family_name": "Doe",
            "given_name": "John",
            "middle_name": "M",
            "suffix": "",
            "prefix": "",
            "degree": "",
            "name_type_code": ""
          }
        },
        {
          "name": "date_time_of_birth",
          "position": "PID-7",
          "type": "TS",
          "value": {"time": "19800101", "degree_of_precision": ""}
        },
        {"name": "administrative_sex", "position": "PID-8", "type": "IS", "value": "M"}
      ]
    },
    {
      "name": "PV1",
      "fields": [
        {"name": "set_id",       "position": "PV1-1", "type": "SI", "value": "1"},
        {"name": "patient_class","position": "PV1-2", "type": "IS", "value": "I"},
        {
          "name": "assigned_patient_location",
          "position": "PV1-3",
          "type": "PL",
          "value": {
            "point_of_care": "ICU",
            "room": "Bed1",
            "bed": "Main",
            "facility": "",
            "location_status": "",
            "person_location_type": "",
            "building": "",
            "floor": "",
            "location_description": ""
          }
        }
      ]
    }
  ]
}
```

#### Example: repeating fields (NK1-2 with `~` separator)

**Input:** `NK1|1|Smith^Jane~Jones^Bob|SPO`

**NK1 segment output:**
```json
{
  "name": "NK1",
  "fields": [
    {"name": "set_id", "position": "NK1-1", "type": "SI", "value": "1"},
    {
      "name": "name",
      "position": "NK1-2",
      "type": "XPN",
      "repeating": true,
      "value": [
        {"family_name": "Smith", "given_name": "Jane", "middle_name": "", "suffix": "", "prefix": "", "degree": "", "name_type_code": ""},
        {"family_name": "Jones", "given_name": "Bob",  "middle_name": "", "suffix": "", "prefix": "", "degree": "", "name_type_code": ""}
      ]
    },
    {
      "name": "relationship",
      "position": "NK1-3",
      "type": "CE",
      "repeating": true,
      "value": [
        {"identifier": "SPO", "text": "", "coding_system": "", "alt_identifier": "", "alt_text": "", "alt_coding_system": ""},
        {"identifier": "EMC", "text": "", "coding_system": "", "alt_identifier": "", "alt_text": "", "alt_coding_system": ""}
      ]
    }
  ]
}
```

Repeating fields carry `"repeating": true` and their `value` is a list of flat
typed dicts. Each dict in the list has the same keys as a non-repeating composite
field of the same datatype.

#### Example: repeating OBX segments

Each OBX segment is annotated independently. All three segments in the
`segments` list carry their own `name`, `position`, and `value` objects:

```json
[
  {
    "name": "OBX",
    "fields": [
      {"name": "set_id",                "position": "OBX-1", "type": "SI", "value": "1"},
      {"name": "value_type",            "position": "OBX-2", "type": "ID", "value": "NM"},
      {"name": "observation_identifier","position": "OBX-3", "type": "CE", "value": {"identifier": "WBC", "text": "", "coding_system": "", "alt_identifier": "", "alt_text": "", "alt_coding_system": ""}},
      {"name": "observation_subid",     "position": "OBX-4", "type": "ST", "value": ""},
      {"name": "observation_value",     "position": "OBX-5", "type": "ST", "value": "7.2"},
      {"name": "units",                 "position": "OBX-6", "type": "CE", "value": {"identifier": "10*3/uL", "text": "", "coding_system": "", "alt_identifier": "", "alt_text": "", "alt_coding_system": ""}}
    ]
  },
  {
    "name": "OBX",
    "fields": [
      {"name": "set_id",                "position": "OBX-1", "type": "SI", "value": "2"},
      {"name": "value_type",            "position": "OBX-2", "type": "ID", "value": "NM"},
      {"name": "observation_identifier","position": "OBX-3", "type": "CE", "value": {"identifier": "RBC", "text": "", "coding_system": "", "alt_identifier": "", "alt_text": "", "alt_coding_system": ""}},
      {"name": "observation_subid",     "position": "OBX-4", "type": "ST", "value": ""},
      {"name": "observation_value",     "position": "OBX-5", "type": "ST", "value": "4.5"},
      {"name": "units",                 "position": "OBX-6", "type": "CE", "value": {"identifier": "10*6/uL", "text": "", "coding_system": "", "alt_identifier": "", "alt_text": "", "alt_coding_system": ""}}
    ]
  },
  {
    "name": "OBX",
    "fields": [
      {"name": "set_id",                "position": "OBX-1", "type": "SI", "value": "3"},
      {"name": "value_type",            "position": "OBX-2", "type": "ID", "value": "NM"},
      {"name": "observation_identifier","position": "OBX-3", "type": "CE", "value": {"identifier": "HGB", "text": "", "coding_system": "", "alt_identifier": "", "alt_text": "", "alt_coding_system": ""}},
      {"name": "observation_subid",     "position": "OBX-4", "type": "ST", "value": ""},
      {"name": "observation_value",     "position": "OBX-5", "type": "ST", "value": "13.8"},
      {"name": "units",                 "position": "OBX-6", "type": "CE", "value": {"identifier": "g/dL", "text": "", "coding_system": "", "alt_identifier": "", "alt_text": "", "alt_coding_system": ""}}
    ]
  }
]
```

---

### Lossless output (`parse_lossless_json()`)

`parse_lossless_json()` serialises the internal Rust parse tree without any
collapsing.  Every field is always an object with a `repetitions` array;
every repetition has a `components` array; every component has a
`sub_components` array.  All three separator levels are always explicit.

This makes it possible to distinguish `A^B` (components), `A~B`
(repetitions), and `A&B` (sub-components), which all collapse to `["A","B"]`
in the positional output.

**Example:** `PID-5 = Doe^John^M` (single repetition, three components)

```json
{
  "repetitions": [
    {
      "components": [
        {"sub_components": ["Doe"]},
        {"sub_components": ["John"]},
        {"sub_components": ["M"]}
      ]
    }
  ]
}
```

**Example:** `AL1-5 = RASH~HIVES` (two simple repetitions)

```json
{
  "repetitions": [
    {"components": [{"sub_components": ["RASH"]}]},
    {"components": [{"sub_components": ["HIVES"]}]}
  ]
}
```

These two produce identical output from `parse()` (`["Doe","John","M"]` and
`["RASH","HIVES"]` respectively) — only `parse_lossless_json()` preserves the
distinction.

---

### Pydantic integration (consuming annotated JSON)

With the typed format, component values are directly accessible as dict keys —
no helper functions needed for composite fields. The `val()` helper is still
useful for plain scalar fields; a `typed()` helper covers composite fields.

```python
import json
from pydantic import BaseModel
from rust_hl7_parser import parse_annotated_json


def val(fields_by_pos: dict, position: str) -> str:
    """Return the scalar string value for a field position, e.g. 'MSH-3'."""
    entry = fields_by_pos.get(position)
    if entry is None:
        return ""
    v = entry.get("value", "")
    return v if isinstance(v, str) else ""


def typed(fields_by_pos: dict, position: str, key: str) -> str:
    """Return a component value from a typed composite field.

    Example: typed(pid, "PID-5", "family_name")
    """
    entry = fields_by_pos.get(position)
    if entry is None:
        return ""
    value = entry.get("value", {})
    if isinstance(value, dict):
        return value.get(key, "") or ""
    return ""


class MessageHeader(BaseModel):
    sending_application: str
    sending_facility: str
    message_type: str
    message_control_id: str
    version: str


class PatientName(BaseModel):
    family_name: str
    given_name: str
    middle_name: str


class Patient(BaseModel):
    patient_id: str
    assigning_authority: str
    name: PatientName
    date_of_birth: str
    sex: str


class Visit(BaseModel):
    patient_class: str
    assigned_location: str
    admission_type: str


class PatientVisit(BaseModel):
    header: MessageHeader
    patient: Patient
    visit: Visit

    @classmethod
    def from_hl7_json(cls, annotated_json_string: str) -> "PatientVisit":
        data = json.loads(annotated_json_string)

        # Build a position-keyed lookup for each segment
        def index_segment(seg_name: str) -> dict:
            for seg in data["segments"]:
                if seg["name"] == seg_name:
                    return {f["position"]: f for f in seg["fields"]}
            return {}

        msh = index_segment("MSH")
        pid = index_segment("PID")
        pv1 = index_segment("PV1")

        return cls(
            header=MessageHeader(
                sending_application=typed(msh, "MSH-3", "namespace_id"),
                sending_facility=typed(msh, "MSH-4", "namespace_id"),
                message_type=typed(msh, "MSH-9", "message_code"),
                message_control_id=val(msh, "MSH-10"),
                version=val(msh, "MSH-12"),
            ),
            patient=Patient(
                patient_id=typed(pid, "PID-3", "id_number"),
                assigning_authority=typed(pid, "PID-3", "assigning_authority"),
                name=PatientName(
                    family_name=typed(pid, "PID-5", "family_name"),
                    given_name=typed(pid, "PID-5", "given_name"),
                    middle_name=typed(pid, "PID-5", "middle_name"),
                ),
                date_of_birth=typed(pid, "PID-7", "time"),
                sex=val(pid, "PID-8"),
            ),
            visit=Visit(
                patient_class=val(pv1, "PV1-2"),
                assigned_location=typed(pv1, "PV1-3", "point_of_care"),
                admission_type=val(pv1, "PV1-4"),
            ),
        )


# Usage
raw_hl7 = (
    "MSH|^~\\&|HIS|GENERAL|ADT|GENERAL|20230615120000||ADT^A01|MSG00042|P|2.4\r"
    "PID|1||98765^^^MRN||Smith^Jane^A|||F\r"
    "PV1|1|I|ICU^Bed4^GH|E"
)

annotated_json = parse_annotated_json(raw_hl7, strict=False)
visit = PatientVisit.from_hl7_json(annotated_json)
print(visit.model_dump_json(indent=2))
# {
#   "header": {"sending_application": "HIS", "sending_facility": "GENERAL",
#              "message_type": "ADT", "message_control_id": "MSG00042", "version": "2.4"},
#   "patient": {"patient_id": "98765", "assigning_authority": "MRN",
#               "name": {"family_name": "Smith", "given_name": "Jane", "middle_name": "A"},
#               "date_of_birth": "19800101", "sex": "F"},
#   "visit": {"patient_class": "I", "assigned_location": "ICU", "admission_type": "E"}
# }
```

## API Reference

| Function | Returns | Description |
|----------|---------|-------------|
| `parse(message, strict=True)` | `dict` | Parse single HL7v2 message. Lossy: single-item wrappers are collapsed. |
| `parse_json(message, strict=True)` | `str` | Parse to JSON string. Same collapsing as `parse()`. |
| `parse_lossless_json(message, strict=True)` | `str` | Parse to fully lossless JSON preserving all Field/Repetition/Component/SubComponent structure. For round-trip serialisation, diff tools, HL7 editors. |
| `parse_file(path, strict=True)` | `list[dict]` | Parse a .hl7 file containing one or more messages |
| `parse_file_json(path, strict=True)` | `str` | Parse file, return JSON array string |
| `parse_batch(messages, strict=True)` | `list[dict]` | Parse a list of message strings |
| `parse_to_json(message, strict=True)` | `bytes` | Parse and return orjson bytes |
| `parse_file_to_json(path, strict=True)` | `bytes` | Parse file and return orjson bytes |
| `parse_annotated(message, strict=True, version=None)` | `dict` | Parse with HL7 field names embedded in output |
| `parse_annotated_json(message, strict=True, version=None)` | `str` | Same but returns JSON string |
| `get(msg, path, default=None, rep=None)` | `str \| None` | Extract a value by HL7 path (e.g. `"PID-5.1"`). Returns first repetition only. |
| `field_reps(msg, path)` | `list` | All repetitions of a repeating field (e.g. `AL1-5`, `IN1-3`). |
| `segments(msg, name)` | `list[dict]` | All segment dicts with the given name |
| `field(seg, field_num, component=None)` | `str \| list \| None` | Low-level field access on a segment dict |
| `all_values(msg, path)` | `list` | Collect a field value from every occurrence of a segment. Returns first repetition per segment. |
| `first(msg, name)` | `dict \| None` | First segment with the given name, or None |
| `validate(message_dict, strict=True, version=None)` | `dict` | Validate a parsed message dict |
| `validate_file(path, strict=True)` | `list[dict]` | Validate all messages in a file |
| `validate_file_summary(path, strict=True)` | `dict` | Summary stats for all messages in a file |

## Benchmarks

Benchmarked against 2,000 real NHS HL7v2 messages (average 1,805 characters each):

```
Pipeline                                  Throughput     Relative to hl7apy extract
parse() — Python dict                      6,514 msg/s   72x
parse_json() — positional JSON             6,260 msg/s   70x
parse() + validate()                       5,278 msg/s   59x
parse_annotated_json() — self-describing   3,293 msg/s   37x
parse_lossless_json() — structural         1,453 msg/s   16x
parse_hl7apy_compat() — compat shim        1,159 msg/s   13x
python-hl7 (parse only)                      ~600 msg/s    7x
hl7apy parse_message() only                  110 msg/s    1.2x
hl7apy full extract_message()                 90 msg/s   baseline
```

`parse_hl7apy_compat()` uses `parse_lossless_json()` internally to correctly
distinguish repeating fields from composite fields.  The ~20% overhead over
the raw lossless output is the Python-side field-key mapping and dict
construction.

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
