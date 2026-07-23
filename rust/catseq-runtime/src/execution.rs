//! Physical execution state machine adapted from CatSeq commit `7c9f02d`.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::time::{Duration, Instant};

use catseq_rtmq::download::{DownloadLoaderConfig, materialize_download_loader};

use crate::model::{
    AssembledOasmProgram, LinuxRawEthernetRuntimeConfig, OasmAddress, validate_runtime_handoff,
};
use crate::protocol::{RtlinkFrame, encode_word_stream};
use crate::transport::{
    RawEthernetTransport, RawSocketConfig, SendRejection, Transport, TransportEnvelope, WirePacket,
};

const DOWNLOAD_FLAG: u8 = 4;
const DOWNLOAD_TAG: u32 = 0;
const OPERATION_TAG: u32 = 0xffff;
const MAX_NOT_ACCEPTED_RETRIES: usize = 100;

/// Per-board monotonic physical-execution evidence.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum BoardExecutionState {
    NotDispatched,
    LoaderSubmitted,
    LaunchSubmitted,
    Succeeded,
    DeviceFailed,
}

impl BoardExecutionState {
    const fn is_terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::DeviceFailed)
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::NotDispatched => "not_dispatched",
            Self::LoaderSubmitted => "loader_submitted",
            Self::LaunchSubmitted => "launch_submitted",
            Self::Succeeded => "succeeded",
            Self::DeviceFailed => "device_failed",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionCertainty {
    NotStarted,
    FullyObserved,
    Indeterminate,
}

impl ExecutionCertainty {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::NotStarted => "not_started",
            Self::FullyObserved => "fully_observed",
            Self::Indeterminate => "indeterminate",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeFailureCode {
    ProgramInvalid,
    TopologyInvalid,
    TransportOpenFailed,
    TransportSendFailed,
    TransportReceiveFailed,
    CompletionTimeout,
    DeviceException,
    ProtocolViolation,
}

impl RuntimeFailureCode {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ProgramInvalid => "program_invalid",
            Self::TopologyInvalid => "topology_invalid",
            Self::TransportOpenFailed => "transport_open_failed",
            Self::TransportSendFailed => "transport_send_failed",
            Self::TransportReceiveFailed => "transport_receive_failed",
            Self::CompletionTimeout => "completion_timeout",
            Self::DeviceException => "device_exception",
            Self::ProtocolViolation => "protocol_violation",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DeviceExceptionReport {
    exception_flags: u32,
    instruction_address: Option<u32>,
}

impl DeviceExceptionReport {
    pub const fn exception_flags(&self) -> u32 {
        self.exception_flags
    }

    pub const fn instruction_address(&self) -> Option<u32> {
        self.instruction_address
    }
}

/// Stable semantic runtime failure. Diagnostic text is not used for control flow.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeFailure {
    schema_version: u32,
    code: RuntimeFailureCode,
    message: String,
    execution_certainty: ExecutionCertainty,
    board_evidence: BTreeMap<OasmAddress, BoardExecutionState>,
    device_exceptions: BTreeMap<OasmAddress, DeviceExceptionReport>,
    details: BTreeMap<String, String>,
}

impl RuntimeFailure {
    fn new(
        code: RuntimeFailureCode,
        message: impl Into<String>,
        board_evidence: BTreeMap<OasmAddress, BoardExecutionState>,
        device_exceptions: BTreeMap<OasmAddress, DeviceExceptionReport>,
    ) -> Self {
        let execution_certainty = derive_certainty(&board_evidence);
        Self {
            schema_version: 1,
            code,
            message: message.into(),
            execution_certainty,
            board_evidence,
            device_exceptions,
            details: BTreeMap::new(),
        }
    }

    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version != 1 {
            return Err("runtime failure schema_version must be 1");
        }
        if derive_certainty(&self.board_evidence) != self.execution_certainty {
            return Err("execution_certainty contradicts board_evidence");
        }
        if self
            .device_exceptions
            .keys()
            .any(|board| self.board_evidence.get(board) != Some(&BoardExecutionState::DeviceFailed))
        {
            return Err("device exception does not correspond to device_failed evidence");
        }
        Ok(())
    }

    pub const fn schema_version(&self) -> u32 {
        self.schema_version
    }

    pub const fn code(&self) -> RuntimeFailureCode {
        self.code
    }

    pub fn message(&self) -> &str {
        &self.message
    }

    pub const fn execution_certainty(&self) -> ExecutionCertainty {
        self.execution_certainty
    }

