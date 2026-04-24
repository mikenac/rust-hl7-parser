# rust-hl7-parser

A fast HL7v2 message parser written in Rust with Python bindings.

<!-- badges: PyPI and CI badges will go here once published -->

## Features

- **10x faster than python-hl7, 255x faster than hl7apy** (parse + validate) — see benchmarks below
- **Zero-copy Rust parser via PyO3** — returns native Python dicts with no intermediate representations
- **Lenient mode** skips malformed segments and reports structured warnings instead of raising
- **JSON output path** (`parse_json`, `parse_file_json`) avoids Python dict construction overhead entirely
- **Annotated JSON output** (`parse_annotated_json`) embeds HL7 field names in every value for self-describing JSON
- **HL7 path accessor** (`get(msg, "PID-5.1")`) — extract fields using standard HL7 notation
- **File parsing** with automatic message splitting: blank-line separation, MSH-restart detection, MLLP framing stripped automatically
- **Batch parsing** for in-memory message lists via `parse_batch`
- **HL7v2 version-aware validation** covering versions 2.1 through 2.9, 16 message types, ~40 segments per version
- **PEP 561 typed** — ships `py.typed`, full type annotations
- **Single abi3 wheel** compatible with CPython 3.9+

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

### 9. Annotated JSON — self-describing output with HL7 field names

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
print(pid5["name"])                          # "patient_name"
print(pid5["value"]["components"][0]["name"]) # "family_name"
print(pid5["value"]["components"][0]["value"]) # "Doe"
```

## Choosing an output format

| Function | Returns | Throughput | Best for |
|----------|---------|------------|----------|
| `parse_json()` | JSON string (positional) | ~31,000 msg/s | Maximum speed; downstream knows HL7 field positions |
| `parse()` | Python dict (positional) | ~26,000 msg/s | Python code that needs to inspect/transform fields |
| `parse()` + `get()` | Python values via HL7 path | ~25,000 msg/s | Python code using HL7 notation (`"PID-5.1"`) |
| `parse()` + `validate()` | dict + validation result | ~16,000 msg/s | When you need schema validation |
| `parse_annotated_json()` | Self-describing JSON | ~5,300 msg/s | Downstream systems that need field names in JSON |

All numbers from 5,000 real NHS HL7v2 messages (avg 1,792 chars). For comparison:
- python-hl7: ~2,500 msg/s (parse only, no JSON output, no validation)
- hl7apy: ~100 msg/s (parse + validate, no JSON output)

**Fast path (positional):** Use `parse_json()` when throughput matters and your downstream system already understands HL7 field positions. The JSON structure uses positional arrays — `fields[8]` is MSH-9, `fields[4]` is PID-5. See "Output structure" below for the full mapping.

**Self-describing path (annotated):** Use `parse_annotated_json()` when the JSON will be consumed by systems or teams that don't want to memorize HL7 field positions. Every field carries its HL7 name, position, and value. ~6x slower than the fast path but still 47x faster than hl7apy.

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
path string), and `value`. Component fields nest their component names recursively.
Repeating fields use a `repetitions` wrapper.

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
        {"name": "field_separator",    "position": "MSH-1",  "value": "|"},
        {"name": "encoding_characters","position": "MSH-2",  "value": "^~\\&"},
        {"name": "sending_application","position": "MSH-3",  "value": {"components": [{"name": "namespace_id", "position": "MSH-3.1", "value": "SendingApp"}]}},
        {"name": "sending_facility",   "position": "MSH-4",  "value": {"components": [{"name": "namespace_id", "position": "MSH-4.1", "value": "SendingFac"}]}},
        {"name": "security",           "position": "MSH-8",  "value": ""},
        {
          "name": "message_type",
          "position": "MSH-9",
          "value": {
            "components": [
              {"name": "message_code",  "position": "MSH-9.1", "value": "ADT"},
              {"name": "trigger_event", "position": "MSH-9.2", "value": "A01"}
            ]
          }
        },
        {"name": "message_control_id", "position": "MSH-10", "value": "MSG00001"},
        {"name": "version_id",         "position": "MSH-12", "value": "2.3"}
      ]
    },
    {
      "name": "PID",
      "fields": [
        {"name": "set_id", "position": "PID-1", "value": "1"},
        {
          "name": "patient_identifier_list",
          "position": "PID-3",
          "value": {
            "components": [
              {"name": "id_number",          "position": "PID-3.1", "value": "12345"},
              {"name": "check_digit",        "position": "PID-3.2", "value": ""},
              {"name": "check_digit_scheme", "position": "PID-3.3", "value": ""},
              {"name": "assigning_authority","position": "PID-3.4", "value": "MRN"}
            ]
          }
        },
        {
          "name": "patient_name",
          "position": "PID-5",
          "value": {
            "components": [
              {"name": "family_name", "position": "PID-5.1", "value": "Doe"},
              {"name": "given_name",  "position": "PID-5.2", "value": "John"},
              {"name": "middle_name", "position": "PID-5.3", "value": "M"}
            ]
          }
        },
        {"name": "date_time_of_birth", "position": "PID-7", "value": {"components": [{"name": "time", "position": "PID-7.1", "value": "19800101"}]}},
        {"name": "administrative_sex",  "position": "PID-8", "value": "M"}
      ]
    },
    {
      "name": "PV1",
      "fields": [
        {"name": "set_id",      "position": "PV1-1", "value": "1"},
        {"name": "patient_class","position": "PV1-2", "value": "I"},
        {
          "name": "assigned_patient_location",
          "position": "PV1-3",
          "value": {
            "components": [
              {"name": "point_of_care", "position": "PV1-3.1", "value": "ICU"},
              {"name": "room",          "position": "PV1-3.2", "value": "Bed1"},
              {"name": "bed",           "position": "PV1-3.3", "value": "Main"}
            ]
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
    {"name": "set_id", "position": "NK1-1", "value": "1"},
    {
      "name": "name",
      "position": "NK1-2",
      "value": {
        "repetitions": [
          {
            "components": [
              {"name": "family_name", "position": "NK1-2.1", "value": "Smith"},
              {"name": "given_name",  "position": "NK1-2.2", "value": "Jane"}
            ]
          },
          {
            "components": [
              {"name": "family_name", "position": "NK1-2.1", "value": "Jones"},
              {"name": "given_name",  "position": "NK1-2.2", "value": "Bob"}
            ]
          }
        ]
      }
    },
    {
      "name": "relationship",
      "position": "NK1-3",
      "value": {"components": [{"name": "identifier", "position": "NK1-3.1", "value": "SPO"}]}
    }
  ]
}
```

