//! Fast HL7v2 parser using str::split instead of Winnow combinators.
//!
//! Parsing is bottom-up:
//!   sub_component → component → repetition → field → segment → message
//!
//! The MSH segment is handled specially: MSH-1 is the field separator itself
//! and MSH-2 is the four encoding characters (`^~\&` by default).

use std::borrow::Cow;

use crate::{
    error::{LenientResult, ParseError, ParseMode},
    types::{Hl7Component, Hl7Field, Hl7Message, Hl7Repetition, Hl7Segment},
};

// ---------------------------------------------------------------------------
// Delimiter configuration
// ---------------------------------------------------------------------------

/// The set of delimiters active for a particular message.
/// Defaults match the HL7 standard (`|`, `^`, `~`, `\`, `&`).
#[derive(Debug, Clone, Copy)]
pub struct Delimiters {
    pub field: char,
    pub component: char,
    pub repetition: char,
    pub escape: char,
    pub sub_component: char,
}

impl Default for Delimiters {
    fn default() -> Self {
        Self {
            field: '|',
            component: '^',
            repetition: '~',
            escape: '\\',
            sub_component: '&',
        }
    }
}

impl Delimiters {
    /// Parse delimiter configuration from the MSH-2 encoding-characters field.
    /// The standard value is `^~\&` (4 bytes).
    pub fn from_encoding_chars(s: &str) -> Result<Self, ParseError> {
        let chars: Vec<char> = s.chars().collect();
        if chars.len() < 4 {
            return Err(ParseError::new(format!(
                "MSH-2 encoding characters must be exactly 4 characters, got: {:?}",
                s
            )));
        }
        Ok(Self {
            field: '|', // always '|' from MSH-1
            component: chars[0],
            repetition: chars[1],
            escape: chars[2],
            sub_component: chars[3],
        })
    }
}

// ---------------------------------------------------------------------------
// Escape-sequence processing
// ---------------------------------------------------------------------------

/// Expand HL7 escape sequences in a raw string value.
/// Sequences: `\F\` → field sep, `\S\` → component sep, `\R\` → repetition sep,
/// `\E\` → escape char, `\T\` → sub-component sep.
///
/// Returns `Cow::Borrowed(raw)` on the hot path (no escape char present),
/// avoiding any heap allocation.
fn unescape<'a>(raw: &'a str, d: &Delimiters) -> Cow<'a, str> {
    let esc = d.escape;
    if !raw.contains(esc) {
        return Cow::Borrowed(raw);
    }

    let mut out = String::with_capacity(raw.len());
    let mut chars = raw.chars().peekable();

    while let Some(ch) = chars.next() {
        if ch != esc {
            out.push(ch);
            continue;
        }
        // Collect until next escape char or end-of-string
        let mut seq = String::new();
        let mut closed = false;
        for inner in chars.by_ref() {
            if inner == esc {
                closed = true;
                break;
            }
            seq.push(inner);
        }
        if closed {
            match seq.as_str() {
                "F" => out.push(d.field),
                "S" => out.push(d.component),
                "R" => out.push(d.repetition),
                "E" => out.push(d.escape),
                "T" => out.push(d.sub_component),
                other => {
                    // Unknown / unsupported escape: preserve literally
                    out.push(esc);
                    out.push_str(other);
                    out.push(esc);
                }
            }
        } else {
            // Unclosed escape: preserve literal backslash + rest
            out.push(esc);
            out.push_str(&seq);
        }
    }

    Cow::Owned(out)
}

// ---------------------------------------------------------------------------
// Fast field parser
// ---------------------------------------------------------------------------

/// Fast field parser using str::split instead of Winnow combinators.
/// Since field content never contains the field separator (|), and component/
/// repetition/sub-component separators are single chars, simple split chains
/// are correct and much faster than combinator-based parsing.
fn parse_field_fast<'a>(raw: &'a str, d: &Delimiters) -> Hl7Field<'a> {
    let repetitions: Vec<Hl7Repetition<'a>> = raw
        .split(d.repetition)
        .map(|rep_str| {
            let components: Vec<Hl7Component<'a>> = rep_str
                .split(d.component)
                .map(|comp_str| {
                    let sub_components: Vec<Cow<'a, str>> = comp_str
                        .split(d.sub_component)
                        .map(|s| unescape(s, d))
                        .collect();
                    Hl7Component { sub_components }
                })
                .collect();
            Hl7Repetition { components }
        })
        .collect();
    Hl7Field { repetitions }
}