    pub fn board_evidence(&self) -> &BTreeMap<OasmAddress, BoardExecutionState> {
        &self.board_evidence
    }

    pub fn device_exceptions(&self) -> &BTreeMap<OasmAddress, DeviceExceptionReport> {
        &self.device_exceptions
    }

    pub fn details(&self) -> &BTreeMap<String, String> {
        &self.details
    }
}

impl Display for RuntimeFailure {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.code.as_str(), self.message)
    }
}

impl Error for RuntimeFailure {}

/// A successful run proves every board reached a trusted success terminal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeSuccess {
    schema_version: u32,
    board_evidence: BTreeMap<OasmAddress, BoardExecutionState>,
    results: BTreeMap<OasmAddress, Vec<u32>>,
}

impl RuntimeSuccess {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.schema_version != 1 {
            return Err("runtime success schema_version must be 1");
        }
        if self.board_evidence.is_empty()
            || self
                .board_evidence
                .values()
                .any(|state| *state != BoardExecutionState::Succeeded)
        {
            return Err("runtime success requires succeeded evidence for every board");
        }
        Ok(())
    }

    pub const fn schema_version(&self) -> u32 {
        self.schema_version
    }

    pub fn board_evidence(&self) -> &BTreeMap<OasmAddress, BoardExecutionState> {
        &self.board_evidence
    }

    pub fn results(&self) -> &BTreeMap<OasmAddress, Vec<u32>> {
        &self.results
    }
}

struct PreparedBoard {
    address: OasmAddress,
    frames: Vec<PreparedFrame>,
}

struct PreparedFrame {
    frame: RtlinkFrame,
    launch_bearing: bool,
}

/// Validate, bind, dispatch, and monitor one immutable assembled OASM program.
pub fn execute_oasm_program(
    program: &AssembledOasmProgram,
    config: &LinuxRawEthernetRuntimeConfig,
) -> Result<RuntimeSuccess, RuntimeFailure> {
    let mut transport = RawEthernetTransport::new(RawSocketConfig {
        interface: config.interface().to_owned(),
        destination_mac: config.destination_mac(),
    });
    execute_with_transport(program, config, &mut transport, MAX_NOT_ACCEPTED_RETRIES)
}

fn execute_with_transport<T: Transport>(
    program: &AssembledOasmProgram,
    config: &LinuxRawEthernetRuntimeConfig,
    transport: &mut T,
    max_not_accepted_retries: usize,
) -> Result<RuntimeSuccess, RuntimeFailure> {
    let mut evidence = program
        .boards()
        .iter()
        .map(|board| (board.address(), BoardExecutionState::NotDispatched))
        .collect::<BTreeMap<_, _>>();
    let mut exceptions = BTreeMap::new();
    let prepared = prepare(program, config, &evidence, &exceptions)?;
    let deadline = Instant::now()
        .checked_add(Duration::from_millis(config.timeout_ms()))
        .ok_or_else(|| {
            RuntimeFailure::new(
                RuntimeFailureCode::TopologyInvalid,
                "runtime timeout cannot be represented by the monotonic clock",
                evidence.clone(),
                exceptions.clone(),
            )
        })?;

    let envelope = transport.open().map_err(|error| {
        RuntimeFailure::new(
            RuntimeFailureCode::TransportOpenFailed,
            error.to_string(),
            evidence.clone(),
            exceptions.clone(),
        )
    })?;

    let outcome = dispatch(
        &prepared,
        envelope,
        max_not_accepted_retries,
        transport,
        &mut evidence,
        &exceptions,
    )
    .and_then(|()| {
        monitor(
            program,
            config,
            deadline,
            envelope,
            transport,
            &mut evidence,
            &mut exceptions,
        )
    });
    transport.close();
    outcome
}

