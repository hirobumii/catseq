//! Transport seam migrated from CatSeq commit `7c9f02d`.

use std::error::Error;
use std::fmt::{Display, Formatter};
use std::time::Instant;

#[cfg(test)]
use std::collections::VecDeque;

mod raw_socket;

pub(crate) use raw_socket::{RawEthernetTransport, RawSocketConfig};

#[cfg(any(target_os = "linux", test))]
pub(crate) const ETHER_TYPE: u16 = 0xface;
#[cfg(any(target_os = "linux", test))]
pub(crate) const OASM_PADDING_BYTES: usize = 32;

/// Ethernet facts resolved once when a transport opens.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct TransportEnvelope {
    pub ether_type: u16,
    pub source_mac: [u8; 6],
    pub destination_mac: [u8; 6],
    pub loopback_marker: [u8; 8],
}

/// One outer Ethernet packet observed by the runtime transport.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct WirePacket {
    pub ether_type: u16,
    pub source_mac: [u8; 6],
    pub destination_mac: [u8; 6],
    pub loopback_marker: [u8; 8],
    pub payload: Vec<u8>,
}

/// A failed send can prove rejection or leave acceptance unknown.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum SendRejection {
    NotAccepted,
    AcceptanceUnknown,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SendError {
    pub rejection: SendRejection,
    pub message: String,
}

#[cfg(any(target_os = "linux", test))]
impl SendError {
    pub(crate) fn not_accepted(message: impl Into<String>) -> Self {
        Self {
            rejection: SendRejection::NotAccepted,
            message: message.into(),
        }
    }

    pub(crate) fn acceptance_unknown(message: impl Into<String>) -> Self {
        Self {
            rejection: SendRejection::AcceptanceUnknown,
            message: message.into(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ReceiveError(pub String);

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct TransportError(pub String);

impl Display for SendError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Display for ReceiveError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Display for TransportError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for SendError {}
impl Error for ReceiveError {}
impl Error for TransportError {}

/// Minimal transport seam; semantic retry policy remains in the runtime.
pub(crate) trait Transport {
    fn open(&mut self) -> Result<TransportEnvelope, TransportError>;
    fn send(&mut self, packet: &WirePacket) -> Result<(), SendError>;
    fn receive(&mut self, deadline: Instant) -> Result<Option<WirePacket>, ReceiveError>;
    fn close(&mut self);
}

/// Deterministic transport used by state-machine and fault-injection tests.
#[cfg(test)]
#[derive(Clone, Debug)]
pub(crate) struct InMemoryTransport {
    pub envelope: TransportEnvelope,
    pub opened: usize,
    pub closed: usize,
    pub sent: Vec<WirePacket>,
    pub receive_queue: VecDeque<Result<Option<WirePacket>, ReceiveError>>,
    pub send_faults: VecDeque<Result<(), SendError>>,
    pub open_error: Option<TransportError>,
}

#[cfg(test)]
impl InMemoryTransport {
    pub(crate) fn new(envelope: TransportEnvelope) -> Self {
        Self {
            envelope,
            opened: 0,
            closed: 0,
            sent: Vec::new(),
            receive_queue: VecDeque::new(),
            send_faults: VecDeque::new(),
            open_error: None,
        }
    }

    pub(crate) fn with_received(
        envelope: TransportEnvelope,
        received: impl IntoIterator<Item = WirePacket>,
    ) -> Self {
        let mut transport = Self::new(envelope);
        transport.receive_queue = received
            .into_iter()
            .map(|packet| Ok(Some(packet)))
            .collect();
        transport
    }
}

#[cfg(test)]
impl Transport for InMemoryTransport {
    fn open(&mut self) -> Result<TransportEnvelope, TransportError> {
        self.opened += 1;
        self.open_error.clone().map_or(Ok(self.envelope), Err)
    }

    fn send(&mut self, packet: &WirePacket) -> Result<(), SendError> {
        if let Some(result) = self.send_faults.pop_front() {
            if result.is_ok() {
                self.sent.push(packet.clone());
            }
            return result;
        }
        self.sent.push(packet.clone());
        Ok(())
    }

    fn receive(&mut self, _deadline: Instant) -> Result<Option<WirePacket>, ReceiveError> {
        self.receive_queue.pop_front().unwrap_or(Ok(None))
    }

    fn close(&mut self) {
        self.closed += 1;
    }
}
