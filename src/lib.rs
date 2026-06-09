//! PyO3 entry point for the `rust_hl7_parser._native` extension module.

mod error;
mod parser;
mod types;

use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString};
use types::{Hl7Component, Hl7Field, Hl7Message, Hl7Repetition, Hl7Segment};

// ---------------------------------------------------------------------------
// Structure-collapsing helpers
// ---------------------------------------------------------------------------
//
// The public API collapses trivial wrappers so that simple scalar fields
// surface as plain Python strings instead of nested dicts.
//
// Rules (applied innermost-first):
//   - A component with exactly 1 sub-component   -> the string itself
//   - A repetition with exactly 1 component      -> that component (or string)
//   - A field with exactly 1 repetition          -> that repetition
//
// When structure cannot be collapsed (multiple items), we return lists /
// dicts that exactly mirror the Rust types.

fn component_to_py<'py>(py: Python<'py>, comp: &Hl7Component<'_>) -> PyResult<Bound<'py, PyAny>> {
    if comp.sub_components.len() == 1 {
        Ok(PyString::new(py, comp.sub_components[0].as_ref()).into_any())
    } else {
        // PyList::new accepts ExactSizeIterator<Item: IntoPyObject> directly —
        // slice::Iter + map produces an ExactSizeIterator, avoiding an intermediate Vec.
        let list = PyList::new(
            py,
            comp.sub_components
                .iter()
                .map(|s| PyString::new(py, s.as_ref())),
        )?;
        Ok(list.into_any())
    }
}

fn repetition_to_py<'py>(
    py: Python<'py>,
    rep: &Hl7Repetition<'_>,
) -> PyResult<Bound<'py, PyAny>> {
    if rep.components.len() == 1 {
        component_to_py(py, &rep.components[0])
    } else {
        let list = PyList::empty(py);
        for c in &rep.components {
            list.append(component_to_py(py, c)?)?;
        }
        Ok(list.into_any())
    }
}

fn field_to_py<'py>(py: Python<'py>, field: &Hl7Field<'_>) -> PyResult<Bound<'py, PyAny>> {
    if field.repetitions.len() == 1 {
        repetition_to_py(py, &field.repetitions[0])
    } else {
        let list = PyList::empty(py);
        for r in &field.repetitions {
            list.append(repetition_to_py(py, r)?)?;
        }
        Ok(list.into_any())
    }
}

fn segment_to_py<'py>(py: Python<'py>, seg: &Hl7Segment<'_>) -> PyResult<Bound<'py, PyAny>> {
    let d = PyDict::new(py);
    // intern! caches the Python string object so it is created once and reused
    // across calls instead of being allocated fresh on every segment conversion.
    d.set_item(intern!(py, "name"), seg.name.as_ref())?;
    let fields = PyList::empty(py);
    for f in &seg.fields {
        fields.append(field_to_py(py, f)?)?;
    }
    d.set_item(intern!(py, "fields"), fields)?;
    Ok(d.into_any())
}

fn message_to_py<'py>(
    py: Python<'py>,
    msg: &Hl7Message<'_>,
    warnings: &[String],
) -> PyResult<Py<PyAny>> {
    let d = PyDict::new(py);
    let segs = PyList::empty(py);
    for s in &msg.segments {
        segs.append(segment_to_py(py, s)?)?;
    }
    d.set_item(intern!(py, "segments"), segs)?;
    if !warnings.is_empty() {
        let wlist = PyList::new(py, warnings.iter().map(|s| s.as_str()))?;
        d.set_item(intern!(py, "warnings"), wlist)?;
    }
    Ok(d.into_any().unbind())
}

// ---------------------------------------------------------------------------
// Direct JSON serialization (no serde_json::Value intermediates)
// ---------------------------------------------------------------------------
//
// We write JSON directly into a `Vec<u8>` buffer using serde_json::to_writer
// for individual string values (which handles all JSON escaping correctly) and
// manual ASCII bytes for structural tokens. This eliminates the allocation of
// a serde_json::Value tree entirely.