fn prepare(
    program: &AssembledOasmProgram,
    config: &LinuxRawEthernetRuntimeConfig,
    evidence: &BTreeMap<OasmAddress, BoardExecutionState>,
    exceptions: &BTreeMap<OasmAddress, DeviceExceptionReport>,
) -> Result<Vec<PreparedBoard>, RuntimeFailure> {
    validate_runtime_handoff(program, config).map_err(|error| {
        RuntimeFailure::new(
            RuntimeFailureCode::TopologyInvalid,
            error.to_string(),
            evidence.clone(),
            exceptions.clone(),
        )
    })?;

    program
        .boards()
        .iter()
        .map(|board| {
            let endpoint = config
                .boards()
                .iter()
                .copied()
                .find(|endpoint| endpoint.address() == board.address())
                .expect("validated topology contains every board");
            let loader = materialize_download_loader(
                board.ich_words(),
                DownloadLoaderConfig {
                    instruction_capacity_words: endpoint.instruction_capacity_words(),
                    exception_handler_word: board.exception_handler_word(),
                },
            )
            .map_err(|error| {
                RuntimeFailure::new(
                    RuntimeFailureCode::TopologyInvalid,
                    error.to_string(),
                    evidence.clone(),
                    exceptions.clone(),
                )
            })?;
            let frames = encode_word_stream(
                DOWNLOAD_FLAG,
                endpoint.channel(),
                endpoint.node(),
                DOWNLOAD_TAG,
                loader.words(),
            )
            .map_err(|error| {
                RuntimeFailure::new(
                    RuntimeFailureCode::ProgramInvalid,
                    error.to_string(),
                    evidence.clone(),
                    exceptions.clone(),
                )
            })?
            .into_iter()
            .enumerate()
            .map(|(frame_index, frame)| PreparedFrame {
                frame,
                launch_bearing: frame_index * 2 + 2 > loader.launch_range().start,
            })
            .collect();
            Ok(PreparedBoard {
                address: board.address(),
                frames,
            })
        })
        .collect()
}

fn dispatch<T: Transport>(
    prepared: &[PreparedBoard],
    envelope: TransportEnvelope,
    max_not_accepted_retries: usize,
    transport: &mut T,
    evidence: &mut BTreeMap<OasmAddress, BoardExecutionState>,
    exceptions: &BTreeMap<OasmAddress, DeviceExceptionReport>,
) -> Result<(), RuntimeFailure> {
    for board in prepared {
        for prepared_frame in &board.frames {
            let packet = outbound_packet(envelope, prepared_frame.frame);
            let mut rejected = 0;
            loop {
                match transport.send(&packet) {
                    Ok(()) => {
                        advance_submitted(evidence, board.address, prepared_frame.launch_bearing);
                        break;
                    }
                    Err(error) if error.rejection == SendRejection::NotAccepted => {
                        if rejected < max_not_accepted_retries {
                            rejected += 1;
                            continue;
                        }
                        return Err(RuntimeFailure::new(
                            RuntimeFailureCode::TransportSendFailed,
                            error.to_string(),
                            evidence.clone(),
                            exceptions.clone(),
                        ));
                    }
                    Err(error) => {
                        // Acceptance is unknown, so evidence advances
                        // conservatively and this exact frame is never retried.
                        advance_submitted(evidence, board.address, prepared_frame.launch_bearing);
                        return Err(RuntimeFailure::new(
                            RuntimeFailureCode::TransportSendFailed,
                            error.to_string(),
                            evidence.clone(),
                            exceptions.clone(),
                        ));
                    }
                }
            }
        }
    }
    Ok(())
}

fn advance_submitted(
    evidence: &mut BTreeMap<OasmAddress, BoardExecutionState>,
    board: OasmAddress,
    launch_bearing: bool,
) {
    let next = if launch_bearing {
        BoardExecutionState::LaunchSubmitted
    } else {
        BoardExecutionState::LoaderSubmitted
    };
    let state = evidence.get_mut(&board).expect("program board is present");
    if *state < next {
        *state = next;
    }
}

fn outbound_packet(envelope: TransportEnvelope, frame: RtlinkFrame) -> WirePacket {
    WirePacket {
        ether_type: envelope.ether_type,
        source_mac: envelope.source_mac,
        destination_mac: envelope.destination_mac,
        loopback_marker: envelope.loopback_marker,
        payload: frame.encode().to_vec(),
    }
}

