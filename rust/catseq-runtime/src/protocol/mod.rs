//! Pinned RTMQ-v2 wire protocol primitives.

mod rtlink;

pub use rtlink::{FRAME_BYTES, RtlinkFrame, RtlinkFrameError, encode_word_stream};
