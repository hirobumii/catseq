//! Pinned RTMQ-v2 wire protocol primitives.

mod rtlink;

pub(crate) use rtlink::{RtlinkFrame, encode_word_stream};
