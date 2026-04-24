"""
HL7v2 Version-Aware Validator
==============================

Post-parse validation layer that checks parsed HL7v2 messages against
version-specific schema definitions.

Usage::

    from rust_hl7_parser import parse, validate, validate_file

    msg = parse("MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|123|P|2.3\\rPID|1||12345|||Doe^John\\rPV1|1|I\\rEVN||20230101")
    result = validate(msg)
    print(result["valid"], result["version"], result["issues"])

"""
from __future__ import annotations

import copy
import json as _json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import orjson as _orjson
    _ORJSON_AVAILABLE = True
except ImportError:
    _orjson = None  # type: ignore[assignment]
    _ORJSON_AVAILABLE = False

# ---------------------------------------------------------------------------
# Schema loading helpers
# ---------------------------------------------------------------------------

_SCHEMA_DIR = Path(__file__).parent / "schemas"

# Map canonical version strings to schema file stems.
_VERSION_FILE_MAP: dict[str, str] = {
    "2.1":   "v2_1",
    "2.2":   "v2_2",
    "2.3":   "v2_3",
    "2.3.1": "v2_3_1",
    "2.4":   "v2_4",
    "2.5":   "v2_5",
    "2.5.1": "v2_5_1",
    "2.6":   "v2_6",
    "2.7":   "v2_7",
    "2.7.1": "v2_7_1",
    "2.8":   "v2_8",
    "2.8.1": "v2_8_1",
    "2.8.2": "v2_8_2",
    "2.9":   "v2_9",
}

# Ordered list of known versions for nearest-match logic.
_KNOWN_VERSIONS_ORDERED: list[str] = [
    "2.1", "2.2", "2.3", "2.3.1", "2.4",
    "2.5", "2.5.1", "2.6",
    "2.7", "2.7.1", "2.8", "2.8.1", "2.8.2",
    "2.9",
]


def _load_json(name: str) -> dict[str, Any]:
    """Load a JSON schema file by stem name."""
    path = _SCHEMA_DIR / f"{name}.json"
    if _ORJSON_AVAILABLE:
        return _orjson.loads(path.read_bytes())  # type: ignore[union-attr]
    return _json.loads(path.read_bytes())