// ---------------------------------------------------------------------------
// Segment-line parsers
// ---------------------------------------------------------------------------

/// Split a segment line (already stripped of its trailing line terminator) into
/// its segment name and the remainder after the first `|`.
fn split_segment_name(line: &str) -> Option<(&str, &str)> {
    // Segment name is the first 3 characters, then `|`.
    if line.len() < 3 {
        return None;
    }
    let (name, rest) = line.split_at(3);
    if !name.chars().all(|c| c.is_ascii_alphabetic() || c.is_ascii_digit()) {
        return None;
    }
    // rest may start with | (normal segments) or be empty
    if rest.is_empty() {
        return Some((name, ""));
    }
    if rest.starts_with('|') {
        Some((name, &rest[1..]))
    } else {
        None
    }
}

/// Parse the special MSH segment line.
///
/// MSH is handled separately because:
/// - MSH-1 is the field separator character itself (first char after "MSH")
/// - MSH-2 is the encoding characters string (next 4 chars)
/// - These two fields are read literally, without applying field/component splitting
/// - All subsequent fields use the delimiters from MSH-2
fn parse_msh_segment<'a>(
    line: &'a str,
    mode: ParseMode,
) -> Result<(Hl7Segment<'a>, Delimiters), ParseError> {
    // line must start with "MSH"
    if !line.starts_with("MSH") {
        return Err(ParseError::new("First segment is not MSH"));
    }
    let after_msh = &line[3..];
    if after_msh.is_empty() {
        return Err(ParseError::new("MSH segment is too short (no field separator)"));
    }

    // MSH-1: the field separator character
    let field_sep = after_msh.chars().next().unwrap();
    let after_field_sep = &after_msh[field_sep.len_utf8()..];

    // MSH-2: the encoding characters (next chars up to the next field separator)
    let enc_end = after_field_sep
        .find(field_sep)
        .unwrap_or(after_field_sep.len());
    let enc_chars_str = &after_field_sep[..enc_end];

    let delimiters = match Delimiters::from_encoding_chars(enc_chars_str) {
        Ok(d) => {
            if d.field != field_sep {
                // Rebuild with correct field separator (should always be '|')
                Delimiters {
                    field: field_sep,
                    ..d
                }
            } else {
                d
            }
        }
        Err(e) => {
            if mode == ParseMode::Strict {
                return Err(e);
            }
            // Lenient: fall back to defaults
            let mut d = Delimiters::default();
            d.field = field_sep;
            d
        }
    };

    // Now parse the rest of the MSH fields (after MSH-2)
    let after_enc = if enc_end < after_field_sep.len() {
        &after_field_sep[enc_end + field_sep.len_utf8()..]
    } else {
        ""
    };

    // Build the fields list:
    // fields[0] = MSH-1 (field separator char as a borrowed slice from the input)
    // fields[1] = MSH-2 (encoding characters as a borrowed slice from the input)
    // fields[2..] = parsed normally
    let mut fields: Vec<Hl7Field<'a>> = Vec::new();

    // MSH-1: borrow the single-char field separator directly from the input line.
    // line[3..4] is always the field separator byte (ASCII, so 1 byte).
    let field_sep_slice: &'a str = &line[3..4];
    fields.push(Hl7Field::scalar(Cow::Borrowed(field_sep_slice)));

    // MSH-2 — stored as a raw scalar (borrowed slice of encoding chars from the input)
    fields.push(Hl7Field::scalar(Cow::Borrowed(enc_chars_str)));

    // Remaining fields
    for raw_field in after_enc.split(field_sep) {
        fields.push(parse_field_fast(raw_field, &delimiters));
    }

    let segment = Hl7Segment {
        name: Cow::Borrowed("MSH"),
        fields,
    };
    Ok((segment, delimiters))
}

/// Parse a non-MSH segment line using the given delimiters.
fn parse_generic_segment<'a>(
    line: &'a str,
    d: &Delimiters,
    mode: ParseMode,
    warnings: &mut Vec<String>,
) -> Option<Hl7Segment<'a>> {
    let (name, fields_str) = match split_segment_name(line) {
        Some(pair) => pair,
        None => {
            let msg = format!("Skipping malformed segment (cannot extract name): {:?}", line);
            warnings.push(msg);
            return None;
        }
    };

    // Validate segment name: must be 3 ASCII alpha characters (digits allowed by spec in extensions)
    if name.len() != 3 {
        let msg = format!("Skipping segment with non-3-char name: {:?}", name);
        warnings.push(msg);
        return None;
    }

    // In strict mode, flag unreachable names that still somehow passed split_segment_name
    let _ = mode; // mode is available if needed for future strict checks

    let mut fields: Vec<Hl7Field<'a>> = Vec::new();
    for raw_field in fields_str.split(d.field) {
        fields.push(parse_field_fast(raw_field, d));
    }

    Some(Hl7Segment {
        name: Cow::Borrowed(name),
        fields,
    })
}

