//! Target-independent RTMQ v2 primitive instruction encoding and diagnostics.

use std::error::Error;
use std::fmt::{Display, Formatter};

const LOW_20_MASK: u32 = 0x000f_ffff;
const HIGH_12_MAX: u16 = 0x0fff;
const SIGNED_20_MIN: i32 = -(1 << 19);
const SIGNED_20_MAX: i32 = (1 << 19) - 1;

/// Address of one control/status register.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CsrAddress(pub u8);

/// Address of one tightly-coupled stack register.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TcsAddress(pub u8);

/// Flow behavior attached to a primitive RTMQ instruction.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FlowControl {
    Continue,
    Halt,
    Pause,
}

impl FlowControl {
    const fn opcode_offset(self) -> u32 {
        match self {
            Self::Continue => 0,
            Self::Halt => 1,
            Self::Pause => 2,
        }
    }

    const fn from_opcode_offset(offset: u32) -> Option<Self> {
        match offset {
            0 => Some(Self::Continue),
            1 => Some(Self::Halt),
            2 => Some(Self::Pause),
            _ => None,
        }
    }

    const fn diagnostic(self) -> &'static str {
        match self {
            Self::Continue => "-",
            Self::Halt => "H",
            Self::Pause => "P",
        }
    }
}

/// An eight-bit operand accepted by the RTMQ atomic-mask format.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AtomicOperand {
    Nibble { nibble: u8, position: u8 },
    Immediate(i8),
    Csr(CsrAddress),
    Tcs(TcsAddress),
}

impl AtomicOperand {
    fn encode(self) -> Result<(u8, u8), EncodeError> {
        match self {
            Self::Nibble { nibble, position } if nibble < 16 && position < 16 => {
                Ok(((nibble << 4) | position, 0))
            }
            Self::Nibble { .. } => Err(EncodeError::new(
                "atomic nibble and position must both fit four bits",
            )),
            Self::Immediate(value) => Ok((value as u8, 1)),
            Self::Csr(address) => Ok((address.0, 2)),
            Self::Tcs(address) => Ok((address.0, 3)),
        }
    }

    fn decode(value: u8, kind: u8) -> Option<Self> {
        match kind {
            0 => Some(Self::Nibble {
                nibble: value >> 4,
                position: value & 0x0f,
            }),
            1 => Some(Self::Immediate(value as i8)),
            2 => Some(Self::Csr(CsrAddress(value))),
            3 => Some(Self::Tcs(TcsAddress(value))),
            _ => None,
        }
    }
}

/// One primitive RTMQ v2 instruction represented before binary encoding.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Instruction {
    Nop(FlowControl),
    CsrHighImmediate {
        destination: CsrAddress,
        high_12_bits: u16,
    },
    CsrLowImmediate {
        destination: CsrAddress,
        low_20_bits: u32,
        flow: FlowControl,
    },
    TcsLowImmediate {
        destination: TcsAddress,
        value: i32,
    },
    AtomicMask {
        destination: CsrAddress,
        mask: AtomicOperand,
        source: AtomicOperand,
        flow: FlowControl,
    },
}

impl Instruction {
    /// Encode exactly one primitive instruction into exactly one hardware word.
    pub fn encode(self) -> Result<u32, EncodeError> {
        match self {
            Self::Nop(flow) => Ok((13 + flow.opcode_offset()) << 20),
            Self::CsrHighImmediate {
                destination,
                high_12_bits,
            } => {
                if high_12_bits > HIGH_12_MAX {
                    return Err(EncodeError::new(
                        "CSR high immediate does not fit twelve bits",
                    ));
                }
                Ok(u32::from(destination.0) << 24 | 8 << 20 | u32::from(high_12_bits))
            }
            Self::CsrLowImmediate {
                destination,
                low_20_bits,
                flow,
            } => {
                if low_20_bits > LOW_20_MASK {
                    return Err(EncodeError::new(
                        "CSR low immediate does not fit twenty bits",
                    ));
                }
                Ok(u32::from(destination.0) << 24 | (9 + flow.opcode_offset()) << 20 | low_20_bits)
            }
            Self::TcsLowImmediate { destination, value } => {
                if !(SIGNED_20_MIN..=SIGNED_20_MAX).contains(&value) {
                    return Err(EncodeError::new(
                        "TCS low immediate does not fit signed twenty bits",
                    ));
                }
                Ok(u32::from(destination.0) << 24 | 2 << 20 | value as u32 & LOW_20_MASK)
            }
            Self::AtomicMask {
                destination,
                mask,
                source,
                flow,
            } => {
                let (mask_value, mask_kind) = mask.encode()?;
                if mask_kind != 0 && mask_kind != 3 {
                    return Err(EncodeError::new(
                        "atomic mask operand must be a nibble or TCS register",
                    ));
                }
                let (source_value, source_kind) = source.encode()?;
                Ok(u32::from(destination.0) << 24
                    | (13 + flow.opcode_offset()) << 20
                    | u32::from(source_kind >> 1) << 18
                    | u32::from(mask_kind & 1) << 17
                    | u32::from(source_kind & 1) << 16
                    | u32::from(mask_value) << 8
                    | u32::from(source_value))
            }
        }
    }
}