def _merge_schemas(parent: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """
    Merge a delta schema on top of a parent schema.

    Segments present in the delta override/extend parent segments.
    Delta segment fields are merged into parent segment fields (delta wins
    on per-field conflicts). The delta may also update max_fields.
    """
    merged: dict[str, Any] = {
        "version": delta["version"],
        "inherits": delta.get("inherits"),
        "segments": copy.deepcopy(parent.get("segments", {})),
    }

    for seg_name, delta_seg in delta.get("segments", {}).items():
        if seg_name in merged["segments"]:
            parent_seg = merged["segments"][seg_name]
            new_seg = copy.deepcopy(parent_seg)
            # Update max_fields if delta specifies it.
            if "max_fields" in delta_seg:
                new_seg["max_fields"] = delta_seg["max_fields"]
            # Merge field definitions — delta entries override parent.
            for fnum, fdef in delta_seg.get("fields", {}).items():
                new_seg.setdefault("fields", {})[fnum] = fdef
            merged["segments"][seg_name] = new_seg
        else:
            # Brand-new segment in this delta.
            merged["segments"][seg_name] = copy.deepcopy(delta_seg)

    return merged


# ---------------------------------------------------------------------------
# SchemaRegistry
# ---------------------------------------------------------------------------

@dataclass
class FieldDef:
    name: str
    type: str
    required: bool = False
    max_length: int | None = None
    repeating: bool = False


@dataclass
class SegmentDef:
    name: str
    desc: str
    max_fields: int
    fields: dict[int, FieldDef]  # field number (1-based) → definition


@dataclass
class VersionSchema:
    version: str
    segments: dict[str, SegmentDef]  # segment name → definition


@dataclass
class MessageSegmentRule:
    name: str
    min: int
    max: int  # -1 = unbounded


@dataclass
class MessageTypeDef:
    key: str
    name: str
    versions: list[str]
    segments: list[MessageSegmentRule]


class SchemaRegistry:
    """Loads and caches version schemas with inheritance resolution."""

    def __init__(self) -> None:
        self._schemas: dict[str, VersionSchema] = {}
        self._message_types: dict[str, MessageTypeDef] = {}
        self._load_all()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_schema(self, version: str) -> VersionSchema | None:
        """Return the resolved schema for *version*, or None if unknown."""
        return self._schemas.get(version)

    def get_message_type(self, msg_type: str) -> MessageTypeDef | None:
        """Look up a message-type definition by key (e.g. 'ADT_A01')."""
        return self._message_types.get(msg_type)

    def nearest_version(self, version: str) -> str:
        """
        Return the nearest known version string for an unrecognised version.

        Strategy: parse the major/minor numbers and find the highest known
        version that is less-than-or-equal.  Falls back to '2.3' as a
        safe default.
        """
        def _ver_tuple(v: str) -> tuple[int, ...]:
            try:
                return tuple(int(p) for p in v.split("."))
            except ValueError:
                return (0,)

        target = _ver_tuple(version)
        best = "2.3"
        for known in _KNOWN_VERSIONS_ORDERED:
            if _ver_tuple(known) <= target:
                best = known
        return best

    def known_versions(self) -> list[str]:
        """Return all known version strings."""
        return list(self._schemas.keys())

    # ------------------------------------------------------------------
    # Private loading logic
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        """Load every version schema and the message-types file."""
        # Load raw JSON for each version (before inheritance resolution).
        raw: dict[str, dict[str, Any]] = {}
        for version, stem in _VERSION_FILE_MAP.items():
            raw[version] = _load_json(stem)

        # Resolve inheritance: topologically safe because we process in
        # order and parents always have smaller version numbers.
        for version in _KNOWN_VERSIONS_ORDERED:
            data = raw[version]
            parent_key: str | None = data.get("inherits")
            if parent_key and parent_key in self._schemas:
                # Reconstruct parent dict from already-resolved VersionSchema.
                parent_dict = self._schema_to_dict(self._schemas[parent_key])
                merged = _merge_schemas(parent_dict, data)
            else:
                merged = data

            self._schemas[version] = self._parse_schema(merged)

        # Load message type definitions.
        mt_raw: dict[str, Any] = _load_json("message_types")
        for key, defn in mt_raw.items():
            rules = [
                MessageSegmentRule(
                    name=r["name"],
                    min=r["min"],
                    max=r["max"],
                )
                for r in defn.get("segments", [])
            ]
            self._message_types[key] = MessageTypeDef(
                key=key,
                name=defn.get("name", key),
                versions=defn.get("versions", []),
                segments=rules,
            )

    @staticmethod
    def _parse_schema(data: dict[str, Any]) -> VersionSchema:
        segments: dict[str, SegmentDef] = {}
        for seg_name, seg_data in data.get("segments", {}).items():
            fields: dict[int, FieldDef] = {}
            for fnum_str, fdata in seg_data.get("fields", {}).items():
                fnum = int(fnum_str)
                fields[fnum] = FieldDef(
                    name=fdata.get("name", ""),
                    type=fdata.get("type", "ST"),
                    required=bool(fdata.get("required", False)),
                    max_length=fdata.get("max_length"),
                    repeating=bool(fdata.get("repeating", False)),
                )
            segments[seg_name] = SegmentDef(
                name=seg_name,
                desc=seg_data.get("desc", ""),
                max_fields=int(seg_data.get("max_fields", 99)),
                fields=fields,
            )
        return VersionSchema(version=data["version"], segments=segments)

    @staticmethod
    def _schema_to_dict(schema: VersionSchema) -> dict[str, Any]:
        """Convert a resolved VersionSchema back to a plain dict for merging."""
        segments: dict[str, Any] = {}
        for seg_name, seg in schema.segments.items():
            fields: dict[str, Any] = {}
            for fnum, fdef in seg.fields.items():
                fd: dict[str, Any] = {
                    "name": fdef.name,
                    "type": fdef.type,
                    "required": fdef.required,
                }
                if fdef.max_length is not None:
                    fd["max_length"] = fdef.max_length
                if fdef.repeating:
                    fd["repeating"] = True
                fields[str(fnum)] = fd
            segments[seg_name] = {
                "desc": seg.desc,
                "max_fields": seg.max_fields,
                "fields": fields,
            }
        return {"version": schema.version, "inherits": None, "segments": segments}


# Module-level singleton — loaded once at import time.
_registry = SchemaRegistry()


# ---------------------------------------------------------------------------
# Validation data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    severity: str          # "error" | "warning" | "info"
    code: str
    message: str
    segment: str | None = None
    field: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "segment": self.segment,
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    valid: bool
    version: str
    message_type: str | None
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "version": self.version,
            "message_type": self.message_type,
            "issues": [i.to_dict() for i in self.issues],
        }