// ---------------------------------------------------------------------------
// Top-level entry points
// ---------------------------------------------------------------------------

/// Split the raw message text into individual segment lines.
/// Accepts `\r`, `\n`, and `\r\n` as segment terminators.
/// MLLP framing bytes (\x0B, \x1C) are stripped from each line.
fn split_lines(input: &str) -> Vec<&str> {
    // Replace \r\n with \n, then split on both \r and \n
    // We must not allocate if we can avoid it; do a manual split.
    let mut lines: Vec<&str> = Vec::new();
    let mut start = 0;
    let bytes = input.as_bytes();
    let len = bytes.len();
    let mut i = 0;

    while i < len {
        if bytes[i] == b'\r' {
            lines.push(&input[start..i]);
            // consume optional \n after \r
            if i + 1 < len && bytes[i + 1] == b'\n' {
                i += 1;
            }
            start = i + 1;
        } else if bytes[i] == b'\n' {
            lines.push(&input[start..i]);
            start = i + 1;
        }
        i += 1;
    }
    // Last line (if no trailing newline)
    if start < len {
        lines.push(&input[start..]);
    }

    // Strip MLLP framing bytes and filter empty lines
    lines
        .into_iter()
        .map(|l| l.trim_matches(|c: char| c == '\x0B' || c == '\x1C'))
        .filter(|l| !l.is_empty())
        .collect()
}

/// Parse an HL7v2 message string in strict mode.
/// Returns `Err(ParseError)` on any malformed content.
pub fn parse_strict<'a>(input: &'a str) -> Result<Hl7Message<'a>, ParseError> {
    let lines = split_lines(input);
    if lines.is_empty() {
        return Err(ParseError::new("Empty message"));
    }

    let (msh_segment, delimiters) = parse_msh_segment(lines[0], ParseMode::Strict)?;

    let mut segments = vec![msh_segment];
    let mut dummy_warnings: Vec<String> = Vec::new();

    for line in &lines[1..] {
        match parse_generic_segment(line, &delimiters, ParseMode::Strict, &mut dummy_warnings) {
            Some(seg) => segments.push(seg),
            None => {
                // In strict mode a None means there was a parse issue.
                let warn = dummy_warnings
                    .pop()
                    .unwrap_or_else(|| format!("Failed to parse segment: {:?}", line));
                return Err(ParseError::new(warn));
            }
        }
    }

    Ok(Hl7Message { segments })
}

/// Parse an HL7v2 message string in lenient mode.
/// Malformed segments are skipped and reported as warnings.
pub fn parse_lenient<'a>(input: &'a str) -> LenientResult<Hl7Message<'a>> {
    let lines = split_lines(input);
    if lines.is_empty() {
        return LenientResult::with_warnings(
            Hl7Message { segments: vec![] },
            vec!["Empty message".to_owned()],
        );
    }

    let mut warnings: Vec<String> = Vec::new();

    let (msh_segment, delimiters) = match parse_msh_segment(lines[0], ParseMode::Lenient) {
        Ok(pair) => pair,
        Err(e) => {
            warnings.push(e.message.clone());
            // Cannot continue without MSH / delimiters — return empty message
            return LenientResult::with_warnings(Hl7Message { segments: vec![] }, warnings);
        }
    };

    let mut segments = vec![msh_segment];

    for line in &lines[1..] {
        match parse_generic_segment(line, &delimiters, ParseMode::Lenient, &mut warnings) {
            Some(seg) => segments.push(seg),
            None => {
                // warning already pushed by parse_generic_segment
            }
        }
    }

    LenientResult::with_warnings(Hl7Message { segments }, warnings)
}

// ---------------------------------------------------------------------------
// Convenience wrapper
// ---------------------------------------------------------------------------