/// A word decoded for diagnostics without discarding unsupported instructions.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DecodedInstruction {
    Known(Instruction),
    Unknown(u32),
}

impl DecodedInstruction {
    pub fn decode(word: u32) -> Self {
        let destination = (word >> 24) as u8;
        let major = (word >> 20) & 0x0f;
        let low_20_bits = word & LOW_20_MASK;

        let instruction = match major {
            13..=15 if destination == 0 && low_20_bits == 0 => {
                FlowControl::from_opcode_offset(major - 13).map(Instruction::Nop)
            }
            8 if low_20_bits <= u32::from(HIGH_12_MAX) => Some(Instruction::CsrHighImmediate {
                destination: CsrAddress(destination),
                high_12_bits: low_20_bits as u16,
            }),
            9..=11 => Some(Instruction::CsrLowImmediate {
                destination: CsrAddress(destination),
                low_20_bits,
                flow: FlowControl::from_opcode_offset(major - 9)
                    .expect("CLO opcode range has a flow control"),
            }),
            2 => {
                let value = ((low_20_bits << 12) as i32) >> 12;
                Some(Instruction::TcsLowImmediate {
                    destination: TcsAddress(destination),
                    value,
                })
            }
            13..=15 => decode_atomic_mask(word, CsrAddress(destination), major - 13),
            _ => None,
        };
        instruction.map_or(Self::Unknown(word), Self::Known)
    }
}

fn decode_atomic_mask(word: u32, destination: CsrAddress, flow_offset: u32) -> Option<Instruction> {
    let mask_value = ((word >> 8) & 0xff) as u8;
    let mask_kind = if word & (1 << 17) == 0 { 0 } else { 3 };
    let source_value = (word & 0xff) as u8;
    let source_kind = (((word >> 18) & 0x03) as u8) << 1 | ((word >> 16) & 0x01) as u8;
    Some(Instruction::AtomicMask {
        destination,
        mask: AtomicOperand::decode(mask_value, mask_kind)?,
        source: AtomicOperand::decode(source_value, source_kind)?,
        flow: FlowControl::from_opcode_offset(flow_offset)?,
    })
}

impl Display for DecodedInstruction {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Known(instruction) => Display::fmt(instruction, formatter),
            Self::Unknown(word) => write!(formatter, ".word 0x{word:08x}"),
        }
    }
}

impl Display for Instruction {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Nop(flow) => write!(formatter, "NOP {}", flow.diagnostic()),
            Self::CsrHighImmediate {
                destination,
                high_12_bits,
            } => write!(
                formatter,
                "CHI - &{:02x} 0x{high_12_bits:03x}_00000",
                destination.0
            ),
            Self::CsrLowImmediate {
                destination,
                low_20_bits,
                flow,
            } => write!(
                formatter,
                "CLO {} &{:02x} 0x000_{low_20_bits:05x}",
                flow.diagnostic(),
                destination.0
            ),
            Self::TcsLowImmediate { destination, value } => {
                write!(formatter, "GLO - ${:02x} {value}", destination.0)
            }
            Self::AtomicMask {
                destination,
                mask,
                source,
                flow,
            } => write!(
                formatter,
                "AMK {} &{:02x} {} {}",
                flow.diagnostic(),
                destination.0,
                DisplayAtomicOperand(*mask),
                DisplayAtomicOperand(*source)
            ),
        }
    }
}

struct DisplayAtomicOperand(AtomicOperand);

impl Display for DisplayAtomicOperand {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self.0 {
            AtomicOperand::Nibble { nibble, position } => {
                write!(formatter, "{nibble:x}.{position:x}")
            }
            AtomicOperand::Immediate(value) => write!(formatter, "{value}"),
            AtomicOperand::Csr(address) => write!(formatter, "&{:02x}", address.0),
            AtomicOperand::Tcs(address) => write!(formatter, "${:02x}", address.0),
        }
    }
}

/// A primitive instruction cannot be represented in its fixed hardware field.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EncodeError {
    message: &'static str,
}

impl EncodeError {
    const fn new(message: &'static str) -> Self {
        Self { message }
    }
}

impl Display for EncodeError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.message)
    }
}

impl Error for EncodeError {}