# ---------------------------------------------------------------------------
# Version / message-type extraction helpers
# ---------------------------------------------------------------------------

_Z_SEGMENT_RE = re.compile(r"^Z[A-Z0-9]{1,2}$")


def _is_z_segment(name: str) -> bool:
    return bool(_Z_SEGMENT_RE.match(name))


def _get_msh_control_id(segments: list[dict[str, Any]]) -> str | None:
    """Extract MSH-10 (Message Control ID) from the first MSH segment."""
    for seg in segments:
        if seg.get("name") == "MSH":
            fields: list[Any] = seg.get("fields", [])
            # MSH-10 is at index 9 (0-based).
            if len(fields) >= 10:
                raw = fields[9]
                val = _extract_field_value(raw)
                return val.strip() if val else None
    return None


def _extract_field_value(field_value: Any) -> str:
    """
    Extract a simple string value from a parsed field.

    The Rust parser returns:
    - plain string for scalar fields
    - list for component fields: ["comp1", "comp2", ...]
    - list of lists for repeating component fields
    """
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, list):
        if not field_value:
            return ""
        first = field_value[0]
        if isinstance(first, list):
            # Repeating field: take first repetition, first component.
            return first[0] if first else ""
        return first if isinstance(first, str) else ""
    return ""


def _get_msh_version(segments: list[dict[str, Any]]) -> str | None:
    """Extract the version string from MSH-12 of the first MSH segment."""
    for seg in segments:
        if seg.get("name") == "MSH":
            fields: list[Any] = seg.get("fields", [])
            # MSH fields are 0-indexed in the parsed output, but MSH-1
            # (the field separator) is implicit in the segment structure.
            # The parsed fields list begins at MSH-1 (field sep).
            # MSH-12 is at index 11 (0-based).
            if len(fields) >= 12:
                raw = fields[11]
                val = _extract_field_value(raw)
                return val.strip() if val else None
    return None


def _get_msh_message_type(segments: list[dict[str, Any]]) -> str | None:
    """
    Extract the message type key from MSH-9.

    MSH-9 is a MSG composite: message_code ^ trigger_event ^ message_structure
    We return "MSG_CODE_TRIGGER" e.g. "ADT_A01".
    """
    for seg in segments:
        if seg.get("name") == "MSH":
            fields: list[Any] = seg.get("fields", [])
            # MSH-9 is at index 8 (0-based).
            if len(fields) >= 9:
                raw = fields[8]
                if isinstance(raw, list):
                    # Components: [message_code, trigger_event, ...]
                    parts = raw if not isinstance(raw[0], list) else raw[0]
                    code = _extract_field_value(parts[0]) if len(parts) > 0 else ""
                    trig = _extract_field_value(parts[1]) if len(parts) > 1 else ""
                    if code and trig:
                        return f"{code}_{trig}"
                    return code or None
                val = _extract_field_value(raw)
                # May be "ADT^A01" or "ADT_A01"
                if "^" in val:
                    parts_str = val.split("^")
                    code = parts_str[0].strip()
                    trig = parts_str[1].strip() if len(parts_str) > 1 else ""
                    return f"{code}_{trig}" if trig else code or None
                if "_" in val:
                    return val.strip() or None
                return val.strip() or None
    return None


def _is_field_empty(field_value: Any) -> bool:
    """Return True if a field value is considered empty/missing."""
    if field_value is None:
        return True
    if isinstance(field_value, str):
        return field_value.strip() == "" or field_value == '""'
    if isinstance(field_value, list):
        if not field_value:
            return True
        return all(_is_field_empty(v) for v in field_value)
    return False


