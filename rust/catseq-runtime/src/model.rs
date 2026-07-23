use std::collections::BTreeSet;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::str::FromStr;

pub const RUNTIME_SCHEMA_VERSION: u32 = 1;
const RTLINK_CHANNEL_MAX: u8 = 31;
const MAC_ADDRESS_MAX: u64 = (1_u64 << 48) - 1;

/// Logical OASM board spelling shared by the assembler and runtime topology.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum OasmAddress {
    Main,
    Rwg0,
    Rwg1,
    Rwg2,
    Rwg3,
    Rwg4,
    Rwg5,
    Rsp6,
    Rsp7,
    Rwg8,
    Rwg9,
    Rsp10,
    Rsp11,
}

impl OasmAddress {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Main => "main",
            Self::Rwg0 => "rwg0",
            Self::Rwg1 => "rwg1",
            Self::Rwg2 => "rwg2",
            Self::Rwg3 => "rwg3",
            Self::Rwg4 => "rwg4",
            Self::Rwg5 => "rwg5",
            Self::Rsp6 => "rsp6",
            Self::Rsp7 => "rsp7",
            Self::Rwg8 => "rwg8",
            Self::Rwg9 => "rwg9",
            Self::Rsp10 => "rsp10",
            Self::Rsp11 => "rsp11",
        }
    }
}

impl Display for OasmAddress {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for OasmAddress {
    type Err = RuntimeContractError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "main" => Ok(Self::Main),
            "rwg0" => Ok(Self::Rwg0),
            "rwg1" => Ok(Self::Rwg1),
            "rwg2" => Ok(Self::Rwg2),
            "rwg3" => Ok(Self::Rwg3),
            "rwg4" => Ok(Self::Rwg4),
            "rwg5" => Ok(Self::Rwg5),
            "rsp6" => Ok(Self::Rsp6),
            "rsp7" => Ok(Self::Rsp7),
            "rwg8" => Ok(Self::Rwg8),
            "rwg9" => Ok(Self::Rwg9),
            "rsp10" => Ok(Self::Rsp10),
            "rsp11" => Ok(Self::Rsp11),
            _ => Err(RuntimeContractError::new(
                RuntimeContractErrorCode::UnknownBoardAddress,
                format!("unknown OASM board address {value:?}"),
            )),
        }
    }
}

/// One finalized board-local ICH image.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssembledOasmBoard {
    address: OasmAddress,
    ich_words: Vec<u32>,
    exception_handler_word: u32,
}

impl AssembledOasmBoard {
    pub fn new(
        address: OasmAddress,
        ich_words: Vec<u32>,
        exception_handler_word: u32,
    ) -> Result<Self, RuntimeContractError> {
        if exception_handler_word as usize >= ich_words.len() {
            return Err(RuntimeContractError::new(
                RuntimeContractErrorCode::ExceptionHandlerOutOfRange,
                format!(
                    "board {address} exception handler word {exception_handler_word} \
                     does not index its {}-word ICH program",
                    ich_words.len()
                ),
            ));
        }
        Ok(Self {
            address,
            ich_words,
            exception_handler_word,
        })
    }

    pub const fn address(&self) -> OasmAddress {
        self.address
    }

    pub fn ich_words(&self) -> &[u32] {
        &self.ich_words
    }

    pub const fn exception_handler_word(&self) -> u32 {
        self.exception_handler_word
    }
}

/// Immutable post-OASM runtime handoff.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssembledOasmProgram {
    schema_version: u32,
    reply_node: u16,
    reply_channel: u8,
    boards: Vec<AssembledOasmBoard>,
}