Repeating fields use a `"repetitions"` wrapper containing a list of component
objects. Each repetition has the same component structure as a non-repeating
composite field.

#### Example: repeating OBX segments

Each OBX segment is annotated independently. All three segments in the
`segments` list carry their own `name`, `position`, and `value` objects:

```json
[
  {
    "name": "OBX",
    "fields": [
      {"name": "set_id",                "position": "OBX-1", "value": "1"},
      {"name": "value_type",            "position": "OBX-2", "value": "NM"},
      {"name": "observation_identifier","position": "OBX-3", "value": {"components": [{"name": "identifier", "position": "OBX-3.1", "value": "WBC"}]}},
      {"name": "observation_subid",     "position": "OBX-4", "value": ""},
      {"name": "observation_value",     "position": "OBX-5", "value": "7.2"},
      {"name": "units",                 "position": "OBX-6", "value": {"components": [{"name": "identifier", "position": "OBX-6.1", "value": "10*3/uL"}]}}
    ]
  },
  {
    "name": "OBX",
    "fields": [
      {"name": "set_id",                "position": "OBX-1", "value": "2"},
      {"name": "value_type",            "position": "OBX-2", "value": "NM"},
      {"name": "observation_identifier","position": "OBX-3", "value": {"components": [{"name": "identifier", "position": "OBX-3.1", "value": "RBC"}]}},
      {"name": "observation_subid",     "position": "OBX-4", "value": ""},
      {"name": "observation_value",     "position": "OBX-5", "value": "4.5"},
      {"name": "units",                 "position": "OBX-6", "value": {"components": [{"name": "identifier", "position": "OBX-6.1", "value": "10*6/uL"}]}}
    ]
  },
  {
    "name": "OBX",
    "fields": [
      {"name": "set_id",                "position": "OBX-1", "value": "3"},
      {"name": "value_type",            "position": "OBX-2", "value": "NM"},
      {"name": "observation_identifier","position": "OBX-3", "value": {"components": [{"name": "identifier", "position": "OBX-3.1", "value": "HGB"}]}},
      {"name": "observation_subid",     "position": "OBX-4", "value": ""},
      {"name": "observation_value",     "position": "OBX-5", "value": "13.8"},
      {"name": "units",                 "position": "OBX-6", "value": {"components": [{"name": "identifier", "position": "OBX-6.1", "value": "g/dL"}]}}
    ]
  }
]
```

---

### Pydantic integration (consuming annotated JSON)