/// Write a JSON-escaped string (with surrounding quotes) to `buf`.
#[inline]
fn write_json_str(buf: &mut Vec<u8>, s: &str) {
    // Fast path: if no bytes need JSON escaping, write directly.
    // Characters requiring JSON escape: 0x00-0x1F (control), '"', '\\'
    let needs_escape = s.as_bytes().iter().any(|&b| b < 0x20 || b == b'"' || b == b'\\');
    if !needs_escape {
        buf.push(b'"');
        buf.extend_from_slice(s.as_bytes());
        buf.push(b'"');
    } else {
        // Fall back to serde_json for correct escaping
        serde_json::to_writer(buf as &mut dyn std::io::Write, s).unwrap_or(());
    }
}

fn write_json_component(buf: &mut Vec<u8>, comp: &Hl7Component<'_>) {
    if comp.sub_components.len() == 1 {
        write_json_str(buf, comp.sub_components[0].as_ref());
    } else {
        buf.push(b'[');
        let mut first = true;
        for s in &comp.sub_components {
            if !first {
                buf.push(b',');
            }
            first = false;
            write_json_str(buf, s.as_ref());
        }
        buf.push(b']');
    }
}

fn write_json_repetition(buf: &mut Vec<u8>, rep: &Hl7Repetition<'_>) {
    if rep.components.len() == 1 {
        write_json_component(buf, &rep.components[0]);
    } else {
        buf.push(b'[');
        let mut first = true;
        for c in &rep.components {
            if !first {
                buf.push(b',');
            }
            first = false;
            write_json_component(buf, c);
        }
        buf.push(b']');
    }
}

fn write_json_field(buf: &mut Vec<u8>, field: &Hl7Field<'_>) {
    if field.repetitions.len() == 1 {
        write_json_repetition(buf, &field.repetitions[0]);
    } else {
        buf.push(b'[');
        let mut first = true;
        for r in &field.repetitions {
            if !first {
                buf.push(b',');
            }
            first = false;
            write_json_repetition(buf, r);
        }
        buf.push(b']');
    }
}

fn write_json_segment(buf: &mut Vec<u8>, seg: &Hl7Segment<'_>) {
    buf.extend_from_slice(b"{\"name\":");
    write_json_str(buf, seg.name.as_ref());
    buf.extend_from_slice(b",\"fields\":[");
    let mut first = true;
    for f in &seg.fields {
        if !first {
            buf.push(b',');
        }
        first = false;
        write_json_field(buf, f);
    }
    buf.extend_from_slice(b"]}");
}

fn write_json_message(buf: &mut Vec<u8>, msg: &Hl7Message<'_>, warnings: &[String]) {
    buf.extend_from_slice(b"{\"segments\":[");
    let mut first = true;
    for seg in &msg.segments {
        if !first {
            buf.push(b',');
        }
        first = false;
        write_json_segment(buf, seg);
    }
    buf.push(b']');
    if !warnings.is_empty() {
        buf.extend_from_slice(b",\"warnings\":[");
        let mut wfirst = true;
        for w in warnings {
            if !wfirst {
                buf.push(b',');
            }
            wfirst = false;
            write_json_str(buf, w.as_str());
        }
        buf.push(b']');
    }
    buf.push(b'}');
}

/// Serialize a single message to a JSON `String` using the direct-write path.
fn message_to_json_string(msg: &Hl7Message<'_>, warnings: &[String]) -> String {
    let mut buf: Vec<u8> = Vec::with_capacity(512);
    write_json_message(&mut buf, msg, warnings);
    // SAFETY: write_json_str uses serde_json for all string content, so buf is valid UTF-8.
    unsafe { String::from_utf8_unchecked(buf) }
}

// ---------------------------------------------------------------------------
// PyO3-exported functions
// ---------------------------------------------------------------------------

/// Parse an HL7v2 message and return a nested Python dict.
///
/// Parameters
/// ----------
/// message : str
///     The raw HL7v2 message text.
/// strict : bool, optional
///     When True (default) raise ValueError on any parse error.
///     When False, skip malformed segments and include a "warnings" key.
///
/// Returns
/// -------
/// dict
///     Parsed message structure with collapsing applied to simple fields.
///
/// Raises
/// ------
/// ValueError
///     If parsing fails in strict mode.
#[pyfunction]
#[pyo3(signature = (message, strict = true))]
fn parse(py: Python<'_>, message: &str, strict: bool) -> PyResult<Py<PyAny>> {
    let mode = if strict {
        error::ParseMode::Strict
    } else {
        error::ParseMode::Lenient
    };

    match parser::parse(message, mode) {
        Ok((msg, warnings)) => message_to_py(py, &msg, &warnings),
        Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.message)),
    }
}