fn monitor<T: Transport>(
    program: &AssembledOasmProgram,
    config: &LinuxRawEthernetRuntimeConfig,
    deadline: Instant,
    envelope: TransportEnvelope,
    transport: &mut T,
    evidence: &mut BTreeMap<OasmAddress, BoardExecutionState>,
    exceptions: &mut BTreeMap<OasmAddress, DeviceExceptionReport>,
) -> Result<RuntimeSuccess, RuntimeFailure> {
    let mut exception_addresses = BTreeMap::<OasmAddress, u32>::new();
    let mut results = BTreeMap::<OasmAddress, Vec<u32>>::new();
    loop {
        if evidence.values().all(|state| state.is_terminal()) {
            if exceptions.is_empty() {
                let success = RuntimeSuccess {
                    schema_version: 1,
                    board_evidence: evidence.clone(),
                    results,
                };
                debug_assert!(success.validate().is_ok());
                return Ok(success);
            }
            let failure = RuntimeFailure::new(
                RuntimeFailureCode::DeviceException,
                "one or more RTMQ boards reported a device exception",
                evidence.clone(),
                exceptions.clone(),
            );
            debug_assert!(failure.validate().is_ok());
            return Err(failure);
        }
        let packet = match transport.receive(deadline) {
            Ok(Some(packet)) => packet,
            Ok(None) => {
                return Err(RuntimeFailure::new(
                    RuntimeFailureCode::CompletionTimeout,
                    "not every launched RTMQ board reached a terminal state before the deadline",
                    evidence.clone(),
                    exceptions.clone(),
                ));
            }
            Err(error) => {
                return Err(RuntimeFailure::new(
                    RuntimeFailureCode::TransportReceiveFailed,
                    error.to_string(),
                    evidence.clone(),
                    exceptions.clone(),
                ));
            }
        };
        if !envelope_is_attributable(envelope, &packet) {
            continue;
        }
        let Some((channel, node)) = RtlinkFrame::route(&packet.payload) else {
            continue;
        };
        if channel != program.reply_channel() || node != program.reply_node() {
            continue;
        }
        let frame = RtlinkFrame::decode(&packet.payload)
            .map_err(|error| protocol_failure(error.to_string(), evidence, exceptions))?;
        apply_frame(
            config,
            frame,
            evidence,
            exceptions,
            &mut exception_addresses,
            &mut results,
        )
        .map_err(|message| protocol_failure(message, evidence, exceptions))?;
    }
}

fn envelope_is_attributable(envelope: TransportEnvelope, packet: &WirePacket) -> bool {
    packet.ether_type == envelope.ether_type
        && packet.source_mac == envelope.destination_mac
        && packet.destination_mac == envelope.source_mac
        && packet.loopback_marker != envelope.loopback_marker
}

fn apply_frame(
    config: &LinuxRawEthernetRuntimeConfig,
    frame: RtlinkFrame,
    evidence: &mut BTreeMap<OasmAddress, BoardExecutionState>,
    exceptions: &mut BTreeMap<OasmAddress, DeviceExceptionReport>,
    exception_addresses: &mut BTreeMap<OasmAddress, u32>,
    results: &mut BTreeMap<OasmAddress, Vec<u32>>,
) -> Result<(), String> {
    let payload = frame.payload();
    if frame.flag() == DOWNLOAD_FLAG {
        let info = payload[0] >> 20;
        let node = payload[0] as u16;
        let Some(board) = board_for_node(config, node) else {
            return Ok(());
        };
        match info {
            1 => {
                if evidence[&board].is_terminal() {
                    return Err(format!(
                        "board {board} reported an exception address after terminal state"
                    ));
                }
                exception_addresses.insert(board, payload[1]);
            }
            0 => {
                if evidence[&board] == BoardExecutionState::Succeeded {
                    return Err(format!(
                        "board {board} reported device failure after success"
                    ));
                }
                evidence.insert(board, BoardExecutionState::DeviceFailed);
                exceptions.insert(
                    board,
                    DeviceExceptionReport {
                        exception_flags: payload[1],
                        instruction_address: exception_addresses.remove(&board),
                    },
                );
            }
            _ => results.entry(board).or_default().push(payload[1]),
        }
        return Ok(());
    }

    if frame.tag() == OPERATION_TAG {
        let argument_count = payload[0] >> 16;
        let node = payload[0] as u16;
        let Some(board) = board_for_node(config, node) else {
            return Ok(());
        };
        if payload[1] == 0 && argument_count == 0 {
            if exception_addresses.contains_key(&board) {
                return Err(format!(
                    "board {board} reported success after an exception address"
                ));
            }
            if evidence[&board] == BoardExecutionState::DeviceFailed {
                return Err(format!(
                    "board {board} reported success after device failure"
                ));
            }
            if evidence[&board] == BoardExecutionState::Succeeded {
                return Err(format!(
                    "board {board} reported duplicate successful completion"
                ));
            }
            evidence.insert(board, BoardExecutionState::Succeeded);
        } else if payload[1] != 0 {
            results.entry(board).or_default().extend(payload);
        }
        return Ok(());
    }

    let node = frame.tag() as u16;
    let Some(board) = board_for_node(config, node) else {
        return Ok(());
    };
    if evidence[&board].is_terminal() {
        return Err(format!(
            "board {board} sent result data after terminal state"
        ));
    }
    results.entry(board).or_default().extend(payload);
    Ok(())
}

