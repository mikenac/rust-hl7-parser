//! Fast HL7v2 message parser.
//!
//! ## Using as a Rust library
//!
//! Add to `Cargo.toml` with the `python` feature disabled:
//!
//! ```toml
//! rust-hl7-parser = { git = "https://github.com/mikenac/rust-hl7-parser", default-features = false }
//! ```
//!
//! Then parse directly:
//!
//! ```rust,ignore
//! use rust_hl7_parser::{parser, error::ParseMode};
//!
//! let (msg, warnings) = parser::parse("MSH|^~\\&|...", ParseMode::Lenient).unwrap();
//! println!("{}", msg.segments[0].name);
//! ```
//!
//! ## Python bindings
//!
//! Built automatically when the `python` feature is enabled (the default).
//! The feature pulls in `pyo3` and compiles the `_native` extension module.
//! Use `maturin develop` or `maturin build` to produce the Python wheel.

pub mod error;
pub mod parser;
pub mod types;

#[cfg(feature = "python")]
mod python_bindings;