/// Parse using either strict or lenient mode.
/// Returns `(Hl7Message, Vec<String> warnings)`.
/// In strict mode the warnings vec is always empty; errors are propagated.
pub fn parse<'a>(
    input: &'a str,
    mode: ParseMode,
) -> Result<(Hl7Message<'a>, Vec<String>), ParseError> {
    match mode {
        ParseMode::Strict => {
            let msg = parse_strict(input)?;
            Ok((msg, vec![]))
        }
        ParseMode::Lenient => {
            let result = parse_lenient(input);
            Ok((result.value, result.warnings))
        }
    }
}

// ---------------------------------------------------------------------------
// File / batch parsing
// ---------------------------------------------------------------------------

/// Split file content into groups of borrowed segment-line slices.
///
/// This is the zero-copy variant of `group_messages`: instead of allocating a
/// joined `String` per message it returns `Vec<Vec<&str>>` — each inner `Vec`
/// holds the raw segment lines for one message, still pointing into `content`.
/// MLLP framing bytes (\x0B, \x1C) are stripped and blank lines treated as
/// message boundaries exactly as in `group_messages`.
///
/// Accepts `\r`, `\n`, and `\r\n` as line terminators so that CR-only files
/// (the native HL7v2 format) are handled correctly as well as LF and CRLF.
pub fn group_message_lines<'a>(content: &'a str) -> Vec<Vec<&'a str>> {
    let mut messages: Vec<Vec<&'a str>> = Vec::new();
    let mut current: Vec<&'a str> = Vec::new();

    // Iterate over raw lines split on \r, \n, or \r\n — same byte-scan
    // approach used by split_lines() so that all three line-ending styles
    // are handled uniformly without any heap allocation.
    let bytes = content.as_bytes();
    let len = bytes.len();
    let mut start = 0;
    let mut i = 0;

    // Closure-like helper: process one candidate line slice.
    // We use a local macro because Rust closures cannot borrow `messages` and
    // `current` mutably at the same time they capture `content`.
    macro_rules! handle_line {
        ($slice:expr) => {{
            let stripped: &'a str = $slice
                .trim_matches(|c: char| c == '\x0B' || c == '\x1C');

            if stripped.is_empty() {
                if !current.is_empty() {
                    messages.push(std::mem::take(&mut current));
                }
            } else {
                if stripped.starts_with("MSH") && !current.is_empty() {
                    messages.push(std::mem::take(&mut current));
                }
                current.push(stripped);
            }
        }};
    }

    while i < len {
        if bytes[i] == b'\r' {
            handle_line!(&content[start..i]);
            // Consume optional \n after \r (CRLF)
            if i + 1 < len && bytes[i + 1] == b'\n' {
                i += 1;
            }
            start = i + 1;
        } else if bytes[i] == b'\n' {
            handle_line!(&content[start..i]);
            start = i + 1;
        }
        i += 1;
    }
    // Final line (no trailing newline)
    if start < len {
        handle_line!(&content[start..]);
    }

    if !current.is_empty() {
        messages.push(current);
    }

    messages
}

/// Parse a message that has already been split into segment lines.
///
/// This avoids the `split_lines` step (and the join allocation done by
/// `group_messages`) when the caller already holds `&[&str]` segments from
/// `group_message_lines`.
pub fn parse_from_lines<'a>(
    lines: &[&'a str],
    mode: ParseMode,
) -> Result<(Hl7Message<'a>, Vec<String>), ParseError> {
    if lines.is_empty() {
        return Err(ParseError::new("Empty message"));
    }

    match mode {
        ParseMode::Strict => {
            let (msh_segment, delimiters) = parse_msh_segment(lines[0], ParseMode::Strict)?;
            let mut segments = vec![msh_segment];
            let mut dummy_warnings: Vec<String> = Vec::new();
            for line in &lines[1..] {
                match parse_generic_segment(line, &delimiters, ParseMode::Strict, &mut dummy_warnings) {
                    Some(seg) => segments.push(seg),
                    None => {
                        let warn = dummy_warnings
                            .pop()
                            .unwrap_or_else(|| format!("Failed to parse segment: {:?}", line));
                        return Err(ParseError::new(warn));
                    }
                }
            }
            Ok((Hl7Message { segments }, vec![]))
        }
        ParseMode::Lenient => {
            let mut warnings: Vec<String> = Vec::new();
            let (msh_segment, delimiters) = match parse_msh_segment(lines[0], ParseMode::Lenient) {
                Ok(pair) => pair,
                Err(e) => {
                    warnings.push(e.message.clone());
                    return Ok((Hl7Message { segments: vec![] }, warnings));
                }
            };
            let mut segments = vec![msh_segment];
            for line in &lines[1..] {
                if let Some(seg) =
                    parse_generic_segment(line, &delimiters, ParseMode::Lenient, &mut warnings)
                {
                    segments.push(seg);
                }
            }
            Ok((Hl7Message { segments }, warnings))
        }
    }
}