fn board_for_node(config: &LinuxRawEthernetRuntimeConfig, node: u16) -> Option<OasmAddress> {
    config
        .boards()
        .iter()
        .copied()
        .find_map(|endpoint| (endpoint.node() == node).then_some(endpoint.address()))
}

fn protocol_failure(
    message: impl Into<String>,
    evidence: &BTreeMap<OasmAddress, BoardExecutionState>,
    exceptions: &BTreeMap<OasmAddress, DeviceExceptionReport>,
) -> RuntimeFailure {
    RuntimeFailure::new(
        RuntimeFailureCode::ProtocolViolation,
        message,
        evidence.clone(),
        exceptions.clone(),
    )
}

fn derive_certainty(evidence: &BTreeMap<OasmAddress, BoardExecutionState>) -> ExecutionCertainty {
    if evidence.values().any(|state| {
        matches!(
            state,
            BoardExecutionState::LaunchSubmitted
                | BoardExecutionState::Succeeded
                | BoardExecutionState::DeviceFailed
        )
    }) {
        if evidence
            .values()
            .any(|state| *state == BoardExecutionState::LaunchSubmitted)
        {
            ExecutionCertainty::Indeterminate
        } else {
            ExecutionCertainty::FullyObserved
        }
    } else {
        ExecutionCertainty::NotStarted
    }
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, VecDeque};

    use crate::model::{AssembledOasmBoard, BoardEndpoint};
    use crate::transport::{
        ETHER_TYPE, InMemoryTransport, ReceiveError, SendError, TransportError,
    };

    use super::*;

    const LOCAL_MAC: [u8; 6] = [1; 6];
    const REMOTE_MAC: [u8; 6] = [2; 6];
    const OUTGOING_MARKER: [u8; 8] = [9; 8];
    const INCOMING_MARKER: [u8; 8] = [8; 8];
    const REPLY_CHANNEL: u8 = 3;
    const DOWNLOAD_CHANNEL: u8 = 7;

    fn envelope() -> TransportEnvelope {
        TransportEnvelope {
            ether_type: ETHER_TYPE,
            source_mac: LOCAL_MAC,
            destination_mac: REMOTE_MAC,
            loopback_marker: OUTGOING_MARKER,
        }
    }

    fn program(addresses: &[OasmAddress]) -> AssembledOasmProgram {
        AssembledOasmProgram::new(
            1,
            20,
            REPLY_CHANNEL,
            addresses
                .iter()
                .copied()
                .map(|address| {
                    AssembledOasmBoard::new(address, vec![0x00d0_0000, 0x00d0_0000], 1).unwrap()
                })
                .collect(),
        )
        .unwrap()
    }

    fn config(bindings: &[(OasmAddress, u16)]) -> LinuxRawEthernetRuntimeConfig {
        LinuxRawEthernetRuntimeConfig::new(
            1,
            "test0".to_owned(),
            Some(REMOTE_MAC),
            10,
            bindings
                .iter()
                .map(|(address, node)| {
                    BoardEndpoint::new(*address, *node, DOWNLOAD_CHANNEL, 131_072).unwrap()
                })
                .collect(),
        )
        .unwrap()
    }

    fn incoming(frame: RtlinkFrame) -> WirePacket {
        WirePacket {
            ether_type: ETHER_TYPE,
            source_mac: REMOTE_MAC,
            destination_mac: LOCAL_MAC,
            loopback_marker: INCOMING_MARKER,
            payload: frame.encode().to_vec(),
        }
    }

    fn completion(node: u16) -> WirePacket {
        incoming(
            RtlinkFrame::new(0, REPLY_CHANNEL, 20, OPERATION_TAG, [u32::from(node), 0]).unwrap(),
        )
    }

    fn exception_address(node: u16, address: u32) -> WirePacket {
        incoming(
            RtlinkFrame::new(
                DOWNLOAD_FLAG,
                REPLY_CHANNEL,
                20,
                0,
                [(1 << 20) | u32::from(node), address],
            )
            .unwrap(),
        )
    }

    fn exception(node: u16, flags: u32) -> WirePacket {
        incoming(
            RtlinkFrame::new(
                DOWNLOAD_FLAG,
                REPLY_CHANNEL,
                20,
                0,
                [u32::from(node), flags],
            )
            .unwrap(),
        )
    }

    #[test]
    fn invalid_topology_is_rejected_before_transport_open() {
        let program = program(&[OasmAddress::Rwg0, OasmAddress::Rwg1]);
        let wrong = config(&[(OasmAddress::Rwg0, 2)]);
        let mut transport = InMemoryTransport::new(envelope());

        let failure = execute_with_transport(&program, &wrong, &mut transport, 100).unwrap_err();

        assert_eq!(failure.code, RuntimeFailureCode::TopologyInvalid);
        assert_eq!(failure.execution_certainty, ExecutionCertainty::NotStarted);
        assert_eq!(transport.opened, 0);
        assert_eq!(transport.sent.len(), 0);
    }

    #[test]
    fn transport_open_failure_is_not_started() {
        let one = program(&[OasmAddress::Rwg0]);
        let topology = config(&[(OasmAddress::Rwg0, 2)]);
        let mut transport = InMemoryTransport::new(envelope());
        transport.open_error = Some(TransportError("permission denied".to_owned()));

        let failure = execute_with_transport(&one, &topology, &mut transport, 100).unwrap_err();

        assert_eq!(failure.code, RuntimeFailureCode::TransportOpenFailed);
        assert_eq!(failure.execution_certainty, ExecutionCertainty::NotStarted);
        assert_eq!(
            failure.board_evidence[&OasmAddress::Rwg0],
            BoardExecutionState::NotDispatched
        );
        assert_eq!(transport.closed, 0);
    }

    #[test]
    fn explicitly_rejected_frame_is_retried() {
        let one = program(&[OasmAddress::Rwg0]);
        let topology = config(&[(OasmAddress::Rwg0, 2)]);
        let mut transport = InMemoryTransport::with_received(envelope(), [completion(2)]);
        transport
            .send_faults
            .push_back(Err(SendError::not_accepted("would block")));

        let success = execute_with_transport(&one, &topology, &mut transport, 100).unwrap();

        assert_eq!(
            success.board_evidence[&OasmAddress::Rwg0],
            BoardExecutionState::Succeeded
        );
        assert!(!transport.sent.is_empty());
    }

    #[test]
    fn acceptance_unknown_is_never_retried_and_advances_evidence() {
        let one = program(&[OasmAddress::Rwg0]);
        let topology = config(&[(OasmAddress::Rwg0, 2)]);
        let mut transport = InMemoryTransport::new(envelope());
        transport
            .send_faults
            .push_back(Err(SendError::acceptance_unknown("short write")));

        let failure = execute_with_transport(&one, &topology, &mut transport, 100).unwrap_err();

        assert_eq!(failure.code, RuntimeFailureCode::TransportSendFailed);
        assert_eq!(failure.execution_certainty, ExecutionCertainty::NotStarted);
        assert_eq!(
            failure.board_evidence[&OasmAddress::Rwg0],
            BoardExecutionState::LoaderSubmitted
        );
        assert!(transport.sent.is_empty());
        assert_eq!(transport.closed, 1);
    }

    #[test]
    fn successful_multiboard_run_requires_every_terminal_completion() {
        let program = program(&[OasmAddress::Rwg0, OasmAddress::Rwg1]);
        let topology = config(&[(OasmAddress::Rwg0, 2), (OasmAddress::Rwg1, 5)]);
        let mut transport =
            InMemoryTransport::with_received(envelope(), [completion(5), completion(2)]);

        let success = execute_with_transport(&program, &topology, &mut transport, 100).unwrap();

        assert_eq!(
            success.board_evidence.values().copied().collect::<Vec<_>>(),
            vec![
                BoardExecutionState::Succeeded,
                BoardExecutionState::Succeeded
            ]
        );
        assert_eq!(transport.opened, 1);
        assert_eq!(transport.closed, 1);
        for packet in transport.sent {
            let frame = RtlinkFrame::decode(&packet.payload).unwrap();
            assert_eq!(frame.channel(), DOWNLOAD_CHANNEL);
            assert!(matches!(frame.node(), 2 | 5));
        }
    }

    #[test]
    fn all_device_failures_are_fully_observed_and_keep_reports() {
        let program = program(&[OasmAddress::Rwg0, OasmAddress::Rwg1]);
        let topology = config(&[(OasmAddress::Rwg0, 2), (OasmAddress::Rwg1, 5)]);
        let flags = (1 << 2) | (1 << 7) | (1 << 8);
        let mut transport = InMemoryTransport::with_received(
            envelope(),
            [
                exception_address(2, 0),
                exception(2, flags),
                exception(5, 1 << 4),
            ],
        );

        let failure = execute_with_transport(&program, &topology, &mut transport, 100).unwrap_err();

        assert_eq!(failure.code, RuntimeFailureCode::DeviceException);
        assert_eq!(
            failure.execution_certainty,
            ExecutionCertainty::FullyObserved
        );
        assert_eq!(failure.device_exceptions.len(), 2);
        assert_eq!(
            failure.device_exceptions[&OasmAddress::Rwg0].instruction_address,
            Some(0)
        );
        assert_eq!(
            failure.device_exceptions[&OasmAddress::Rwg1].instruction_address,
            None
        );
    }

    #[test]
    fn unresolved_board_at_deadline_retains_prior_exception() {
        let program = program(&[OasmAddress::Rwg0, OasmAddress::Rwg1]);
        let topology = config(&[(OasmAddress::Rwg0, 2), (OasmAddress::Rwg1, 5)]);
        let mut transport = InMemoryTransport::with_received(envelope(), [exception(2, 0x84)]);

        let failure = execute_with_transport(&program, &topology, &mut transport, 100).unwrap_err();

        assert_eq!(failure.code, RuntimeFailureCode::CompletionTimeout);
        assert_eq!(
            failure.execution_certainty,
            ExecutionCertainty::Indeterminate
        );
        assert_eq!(
            failure.board_evidence[&OasmAddress::Rwg1],
            BoardExecutionState::LaunchSubmitted
        );
        assert_eq!(
            failure.device_exceptions[&OasmAddress::Rwg0].exception_flags,
            0x84
        );
    }

    #[test]
    fn receive_failure_retains_prior_terminal_evidence() {
        let program = program(&[OasmAddress::Rwg0, OasmAddress::Rwg1]);
        let topology = config(&[(OasmAddress::Rwg0, 2), (OasmAddress::Rwg1, 5)]);
        let mut transport = InMemoryTransport::new(envelope());
        transport.receive_queue = VecDeque::from([
            Ok(Some(exception(2, 4))),
            Err(ReceiveError("device disappeared".to_owned())),
        ]);

        let failure = execute_with_transport(&program, &topology, &mut transport, 100).unwrap_err();

        assert_eq!(failure.code, RuntimeFailureCode::TransportReceiveFailed);
        assert_eq!(
            failure.execution_certainty,
            ExecutionCertainty::Indeterminate
        );
        assert_eq!(
            failure.device_exceptions[&OasmAddress::Rwg0].exception_flags,
            4
        );
    }

    #[test]
    fn unrelated_traffic_is_ignored_before_protocol_validation() {
        let one = program(&[OasmAddress::Rwg0]);
        let topology = config(&[(OasmAddress::Rwg0, 2)]);
        let mut unrelated = completion(2);
        unrelated.ether_type = 0x1234;
        unrelated.payload = vec![1, 2, 3];
        let mut loopback = completion(2);
        loopback.loopback_marker = OUTGOING_MARKER;
        loopback.payload = vec![1];
        let mut wrong_reply =
            incoming(RtlinkFrame::new(0, REPLY_CHANNEL + 1, 20, OPERATION_TAG, [2, 0]).unwrap());
        wrong_reply.payload.truncate(6);
        let mut transport = InMemoryTransport::with_received(
            envelope(),
            [unrelated, loopback, wrong_reply, completion(2)],
        );

        execute_with_transport(&one, &topology, &mut transport, 100).unwrap();
    }

    #[test]
    fn malformed_attributable_and_contradictory_terminal_are_violations() {
        let one = program(&[OasmAddress::Rwg0]);
        let one_topology = config(&[(OasmAddress::Rwg0, 2)]);
        let malformed = WirePacket {
            payload: completion(2).payload[..6].to_vec(),
            ..completion(2)
        };
        let mut transport = InMemoryTransport::with_received(envelope(), [malformed]);
        let failure = execute_with_transport(&one, &one_topology, &mut transport, 100).unwrap_err();
        assert_eq!(failure.code, RuntimeFailureCode::ProtocolViolation);

        let two = program(&[OasmAddress::Rwg0, OasmAddress::Rwg1]);
        let two_topology = config(&[(OasmAddress::Rwg0, 2), (OasmAddress::Rwg1, 5)]);
        let mut transport =
            InMemoryTransport::with_received(envelope(), [completion(2), exception(2, 1)]);
        let failure = execute_with_transport(&two, &two_topology, &mut transport, 100).unwrap_err();
        assert_eq!(failure.code, RuntimeFailureCode::ProtocolViolation);
        assert_eq!(
            failure.board_evidence[&OasmAddress::Rwg0],
            BoardExecutionState::Succeeded
        );
    }

    #[test]
    fn pending_exception_address_cannot_be_discarded_by_success() {
        let one = program(&[OasmAddress::Rwg0]);
        let topology = config(&[(OasmAddress::Rwg0, 2)]);
        let mut transport =
            InMemoryTransport::with_received(envelope(), [exception_address(2, 17), completion(2)]);

        let failure = execute_with_transport(&one, &topology, &mut transport, 100).unwrap_err();

        assert_eq!(failure.code, RuntimeFailureCode::ProtocolViolation);
        assert_eq!(
            failure.board_evidence[&OasmAddress::Rwg0],
            BoardExecutionState::LaunchSubmitted
        );
    }

    #[test]
    fn runtime_failure_rejects_certainty_that_contradicts_evidence() {
        let program = program(&[OasmAddress::Rwg0, OasmAddress::Rwg1]);
        let topology = config(&[(OasmAddress::Rwg0, 2), (OasmAddress::Rwg1, 5)]);
        let mut transport = InMemoryTransport::with_received(envelope(), [completion(2)]);
        let mut failure =
            execute_with_transport(&program, &topology, &mut transport, 100).unwrap_err();

        assert!(failure.validate().is_ok());
        failure.execution_certainty = ExecutionCertainty::NotStarted;
        assert!(failure.validate().is_err());
    }

    #[test]
    fn explicitly_rejected_frame_stops_after_retry_budget() {
        let one = program(&[OasmAddress::Rwg0]);
        let topology = config(&[(OasmAddress::Rwg0, 2)]);
        let mut transport = InMemoryTransport::new(envelope());
        transport.send_faults = (0..2)
            .map(|_| Err(SendError::not_accepted("still blocked")))
            .collect();

        let failure = execute_with_transport(&one, &topology, &mut transport, 1).unwrap_err();

        assert_eq!(failure.code, RuntimeFailureCode::TransportSendFailed);
        assert_eq!(
            failure.board_evidence[&OasmAddress::Rwg0],
            BoardExecutionState::NotDispatched
        );
        assert_eq!(transport.closed, 1);
    }

    #[test]
    fn capacity_failure_materializes_no_physical_side_effect() {
        let one = program(&[OasmAddress::Rwg0]);
        let too_small = LinuxRawEthernetRuntimeConfig::new(
            1,
            "test0".to_owned(),
            Some(REMOTE_MAC),
            10,
            vec![BoardEndpoint::new(OasmAddress::Rwg0, 2, DOWNLOAD_CHANNEL, 1).unwrap()],
        )
        .unwrap();
        let mut transport = InMemoryTransport::new(envelope());

        let failure = execute_with_transport(&one, &too_small, &mut transport, 100).unwrap_err();

        assert_eq!(failure.code, RuntimeFailureCode::TopologyInvalid);
        assert_eq!(transport.opened, 0);
        assert!(transport.sent.is_empty());
    }

    #[test]
    fn result_data_is_collected_by_logical_board() {
        let one = program(&[OasmAddress::Rwg0]);
        let topology = config(&[(OasmAddress::Rwg0, 2)]);
        let result = incoming(
            RtlinkFrame::new(0, REPLY_CHANNEL, 20, 2, [0x1234_5678, 0x9abc_def0]).unwrap(),
        );
        let mut transport = InMemoryTransport::with_received(envelope(), [result, completion(2)]);

        let success = execute_with_transport(&one, &topology, &mut transport, 100).unwrap();

        assert_eq!(
            success.results[&OasmAddress::Rwg0],
            [0x1234_5678, 0x9abc_def0]
        );
    }

    #[test]
    fn evidence_order_is_logical_address_order() {
        let evidence = BTreeMap::from([
            (OasmAddress::Rwg1, BoardExecutionState::NotDispatched),
            (OasmAddress::Rwg0, BoardExecutionState::NotDispatched),
        ]);

        assert_eq!(
            evidence.keys().copied().collect::<Vec<_>>(),
            vec![OasmAddress::Rwg0, OasmAddress::Rwg1]
        );
    }
}
