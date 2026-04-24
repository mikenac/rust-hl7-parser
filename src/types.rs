use std::borrow::Cow;

use serde::Serialize;

/// A fully parsed HL7v2 message.
#[derive(Debug, Clone, Serialize)]
pub struct Hl7Message<'a> {
    pub segments: Vec<Hl7Segment<'a>>,
}

/// A single HL7 segment (e.g. MSH, PID, OBX).
#[derive(Debug, Clone, Serialize)]
pub struct Hl7Segment<'a> {
    /// Three-character segment identifier (e.g. "MSH").
    pub name: Cow<'a, str>,
    /// Zero-indexed list of fields. For MSH, index 0 = MSH-1 ("|"),
    /// index 1 = MSH-2 ("^~\&"), index 2 = MSH-3 (SendingApp), etc.
    pub fields: Vec<Hl7Field<'a>>,
}

/// One field in a segment. A field may repeat (separated by `~`).
#[derive(Debug, Clone, Serialize)]
pub struct Hl7Field<'a> {
    pub repetitions: Vec<Hl7Repetition<'a>>,
}

/// One repetition of a field. Contains components separated by `^`.
#[derive(Debug, Clone, Serialize)]
pub struct Hl7Repetition<'a> {
    pub components: Vec<Hl7Component<'a>>,
}

/// One component within a repetition. Contains sub-components separated by `&`.
#[derive(Debug, Clone, Serialize)]
pub struct Hl7Component<'a> {
    pub sub_components: Vec<Cow<'a, str>>,
}

impl<'a> Hl7Component<'a> {
    /// Convenience: single sub-component value.
    pub fn scalar(value: impl Into<Cow<'a, str>>) -> Self {
        Self {
            sub_components: vec![value.into()],
        }
    }
}

impl<'a> Hl7Repetition<'a> {
    /// Convenience: single component with a single sub-component.
    pub fn scalar(value: impl Into<Cow<'a, str>>) -> Self {
        Self {
            components: vec![Hl7Component::scalar(value)],
        }
    }
}

impl<'a> Hl7Field<'a> {
    /// Convenience: single repetition / single component / single sub-component.
    pub fn scalar(value: impl Into<Cow<'a, str>>) -> Self {
        Self {
            repetitions: vec![Hl7Repetition::scalar(value)],
        }
    }
}
