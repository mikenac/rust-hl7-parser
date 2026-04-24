use std::fmt;

/// Controls how strictly the parser enforces HL7 rules.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParseMode {
    /// Any malformed content produces an error immediately.
    Strict,
    /// Malformed segments are skipped; warnings are accumulated.
    Lenient,
}

/// Error returned by the parser in strict mode (or for fatal lenient failures).
#[derive(Debug, Clone)]
pub struct ParseError {
    pub message: String,
}

impl ParseError {
    pub fn new(msg: impl Into<String>) -> Self {
        Self {
            message: msg.into(),
        }
    }
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "HL7 parse error: {}", self.message)
    }
}

impl std::error::Error for ParseError {}

/// Result of a lenient parse: best-effort message plus any warnings collected.
#[derive(Debug, Clone)]
pub struct LenientResult<T> {
    pub value: T,
    pub warnings: Vec<String>,
}

impl<T> LenientResult<T> {
    pub fn with_warnings(value: T, warnings: Vec<String>) -> Self {
        Self { value, warnings }
    }
}