/// Parse a pre-grouped set of line-groups produced by `group_message_lines`.
///
/// This is the zero-copy batch entry point: no additional allocations beyond
/// the parsed message structures themselves.
pub fn parse_message_groups<'a>(
    groups: &[Vec<&'a str>],
    mode: ParseMode,
) -> Vec<Result<(Hl7Message<'a>, Vec<String>), ParseError>> {
    groups.iter().map(|lines| parse_from_lines(lines, mode)).collect()
}

/// Split file content into individual HL7 messages.
///
/// Handles the common file format where segments are one-per-line (\n separated)
/// and messages are separated by blank lines or MSH restarts.
/// MLLP framing bytes (\x0B, \x1C) are stripped.
///
/// Kept for backward compatibility. Prefer `group_message_lines` for
/// zero-copy batch parsing.
#[allow(dead_code)]
pub fn group_messages(content: &str) -> Vec<String> {
    group_message_lines(content)
        .into_iter()
        .map(|lines| lines.join("\r"))
        .collect()
}

/// Parse a pre-grouped list of HL7 message strings.
/// Each element must be a complete HL7 message (segments separated by `\r`).
/// Returns a Vec of results — one per message.
///
/// The caller is responsible for keeping the strings alive for the duration
/// of this call (and any further use of the returned messages).
#[allow(dead_code)]
pub fn parse_messages<'a>(
    messages: &'a [String],
    mode: ParseMode,
) -> Vec<Result<(Hl7Message<'a>, Vec<String>), ParseError>> {
    messages.iter().map(|msg| parse(msg.as_str(), mode)).collect()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    const SIMPLE_ADT: &str =
        "MSH|^~\\&|SendingApp|SendingFac|ReceivingApp|ReceivingFac|20230101120000||ADT^A01|MSG00001|P|2.3\rPID|1||12345^^^MRN||Doe^John^M||19800101|M";

    #[test]
    fn test_split_lines_cr() {
        let lines = split_lines("A\rB\rC");
        assert_eq!(lines, vec!["A", "B", "C"]);
    }

    #[test]
    fn test_split_lines_lf() {
        let lines = split_lines("A\nB\nC");
        assert_eq!(lines, vec!["A", "B", "C"]);
    }

    #[test]
    fn test_split_lines_crlf() {
        let lines = split_lines("A\r\nB\r\nC");
        assert_eq!(lines, vec!["A", "B", "C"]);
    }

    #[test]
    fn test_split_lines_strips_mllp() {
        let lines = split_lines("\x0BMSH|data\x1C\r");
        assert_eq!(lines, vec!["MSH|data"]);
    }

    #[test]
    fn test_split_lines_mllp_only_line_discarded() {
        let lines = split_lines("MSH|data\r\x1C\rPID|1");
        assert_eq!(lines, vec!["MSH|data", "PID|1"]);
    }

    #[test]
    fn test_parse_simple_adt() {
        let msg = parse_strict(SIMPLE_ADT).unwrap();
        assert_eq!(msg.segments.len(), 2);
        assert_eq!(msg.segments[0].name, "MSH");
        assert_eq!(msg.segments[1].name, "PID");
    }

    #[test]
    fn test_msh_fields() {
        let msg = parse_strict(SIMPLE_ADT).unwrap();
        let msh = &msg.segments[0];
        // MSH-1 (index 0): field separator
        assert_eq!(msh.fields[0].repetitions[0].components[0].sub_components[0], "|");
        // MSH-2 (index 1): encoding chars
        assert_eq!(msh.fields[1].repetitions[0].components[0].sub_components[0], "^~\\&");
        // MSH-3 (index 2): SendingApp
        assert_eq!(msh.fields[2].repetitions[0].components[0].sub_components[0], "SendingApp");
    }

    #[test]
    fn test_component_parsing() {
        let msg = parse_strict(SIMPLE_ADT).unwrap();
        let pid = &msg.segments[1];
        // PID-5 (index 4): "Doe^John^M"
        let name_field = &pid.fields[4];
        let rep = &name_field.repetitions[0];
        assert_eq!(rep.components.len(), 3);
        assert_eq!(rep.components[0].sub_components[0], "Doe");
        assert_eq!(rep.components[1].sub_components[0], "John");
        assert_eq!(rep.components[2].sub_components[0], "M");
    }

    #[test]
    fn test_repetition_parsing() {
        let msg = parse_strict("MSH|^~\\&|A\rTST|val1~val2").unwrap();
        let tst = &msg.segments[1];
        assert_eq!(tst.fields[0].repetitions.len(), 2);
        assert_eq!(
            tst.fields[0].repetitions[0].components[0].sub_components[0],
            "val1"
        );
        assert_eq!(
            tst.fields[0].repetitions[1].components[0].sub_components[0],
            "val2"
        );
    }

    #[test]
    fn test_sub_component_parsing() {
        let msg = parse_strict("MSH|^~\\&|A\rTST|a&b").unwrap();
        let tst = &msg.segments[1];
        let comp = &tst.fields[0].repetitions[0].components[0];
        assert_eq!(comp.sub_components.len(), 2);
        assert_eq!(comp.sub_components[0], "a");
        assert_eq!(comp.sub_components[1], "b");
    }

    #[test]
    fn test_empty_fields() {
        let msg = parse_strict("MSH|^~\\&|A\rTST||foo||bar").unwrap();
        let tst = &msg.segments[1];
        assert_eq!(tst.fields[0].repetitions[0].components[0].sub_components[0], "");
        assert_eq!(tst.fields[1].repetitions[0].components[0].sub_components[0], "foo");
        assert_eq!(tst.fields[2].repetitions[0].components[0].sub_components[0], "");
        assert_eq!(tst.fields[3].repetitions[0].components[0].sub_components[0], "bar");
    }

    #[test]
    fn test_escape_sequences() {
        let d = Delimiters::default();
        assert_eq!(unescape("hello\\F\\world", &d), "hello|world");
        assert_eq!(unescape("a\\S\\b", &d), "a^b");
        assert_eq!(unescape("a\\E\\b", &d), "a\\b");
        assert_eq!(unescape("a\\T\\b", &d), "a&b");
        assert_eq!(unescape("a\\R\\b", &d), "a~b");
    }

    #[test]
    fn test_no_escape_returns_borrowed() {
        let d = Delimiters::default();
        let raw = "hello world";
        let result = unescape(raw, &d);
        assert!(matches!(result, Cow::Borrowed(_)));
    }

    #[test]
    fn test_escape_returns_owned() {
        let d = Delimiters::default();
        let raw = "hello\\F\\world";
        let result = unescape(raw, &d);
        assert!(matches!(result, Cow::Owned(_)));
    }

    #[test]
    fn test_strict_rejects_bad_msh() {
        let result = parse_strict("NOT|^~\\&|A");
        assert!(result.is_err());
    }

    #[test]
    fn test_lenient_skips_bad_segment() {
        let result = parse_lenient("MSH|^~\\&|A\r12|bad\rPID|1");
        assert!(!result.warnings.is_empty());
        // PID should still be present
        assert!(result.value.segments.iter().any(|s| s.name == "PID"));
    }

    #[test]
    fn test_group_messages_blank_separator() {
        let content = "MSH|^~\\&|A\nPID|1\n\nMSH|^~\\&|B\nPID|2\n";
        let msgs = group_messages(content);
        assert_eq!(msgs.len(), 2);
        assert!(msgs[0].starts_with("MSH"));
        assert!(msgs[1].starts_with("MSH"));
    }

    #[test]
    fn test_group_messages_msh_restart() {
        // No blank line between messages, MSH detection
        let content = "MSH|^~\\&|A\nPID|1\nMSH|^~\\&|B\nPID|2\n";
        let msgs = group_messages(content);
        assert_eq!(msgs.len(), 2);
    }

    #[test]
    fn test_group_messages_mllp_separator() {
        let content = "MSH|^~\\&|A\nPID|1\n\x1C\nMSH|^~\\&|B\nPID|2\n";
        let msgs = group_messages(content);
        assert_eq!(msgs.len(), 2);
    }

    #[test]
    fn test_parse_messages_basic() {
        let content = "MSH|^~\\&|A\nPID|1\n\nMSH|^~\\&|B\nOBX|1\n";
        let grouped = group_messages(content);
        let results = parse_messages(&grouped, ParseMode::Strict);
        assert_eq!(results.len(), 2);
        assert!(results[0].is_ok());
        assert!(results[1].is_ok());
    }
}