# ---------------------------------------------------------------------------
# Core validation function
# ---------------------------------------------------------------------------

def validate(
    message: dict[str, Any],
    strict: bool = True,
    version: str | None = None,
) -> dict[str, Any]:
    """
    Validate a parsed HL7v2 message against its version schema.

    Parameters
    ----------
    message:
        A parsed message dict as returned by ``parse()`` or ``parse_file()``.
    strict:
        When True (default), any Error-severity issue makes ``valid=False``.
        When False (lenient), ``valid`` is always True and Error issues are
        downgraded to Warning.
    version:
        Override the version detected from MSH-12.  If None, version is
        auto-detected from the message.

    Returns
    -------
    dict with keys: valid, version, message_type, issues.
    """
    segments: list[dict[str, Any]] = message.get("segments", [])
    issues: list[ValidationIssue] = []

    # ------------------------------------------------------------------
    # 1. Determine version
    # ------------------------------------------------------------------
    detected_version = version or _get_msh_version(segments) or "2.3"
    effective_version = detected_version
    schema: VersionSchema | None = _registry.get_schema(detected_version)

    if schema is None:
        nearest = _registry.nearest_version(detected_version)
        schema = _registry.get_schema(nearest)
        if strict:
            issues.append(ValidationIssue(
                severity="error",
                code="UNKNOWN_VERSION",
                message=f"Version '{detected_version}' is not a recognised HL7v2 version; "
                        f"nearest known is '{nearest}'",
            ))
            effective_version = nearest
        else:
            issues.append(ValidationIssue(
                severity="warning",
                code="UNKNOWN_VERSION",
                message=f"Version '{detected_version}' is not a recognised HL7v2 version; "
                        f"falling back to nearest known '{nearest}'",
            ))
            effective_version = nearest

    # ------------------------------------------------------------------
    # 2. Determine message type
    # ------------------------------------------------------------------
    raw_msg_type = _get_msh_message_type(segments)
    msg_type_def = _registry.get_message_type(raw_msg_type) if raw_msg_type else None
    message_type_key: str | None = raw_msg_type

    if raw_msg_type and msg_type_def is None:
        known_types = sorted(_registry._message_types.keys())
        sample_types = ", ".join(known_types[:8])
        last_type = known_types[-1] if known_types else ""
        issues.append(ValidationIssue(
            severity="warning",
            code="UNKNOWN_MESSAGE_TYPE",
            message=(
                f"Message type '{raw_msg_type}' is not in the known message type registry. "
                f"Known types include: {sample_types}, ..., {last_type}. "
                f"Segment composition checks will be skipped; "
                f"only field-level validation will be performed."
            ),
        ))

    # ------------------------------------------------------------------
    # 3. Per-segment checks (field-level)
    # ------------------------------------------------------------------
    assert schema is not None  # guaranteed by fallback above

    for seg in segments:
        seg_name: str = seg.get("name", "")
        seg_fields: list[Any] = seg.get("fields", [])

        # Z-segment check — always Info, skip schema validation.
        if _is_z_segment(seg_name):
            issues.append(ValidationIssue(
                severity="info",
                code="CUSTOM_Z_SEGMENT",
                message=f"Custom Z-segment: {seg_name}",
                segment=seg_name,
            ))
            continue

        seg_def = schema.segments.get(seg_name)

        # Unknown segment (not Z-, not in schema).
        if seg_def is None:
            sev = "error" if strict else "warning"
            known_names = sorted(schema.segments.keys())
            sample = ", ".join(known_names[:8])
            issues.append(ValidationIssue(
                severity=sev,
                code="UNKNOWN_SEGMENT",
                message=(
                    f"Segment '{seg_name}' is not defined in HL7v{effective_version}. "
                    f"Known segments for this version include: {sample}, ... "
                    f"({len(known_names)} total)"
                ),
                segment=seg_name,
            ))
            continue

        # Excess fields check.
        actual_field_count = len(seg_fields)
        if actual_field_count > seg_def.max_fields:
            sev = "warning"
            issues.append(ValidationIssue(
                severity=sev,
                code="EXCESS_FIELDS",
                message=(
                    f"{seg_name} has {actual_field_count} fields but HL7v{effective_version} "
                    f"defines a maximum of {seg_def.max_fields} fields for this segment. "
                    f"Extra fields may indicate a version mismatch or custom extension."
                ),
                segment=seg_name,
            ))

        # Required field and max_length checks.
        for fnum, fdef in seg_def.fields.items():
            # Field index is 1-based; map to 0-based list index.
            idx = fnum - 1
            if idx >= len(seg_fields):
                field_value: Any = None
            else:
                field_value = seg_fields[idx]

            if fdef.required and _is_field_empty(field_value):
                sev = "error" if strict else "warning"
                issues.append(ValidationIssue(
                    severity=sev,
                    code="MISSING_REQUIRED_FIELD",
                    message=(
                        f"{seg_name}-{fnum} ({fdef.name}) is required in HL7v{effective_version} "
                        f"but is empty or missing. Field type: {fdef.type}"
                    ),
                    segment=seg_name,
                    field=fnum,
                ))

            if fdef.max_length is not None and field_value is not None:
                raw_str = _extract_field_value(field_value)
                if len(raw_str) > fdef.max_length:
                    preview = raw_str[:25] + "..." if len(raw_str) > 25 else raw_str
                    issues.append(ValidationIssue(
                        severity="warning",
                        code="FIELD_TOO_LONG",
                        message=(
                            f"{seg_name}-{fnum} ({fdef.name}) has length {len(raw_str)} "
                            f"but maximum allowed is {fdef.max_length} characters. "
                            f"Value: '{preview}' (truncated)"
                        ),
                        segment=seg_name,
                        field=fnum,
                    ))

    # ------------------------------------------------------------------
    # 4. Message composition checks (only if message type is known)
    # ------------------------------------------------------------------
    if msg_type_def is not None:
        _check_message_composition(
            segments=segments,
            msg_type_def=msg_type_def,
            strict=strict,
            issues=issues,
        )

    # ------------------------------------------------------------------
    # 5. Compute validity
    # ------------------------------------------------------------------
    if strict:
        has_error = any(i.severity == "error" for i in issues)
        valid = not has_error
    else:
        # Lenient: downgrade all errors to warnings.
        for issue in issues:
            if issue.severity == "error":
                issue.severity = "warning"
        valid = True

    return ValidationResult(
        valid=valid,
        version=effective_version,
        message_type=message_type_key,
        issues=issues,
    ).to_dict()