impl AssembledOasmProgram {
    pub fn new(
        schema_version: u32,
        reply_node: u16,
        reply_channel: u8,
        boards: Vec<AssembledOasmBoard>,
    ) -> Result<Self, RuntimeContractError> {
        validate_schema_version(schema_version)?;
        validate_channel(reply_channel, "reply")?;
        if boards.is_empty() {
            return Err(RuntimeContractError::new(
                RuntimeContractErrorCode::EmptyProgram,
                "an executable assembled program must contain at least one board",
            ));
        }
        let mut addresses = BTreeSet::new();
        for board in &boards {
            if !addresses.insert(board.address()) {
                return Err(RuntimeContractError::new(
                    RuntimeContractErrorCode::DuplicateBoardAddress,
                    format!(
                        "assembled program contains board {} more than once",
                        board.address()
                    ),
                ));
            }
        }
        Ok(Self {
            schema_version,
            reply_node,
            reply_channel,
            boards,
        })
    }

    pub const fn schema_version(&self) -> u32 {
        self.schema_version
    }

    pub const fn reply_node(&self) -> u16 {
        self.reply_node
    }

    pub const fn reply_channel(&self) -> u8 {
        self.reply_channel
    }

    pub fn boards(&self) -> &[AssembledOasmBoard] {
        &self.boards
    }
}

/// Physical RTLink target for one logical OASM board.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BoardEndpoint {
    address: OasmAddress,
    node: u16,
    channel: u8,
    instruction_capacity_words: usize,
}

impl BoardEndpoint {
    pub fn new(
        address: OasmAddress,
        node: u16,
        channel: u8,
        instruction_capacity_words: usize,
    ) -> Result<Self, RuntimeContractError> {
        validate_channel(channel, "download target")?;
        Ok(Self {
            address,
            node,
            channel,
            instruction_capacity_words,
        })
    }

    pub const fn address(self) -> OasmAddress {
        self.address
    }

    pub const fn node(self) -> u16 {
        self.node
    }

    pub const fn channel(self) -> u8 {
        self.channel
    }

    pub const fn instruction_capacity_words(self) -> usize {
        self.instruction_capacity_words
    }
}

/// Linux-only physical runtime configuration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LinuxRawEthernetRuntimeConfig {
    schema_version: u32,
    interface: String,
    destination_mac: Option<[u8; 6]>,
    timeout_ms: u64,
    boards: Vec<BoardEndpoint>,
}

impl LinuxRawEthernetRuntimeConfig {
    pub fn new(
        schema_version: u32,
        interface: String,
        destination_mac: Option<[u8; 6]>,
        timeout_ms: u64,
        boards: Vec<BoardEndpoint>,
    ) -> Result<Self, RuntimeContractError> {
        validate_schema_version(schema_version)?;
        if interface.is_empty() {
            return Err(RuntimeContractError::new(
                RuntimeContractErrorCode::EmptyInterface,
                "raw-Ethernet interface must not be empty",
            ));
        }
        if timeout_ms == 0 {
            return Err(RuntimeContractError::new(
                RuntimeContractErrorCode::ZeroTimeout,
                "runtime timeout must be greater than zero",
            ));
        }
        let mut addresses = BTreeSet::new();
        let mut nodes = BTreeSet::new();
        for endpoint in &boards {
            if !addresses.insert(endpoint.address()) {
                return Err(RuntimeContractError::new(
                    RuntimeContractErrorCode::DuplicateBoardAddress,
                    format!(
                        "runtime configuration contains board {} more than once",
                        endpoint.address()
                    ),
                ));
            }
            if !nodes.insert(endpoint.node()) {
                return Err(RuntimeContractError::new(
                    RuntimeContractErrorCode::DuplicatePhysicalNode,
                    format!(
                        "physical node {} is assigned more than once",
                        endpoint.node()
                    ),
                ));
            }
        }
        Ok(Self {
            schema_version,
            interface,
            destination_mac,
            timeout_ms,
            boards,
        })
    }

    pub const fn schema_version(&self) -> u32 {
        self.schema_version
    }

    pub fn interface(&self) -> &str {
        &self.interface
    }

    pub const fn destination_mac(&self) -> Option<[u8; 6]> {
        self.destination_mac
    }