/// Parse an HL7v2 message and return a JSON string.
///
/// Parameters
/// ----------
/// message : str
///     The raw HL7v2 message text.
/// strict : bool, optional
///     When True (default) raise ValueError on any parse error.
///     When False, skip malformed segments and include a "warnings" key.
///
/// Returns
/// -------
/// str
///     JSON-serialised parse result using the same collapsing logic as parse().
///
/// Raises
/// ------
/// ValueError
///     If parsing fails in strict mode.
#[pyfunction]
#[pyo3(signature = (message, strict = true))]
fn parse_json(message: &str, strict: bool) -> PyResult<String> {
    let mode = if strict {
        error::ParseMode::Strict
    } else {
        error::ParseMode::Lenient
    };

    match parser::parse(message, mode) {
        Ok((msg, warnings)) => Ok(message_to_json_string(&msg, &warnings)),
        Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.message)),
    }
}

/// Wrapper used by parse_lossless_json to include optional warnings alongside
/// the serde-serialised message tree without a heap allocation or string manipulation.
#[derive(serde::Serialize)]
struct LosslessOutput<'a> {
    #[serde(flatten)]
    msg: &'a types::Hl7Message<'a>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    warnings: Vec<String>,
}

/// Parse an HL7v2 message and return a fully lossless JSON string.
///
/// Unlike parse_json(), which collapses single-item wrappers (e.g. a field
/// with one repetition is returned as that repetition, not as a list), this
/// function serialises the complete internal Rust representation without any
/// collapsing. Every field is always ``{"repetitions": [...]}``; every
/// repetition is always ``{"components": [...]}``;  every component is always
/// ``{"sub_components": [...]}``.
///
/// Use this when you need to:
/// - Round-trip an HL7 message (parse → edit → re-serialise to HL7 text)
/// - Build an HL7 diff or merge tool
/// - Distinguish ``A^B`` (components) from ``A~B`` (repetitions) from
///   ``A&B`` (sub-components) — all three collapse to ``["A","B"]`` in
///   parse_json() but are distinct in this output.
///
/// When strict=False, a ``"warnings"`` key is included in the output when any
/// segments were skipped, consistent with parse_json() behaviour.
///
/// Parameters
/// ----------
/// message : str
///     The raw HL7v2 message text.
/// strict : bool, optional
///     When True (default) raise ValueError on any parse error.
///     When False, skip malformed segments.
///
/// Returns
/// -------
/// str
///     Lossless JSON string. Significantly more verbose than parse_json().
///
/// Raises
/// ------
/// ValueError
///     If parsing fails in strict mode.
#[pyfunction]
#[pyo3(signature = (message, strict = true))]
fn parse_lossless_json(message: &str, strict: bool) -> PyResult<String> {
    let mode = if strict {
        error::ParseMode::Strict
    } else {
        error::ParseMode::Lenient
    };
    match parser::parse(message, mode) {
        Ok((msg, warnings)) => serde_json::to_string(&LosslessOutput { msg: &msg, warnings })
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string())),
        Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e.message)),
    }
}

/// Parse an HL7v2 file containing one or more messages.
///
/// The file may contain messages in any common format:
/// - One segment per line, messages separated by blank lines
/// - Single-line messages with \r between segments
/// - MLLP framing bytes (\x0B, \x1C) are stripped automatically
///
/// Returns a list of parsed message dicts.
#[pyfunction]
#[pyo3(signature = (path, strict = true))]
fn parse_file(py: Python<'_>, path: &str, strict: bool) -> PyResult<Vec<Py<PyAny>>> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| pyo3::exceptions::PyOSError::new_err(format!("{}: {}", path, e)))?;

    let mode = if strict {
        error::ParseMode::Strict
    } else {
        error::ParseMode::Lenient
    };

    // Zero-copy: group into borrowed line slices, parse without joining
    let groups = parser::group_message_lines(&content);
    let results = parser::parse_message_groups(&groups, mode);

    let mut parsed: Vec<Py<PyAny>> = Vec::with_capacity(results.len());
    let mut errors: Vec<(usize, String)> = Vec::new();

    for (i, result) in results.into_iter().enumerate() {
        match result {
            Ok((msg, warnings)) => {
                parsed.push(message_to_py(py, &msg, &warnings)?);
            }
            Err(e) => {
                if strict {
                    errors.push((i, e.message));
                }
                // In lenient mode this shouldn't happen, but skip if it does
            }
        }
    }

    if !errors.is_empty() {
        let err_lines: Vec<String> = errors
            .iter()
            .map(|(i, msg)| format!("  [{}]: {}", i, msg))
            .collect();
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "parse_file failed on {} message(s):\n{}",
            errors.len(),
            err_lines.join("\n")
        )));
    }

    Ok(parsed)
}