def _check_message_composition(
    segments: list[dict[str, Any]],
    msg_type_def: MessageTypeDef,
    strict: bool,
    issues: list[ValidationIssue],
) -> None:
    """Check segment composition rules against a message type definition."""
    # Count occurrences of each segment name.
    seg_counts: dict[str, int] = {}
    for seg in segments:
        name = seg.get("name", "")
        if not _is_z_segment(name):
            seg_counts[name] = seg_counts.get(name, 0) + 1

    # Build a deduplicated list of allowed segment names and their combined
    # min/max from the rules (a segment may appear multiple times in the
    # rule list, e.g. ROL appearing in different positions).
    allowed_mins: dict[str, int] = {}
    allowed_maxes: dict[str, int | None] = {}
    for rule in msg_type_def.segments:
        name = rule.name
        if name not in allowed_mins:
            # First time seeing this segment name.
            allowed_mins[name] = rule.min
            allowed_maxes[name] = rule.max
        else:
            # Segment appears in multiple positions in the message structure.
            # Take the highest minimum (required in any position = required).
            allowed_mins[name] = max(allowed_mins[name], rule.min)
            # max: -1 means unbounded; if any position is unbounded, result is unbounded;
            # otherwise sum the maxima across all positions.
            existing_max = allowed_maxes[name]
            if existing_max == -1 or rule.max == -1:
                allowed_maxes[name] = -1
            else:
                allowed_maxes[name] = (existing_max or 0) + rule.max

    allowed_names: set[str] = set(allowed_mins.keys())

    # Ordered, deduplicated expected segment names for display.
    seen: set[str] = set()
    expected_ordered: list[str] = []
    for rule in msg_type_def.segments:
        if rule.name not in seen:
            seen.add(rule.name)
            expected_ordered.append(rule.name)
    expected_display = ", ".join(expected_ordered)

    # Present segments (non-Z) for display in missing-required messages.
    present_names = ", ".join(sorted(seg_counts.keys())) if seg_counts else "(none)"

    # Check for missing required segments.
    for name, min_count in allowed_mins.items():
        if min_count >= 1 and seg_counts.get(name, 0) < min_count:
            sev = "error" if strict else "warning"
            issues.append(ValidationIssue(
                severity=sev,
                code="MISSING_REQUIRED_SEGMENT",
                message=(
                    f"Required segment {name} is missing from "
                    f"{msg_type_def.key} ({msg_type_def.name}) message. "
                    f"This segment must appear at least {min_count} time(s). "
                    f"Segments present: {present_names}"
                ),
                segment=name,
            ))

    # Check for segments that exceed max occurrence.
    for name, count in seg_counts.items():
        if name not in allowed_names:
            # Unexpected segment (present but not in message type definition).
            sev = "warning" if strict else "info"
            # Use "an" before vowel-starting type names for grammatical correctness.
            article = "an" if msg_type_def.key[0] in "AEIOU" else "a"
            issues.append(ValidationIssue(
                severity=sev,
                code="UNEXPECTED_SEGMENT",
                message=(
                    f"Segment {name} is not expected in {article} "
                    f"{msg_type_def.key} ({msg_type_def.name}) message. "
                    f"Expected segments: {expected_display}"
                ),
                segment=name,
            ))
        else:
            max_count = allowed_maxes.get(name)
            if max_count is not None and max_count != -1 and count > max_count:
                sev = "error" if strict else "warning"
                issues.append(ValidationIssue(
                    severity=sev,
                    code="SEGMENT_EXCEEDS_MAX",
                    message=(
                        f"Segment {name} appears {count} times in "
                        f"{msg_type_def.key} ({msg_type_def.name}) message "
                        f"but is limited to {max_count} occurrence(s)"
                    ),
                    segment=name,
                ))


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------