Annotated JSON is designed to be consumed directly by typed Python objects. The
`val()` and `comp()` helper functions below convert the position-keyed structure
into scalar strings, making Pydantic model construction straightforward.

```python
import json
from pydantic import BaseModel
from rust_hl7_parser import parse_annotated_json


def val(fields_by_pos: dict, position: str) -> str:
    """Return the scalar value for a field position, e.g. 'MSH-3'."""
    entry = fields_by_pos.get(position)
    if entry is None:
        return ""
    v = entry.get("value", "")
    return v if isinstance(v, str) else ""


def comp(fields_by_pos: dict, position: str) -> str:
    """Return a component value by dotted position, e.g. 'PID-5.1'.

    Splits on the last dot to find the parent field ('PID-5') and then
    the component index (1-based) within that field's components list.
    """
    parent, _, idx_str = position.rpartition(".")
    entry = fields_by_pos.get(parent)
    if entry is None:
        return ""
    components = entry.get("value", {}).get("components", [])
    idx = int(idx_str) - 1  # convert 1-based HL7 index to 0-based
    if idx < 0 or idx >= len(components):
        return ""
    return components[idx].get("value", "") or ""


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
                sending_application=val(msh, "MSH-3"),
                sending_facility=val(msh, "MSH-4"),
                message_type=comp(msh, "MSH-9.1"),
                message_control_id=val(msh, "MSH-10"),
                version=val(msh, "MSH-12"),
            ),
            patient=Patient(
                patient_id=comp(pid, "PID-3.1"),
                assigning_authority=comp(pid, "PID-3.4"),
                name=PatientName(
                    family_name=comp(pid, "PID-5.1"),
                    given_name=comp(pid, "PID-5.2"),
                    middle_name=comp(pid, "PID-5.3"),
                ),
                date_of_birth=val(pid, "PID-7"),
                sex=val(pid, "PID-8"),
            ),
            visit=Visit(
                patient_class=val(pv1, "PV1-2"),
                assigned_location=comp(pv1, "PV1-3.1"),
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
#               "date_of_birth": "", "sex": "F"},
#   "visit": {"patient_class": "I", "assigned_location": "ICU", "admission_type": "E"}
# }
```

## API Reference

| Function | Returns | Description |
|----------|---------|-------------|
| `parse(message, strict=True)` | `dict` | Parse single HL7v2 message |
| `parse_json(message, strict=True)` | `str` | Parse to JSON string |
| `parse_file(path, strict=True)` | `list[dict]` | Parse a .hl7 file containing one or more messages |
| `parse_file_json(path, strict=True)` | `str` | Parse file, return JSON array string |
| `parse_batch(messages, strict=True)` | `list[dict]` | Parse a list of message strings |
| `parse_to_json(message, strict=True)` | `bytes` | Parse and return orjson bytes |
| `parse_file_to_json(path, strict=True)` | `bytes` | Parse file and return orjson bytes |
| `parse_annotated(message, strict=True, version=None)` | `dict` | Parse with HL7 field names embedded in output |
| `parse_annotated_json(message, strict=True, version=None)` | `str` | Same but returns JSON string |
| `get(msg, path, default=None, rep=None)` | `str \| None` | Extract a value by HL7 path (e.g. `"PID-5.1"`) |
| `segments(msg, name)` | `list[dict]` | All segment dicts with the given name |
| `field(seg, field_num, component=None)` | `str \| list \| None` | Low-level field access on a segment dict |
| `all_values(msg, path)` | `list` | Collect a field value from every occurrence of a segment |
| `first(msg, name)` | `dict \| None` | First segment with the given name, or None |
| `validate(message_dict, strict=True, version=None)` | `dict` | Validate a parsed message dict |
| `validate_file(path, strict=True)` | `list[dict]` | Validate all messages in a file |
| `validate_file_summary(path, strict=True)` | `dict` | Summary stats for all messages in a file |

## Benchmarks

Benchmarked against 5,000 real NHS HL7v2 messages (average 1,792 characters each):

```
Pipeline                                  Throughput     Relative
parse_json() — positional JSON            31,190 msg/s   fastest
parse() — Python dict                     26,494 msg/s   baseline
parse() + get() — HL7 path accessor      ~25,000 msg/s   accessor overhead negligible
parse_batch() — batch mode               20,797 msg/s   batch overhead
parse() + validate()                     16,407 msg/s   with schema validation
parse_annotated_json() — self-describing  5,254 msg/s   self-describing JSON
python-hl7 (parse only)                   2,530 msg/s   10x slower
hl7apy (parse + validate)                   102 msg/s   255x slower, no JSON output
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