/// Parse an HL7v2 file and return a JSON array string.
///
/// Same as parse_file but returns serialized JSON, avoiding Python dict
/// construction overhead. Useful for piping to other systems.
#[pyfunction]
#[pyo3(signature = (path, strict = true))]
fn parse_file_json(path: &str, strict: bool) -> PyResult<String> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| pyo3::exceptions::PyOSError::new_err(format!("{}: {}", path, e)))?;

    let mode = if strict {
        error::ParseMode::Strict
    } else {
        error::ParseMode::Lenient
    };

    // Zero-copy grouping + direct JSON write (no serde_json::Value tree)
    let groups = parser::group_message_lines(&content);
    let results = parser::parse_message_groups(&groups, mode);

    let mut buf: Vec<u8> = Vec::with_capacity(groups.len() * 512);
    buf.push(b'[');
    let mut errors: Vec<(usize, String)> = Vec::new();
    let mut first = true;

    for (i, result) in results.into_iter().enumerate() {
        match result {
            Ok((msg, warnings)) => {
                if !first {
                    buf.push(b',');
                }
                first = false;
                write_json_message(&mut buf, &msg, &warnings);
            }
            Err(e) => {
                if strict {
                    errors.push((i, e.message));
                }
            }
        }
    }

    buf.push(b']');

    if !errors.is_empty() {
        let err_lines: Vec<String> = errors
            .iter()
            .map(|(i, msg)| format!("  [{}]: {}", i, msg))
            .collect();
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "parse_file_json failed on {} message(s):\n{}",
            errors.len(),
            err_lines.join("\n")
        )));
    }

    // SAFETY: buf only contains output from write_json_str (serde_json-escaped)
    // and ASCII structural bytes.
    Ok(unsafe { String::from_utf8_unchecked(buf) })
}

/// Parse a list of HL7v2 message strings.
///
/// Each element should be a complete HL7 message (segments separated by \r).
/// Returns a list of parsed message dicts, one per input message.
#[pyfunction]
#[pyo3(signature = (messages, strict = true))]
fn parse_batch(
    py: Python<'_>,
    messages: &Bound<'_, PyList>,
    strict: bool,
) -> PyResult<Vec<Py<PyAny>>> {
    let mode = if strict {
        error::ParseMode::Strict
    } else {
        error::ParseMode::Lenient
    };

    let mut parsed: Vec<Py<PyAny>> = Vec::with_capacity(messages.len());
    let mut errors: Vec<(usize, String)> = Vec::new();

    for (i, item) in messages.iter().enumerate() {
        let pystr = item.cast::<PyString>()?;
        // to_str() borrows directly from the Python string's UTF-8 buffer —
        // zero copy for the common case of compact (non-legacy) Python str objects.
        let msg: &str = pystr.to_str()?;
        match parser::parse(msg, mode) {
            Ok((parsed_msg, warnings)) => {
                parsed.push(message_to_py(py, &parsed_msg, &warnings)?);
            }
            Err(e) => {
                if strict {
                    errors.push((i, e.message));
                }
            }
        }
    }

    if !errors.is_empty() {
        let err_lines: Vec<String> = errors
            .iter()
            .map(|(i, msg)| format!("  [{}]: {}", i, msg))
            .collect();
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "parse_batch failed on {} message(s):\n{}",
            errors.len(),
            err_lines.join("\n")
        )));
    }

    Ok(parsed)
}

// ---------------------------------------------------------------------------
// Module definition
// ---------------------------------------------------------------------------

#[pymodule(gil_used = false)]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse, m)?)?;
    m.add_function(wrap_pyfunction!(parse_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_lossless_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_file, m)?)?;
    m.add_function(wrap_pyfunction!(parse_file_json, m)?)?;
    m.add_function(wrap_pyfunction!(parse_batch, m)?)?;
    Ok(())
}