def validate_file(
    path: str,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """
    Parse and validate all messages in an HL7 file.

    Parameters
    ----------
    path:
        Path to the HL7 file.
    strict:
        Passed through to ``validate()`` for each message.

    Returns
    -------
    List of validation result dicts, one per message.  Each dict includes:

    - All keys from ``validate()``: ``valid``, ``version``, ``message_type``, ``issues``
    - ``message_index`` (int): 0-based position of the message in the file
    - ``message_control_id`` (str | None): value from MSH-10, if present
    """
    from rust_hl7_parser._native import parse_file as _parse_file  # type: ignore[import]

    messages: list[dict[str, Any]] = _parse_file(path, strict=False)
    results: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages):
        result = validate(msg, strict=strict)
        result["message_index"] = idx
        result["message_control_id"] = _get_msh_control_id(msg.get("segments", []))
        results.append(result)
    return results


def validate_file_summary(path: str, strict: bool = True) -> dict[str, Any]:
    """
    Return a high-level summary of validation results for an HL7 file.

    Parameters
    ----------
    path:
        Path to the HL7 file.
    strict:
        Passed through to ``validate_file()``.

    Returns
    -------
    dict with keys:

    - ``file`` (str): the path that was validated
    - ``total_messages`` (int): total number of messages parsed
    - ``valid_messages`` (int): count of messages where ``valid=True``
    - ``invalid_messages`` (int): count of messages where ``valid=False``
    - ``issue_counts`` (dict[str, int]): aggregated count per issue code
    - ``results`` (list[dict]): full per-message results from ``validate_file()``
    """
    results = validate_file(path, strict=strict)
    total = len(results)
    valid_count = sum(1 for r in results if r["valid"])
    error_count = total - valid_count

    issue_counts: dict[str, int] = {}
    for r in results:
        for issue in r["issues"]:
            code: str = issue["code"]
            issue_counts[code] = issue_counts.get(code, 0) + 1

    return {
        "file": path,
        "total_messages": total,
        "valid_messages": valid_count,
        "invalid_messages": error_count,
        "issue_counts": issue_counts,
        "results": results,
    }
