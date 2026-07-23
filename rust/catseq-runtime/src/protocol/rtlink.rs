//! RTLink framing migrated from CatSeq commit `7c9f02d`.

use std::error::Error;
use std::fmt::{Display, Formatter};

/// Frozen RTMQ-v2 RTLink payload size: six header bytes and two words.
pub const FRAME_BYTES: usize = 14;
const CHANNEL_BITS: u32 = 5;
const TAG_BITS: u32 = 20;
const CHANNEL_MAX: u8 = (1 << CHANNEL_BITS) - 1;
const TAG_MAX: u32 = (1 << TAG_BITS) - 1;

/// One canonical RTLink frame, without the outer Ethernet envelope.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RtlinkFrame {
    flag: u8,
    channel: u8,
    node: u16,
    tag: u32,
    payload: [u32; 2],
}

impl RtlinkFrame {
    pub fn new(
        flag: u8,
        channel: u8,
        node: u16,
        tag: u32,
        payload: [u32; 2],
    ) -> Result<Self, RtlinkFrameError> {
        if flag > 7 {
            return Err(RtlinkFrameError::new("flag exceeds three bits"));
        }
        if channel > CHANNEL_MAX {
            return Err(RtlinkFrameError::new("channel exceeds five bits"));
        }
        if tag > TAG_MAX {
            return Err(RtlinkFrameError::new("tag exceeds twenty bits"));
        }
        Ok(Self {
            flag,
            channel,
            node,
            tag,
            payload,
        })
    }

    pub const fn flag(self) -> u8 {
        self.flag
    }

    pub const fn channel(self) -> u8 {
        self.channel
    }

    pub const fn node(self) -> u16 {
        self.node
    }

    pub const fn tag(self) -> u32 {
        self.tag
    }

    pub const fn payload(self) -> [u32; 2] {
        self.payload
    }

    pub fn encode(self) -> [u8; FRAME_BYTES] {
        // OASM bit_concat((flag,3), (channel,5), (node,16), (tag,20))
        // is a 44-bit header serialized into six bytes, leaving four leading
        // padding bits at zero.
        let header = (u64::from(self.flag) << 41)
            | (u64::from(self.channel) << 36)
            | (u64::from(self.node) << 20)
            | u64::from(self.tag);
        let mut bytes = [0_u8; FRAME_BYTES];
        let encoded_header = header.to_be_bytes();
        bytes[..6].copy_from_slice(&encoded_header[2..]);
        bytes[6..10].copy_from_slice(&self.payload[0].to_be_bytes());
        bytes[10..14].copy_from_slice(&self.payload[1].to_be_bytes());
        bytes
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, RtlinkFrameError> {
        if bytes.len() != FRAME_BYTES {
            return Err(RtlinkFrameError::new(format!(
                "RTLink frame has {} bytes, expected {FRAME_BYTES}",
                bytes.len()
            )));
        }
        if bytes[0] & 0xf0 != 0 {
            return Err(RtlinkFrameError::new(
                "RTLink header has nonzero padding bits",
            ));
        }
        let mut header_bytes = [0_u8; 8];
        header_bytes[2..].copy_from_slice(&bytes[..6]);
        let header = u64::from_be_bytes(header_bytes);
        let flag = ((header >> 41) & 0x7) as u8;
        let channel = ((header >> 36) & 0x1f) as u8;
        let node = ((header >> 20) & 0xffff) as u16;
        let tag = (header & u64::from(TAG_MAX)) as u32;
        let payload = [
            u32::from_be_bytes(bytes[6..10].try_into().expect("fixed slice")),
            u32::from_be_bytes(bytes[10..14].try_into().expect("fixed slice")),
        ];
        Self::new(flag, channel, node, tag, payload)
    }
}

/// Encode one Direct loader exactly as OASM `base_intf.write`: odd streams are
/// zero-padded and each pair gets an identical header.
pub fn encode_word_stream(
    flag: u8,
    channel: u8,
    node: u16,
    tag: u32,
    words: &[u32],
) -> Result<Vec<RtlinkFrame>, RtlinkFrameError> {
    let mut frames = Vec::with_capacity(words.len().div_ceil(2));
    for pair in words.chunks(2) {
        frames.push(RtlinkFrame::new(
            flag,
            channel,
            node,
            tag,
            [pair[0], pair.get(1).copied().unwrap_or(0)],
        )?);
    }
    Ok(frames)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RtlinkFrameError {
    message: String,
}

impl RtlinkFrameError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for RtlinkFrameError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for RtlinkFrameError {}