    pub const fn timeout_ms(&self) -> u64 {
        self.timeout_ms
    }

    pub fn boards(&self) -> &[BoardEndpoint] {
        &self.boards
    }
}

/// Validate facts that involve both the assembled program and physical map.
pub fn validate_runtime_handoff(
    program: &AssembledOasmProgram,
    config: &LinuxRawEthernetRuntimeConfig,
) -> Result<(), RuntimeContractError> {
    let program_addresses = program
        .boards()
        .iter()
        .map(AssembledOasmBoard::address)
        .collect::<BTreeSet<_>>();
    let configured_addresses = config
        .boards()
        .iter()
        .copied()
        .map(BoardEndpoint::address)
        .collect::<BTreeSet<_>>();
    if program_addresses != configured_addresses {
        return Err(RuntimeContractError::new(
            RuntimeContractErrorCode::TopologyMismatch,
            "runtime configuration must map every and only assembled board address",
        ));
    }
    for board in program.boards() {
        let endpoint = config
            .boards()
            .iter()
            .copied()
            .find(|endpoint| endpoint.address() == board.address())
            .expect("equal address sets guarantee an endpoint");
        if board.ich_words().len() > endpoint.instruction_capacity_words() {
            return Err(RuntimeContractError::new(
                RuntimeContractErrorCode::CapacityOverflow,
                format!(
                    "board {} has {} ICH words but physical capacity is {}",
                    board.address(),
                    board.ich_words().len(),
                    endpoint.instruction_capacity_words()
                ),
            ));
        }
    }
    Ok(())
}

/// Preserve pinned OASM behavior by adding two to a source MAC as a 48-bit value.
pub fn derive_destination_mac(source_mac: [u8; 6]) -> Result<[u8; 6], RuntimeContractError> {
    let source = u64::from_be_bytes([
        0,
        0,
        source_mac[0],
        source_mac[1],
        source_mac[2],
        source_mac[3],
        source_mac[4],
        source_mac[5],
    ]);
    let destination = source
        .checked_add(2)
        .filter(|value| *value <= MAC_ADDRESS_MAX)
        .ok_or_else(|| {
            RuntimeContractError::new(
                RuntimeContractErrorCode::MacOverflow,
                "source MAC plus two exceeds the 48-bit MAC address space",
            )
        })?;
    let bytes = destination.to_be_bytes();
    Ok([bytes[2], bytes[3], bytes[4], bytes[5], bytes[6], bytes[7]])
}

fn validate_schema_version(schema_version: u32) -> Result<(), RuntimeContractError> {
    if schema_version != RUNTIME_SCHEMA_VERSION {
        return Err(RuntimeContractError::new(
            RuntimeContractErrorCode::UnsupportedSchemaVersion,
            format!(
                "unsupported runtime schema version {schema_version}; expected \
                 {RUNTIME_SCHEMA_VERSION}"
            ),
        ));
    }
    Ok(())
}

fn validate_channel(channel: u8, role: &str) -> Result<(), RuntimeContractError> {
    if channel > RTLINK_CHANNEL_MAX {
        return Err(RuntimeContractError::new(
            RuntimeContractErrorCode::InvalidChannel,
            format!("{role} channel {channel} exceeds five bits"),
        ));
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum RuntimeContractErrorCode {
    UnsupportedSchemaVersion,
    UnknownBoardAddress,
    EmptyProgram,
    DuplicateBoardAddress,
    DuplicatePhysicalNode,
    InvalidChannel,
    ExceptionHandlerOutOfRange,
    EmptyInterface,
    ZeroTimeout,
    TopologyMismatch,
    CapacityOverflow,
    MacOverflow,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeContractError {
    code: RuntimeContractErrorCode,
    message: String,
}

impl RuntimeContractError {
    fn new(code: RuntimeContractErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    pub const fn code(&self) -> RuntimeContractErrorCode {
        self.code
    }
}

impl Display for RuntimeContractError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for RuntimeContractError {}
