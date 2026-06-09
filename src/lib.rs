//! Fast HL7v2 message parser.
//!
//! ## Using as a Rust library
//!
//! Add to `Cargo.toml` with the `python` feature disabled so pyo3 is not
//! pulled in:
//!
//! ```toml
//! [dependencies]
//! rust-hl7-parser = { git = "https://github.com/mikenac/rust-hl7-parser", default-features = false }
//! ```
//!
//! ### Basic parse
//!
//! ```rust,no_run
//! use rust_hl7_parser::{parser, error::ParseMode};
//!
//! let raw = "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r\
//!            PID|1||12345^^^MRN||Doe^John^M";
//!
//! let (msg, _warnings) = parser::parse(raw, ParseMode::Strict).unwrap();
//!
//! // Navigate the fully-structured tree — no collapsing at the Rust level.
//! let pid5   = &msg.segments[1].fields[4];  // PID-5, zero-indexed
//! let family = pid5.repetitions[0].components[0].sub_components[0].as_ref();
//! assert_eq!(family, "Doe");
//! ```
//!
//! ### Lenient mode
//!
//! ```rust,no_run
//! use rust_hl7_parser::{parser, error::ParseMode};
//!
//! let raw = "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r\
//!            BA\r\
//!            PID|1";
//!
//! let (msg, warnings) = parser::parse(raw, ParseMode::Lenient).unwrap();
//! // MSH + PID parsed; BA skipped and reported.
//! assert_eq!(msg.segments.len(), 2);
//! assert!(!warnings.is_empty());
//! ```
//!
//! ### Repeating fields
//!
//! ```rust,no_run
//! use rust_hl7_parser::{parser, error::ParseMode};
//!
//! let raw = "MSH|^~\\&|App|Fac|App|Fac|20230101||ADT^A01|1|P|2.3\r\
//!            AL1|1|DA|PENICILLIN|MO|RASH~HIVES~NAUSEA";
//!
//! let (msg, _) = parser::parse(raw, ParseMode::Strict).unwrap();
//! let al1_5 = &msg.segments[1].fields[4];  // AL1-5, zero-indexed
//!
//! // Three repetitions — each a scalar sub-component.
//! assert_eq!(al1_5.repetitions.len(), 3);
//! assert_eq!(al1_5.repetitions[0].components[0].sub_components[0].as_ref(), "RASH");
//! assert_eq!(al1_5.repetitions[1].components[0].sub_components[0].as_ref(), "HIVES");
//! assert_eq!(al1_5.repetitions[2].components[0].sub_components[0].as_ref(), "NAUSEA");
//! ```
//!
//! ### File and batch parsing
//!
//! ```rust,no_run
//! use rust_hl7_parser::{parser, error::ParseMode};
//!
//! let content = std::fs::read_to_string("messages.hl7").unwrap();
//! let groups  = parser::group_message_lines(&content);
//! let results = parser::parse_message_groups(&groups, ParseMode::Lenient);
//!
//! for (i, result) in results.into_iter().enumerate() {
//!     let (msg, warnings) = result.unwrap();
//!     println!("Message {}: {} segments", i, msg.segments.len());
//! }
//! ```
//!
//! ## Python bindings
//!
//! Built automatically when the `python` feature is enabled (the default).
//! The feature pulls in `pyo3` and compiles `src/python_bindings.rs` as the
//! `_native` extension module. Use `maturin develop` or `maturin build` to
//! produce the Python wheel.

pub mod error;
pub mod parser;
pub mod types;

#[cfg(feature = "python")]
mod python_bindings;
