//! Materialization of deployment-time Direct loaders for compiled ICH programs.

use std::error::Error;
use std::fmt::{Display, Formatter};
use std::ops::Range;

use crate::isa::{AtomicOperand, CsrAddress, FlowControl, Instruction, TcsAddress};

const ICA_ADDRESS_SPACE_WORDS: usize = 1 << 20;

const PTR: CsrAddress = CsrAddress(0);
const RSM: CsrAddress = CsrAddress(2);
const EXC: CsrAddress = CsrAddress(3);
const EHN: CsrAddress = CsrAddress(4);
const STK: CsrAddress = CsrAddress(5);
const ICA: CsrAddress = CsrAddress(7);
const ICD: CsrAddress = CsrAddress(8);

/// Target limits and compiler-provided launch metadata for one board program.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DownloadLoaderConfig {
    pub instruction_capacity_words: usize,
    pub exception_handler_word: u32,
}

/// Direct-mode words plus the boundaries needed for conservative dispatch evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DownloadLoader {
    words: Vec<u32>,
    loader_prologue: Range<usize>,
    ich_download: Range<usize>,
    launch: Range<usize>,
}

impl DownloadLoader {
    pub fn words(&self) -> &[u32] {
        &self.words
    }

    pub fn loader_prologue_range(&self) -> Range<usize> {
        self.loader_prologue.clone()
    }

    pub fn ich_download_range(&self) -> Range<usize> {
        self.ich_download.clone()
    }

    pub fn launch_range(&self) -> Range<usize> {
        self.launch.clone()
    }
}

/// Build the OASM-compatible Direct loader without binding RTLink topology.
pub fn materialize_download_loader(
    ich_words: &[u32],
    config: DownloadLoaderConfig,
) -> Result<DownloadLoader, DownloadLoaderError> {
    if ich_words.len() > config.instruction_capacity_words {
        return Err(DownloadLoaderError::ProgramTooLarge {
            words: ich_words.len(),
            capacity: config.instruction_capacity_words,
        });
    }
    if ich_words.len() > ICA_ADDRESS_SPACE_WORDS {
        return Err(DownloadLoaderError::ProgramTooLarge {
            words: ich_words.len(),
            capacity: config
                .instruction_capacity_words
                .min(ICA_ADDRESS_SPACE_WORDS),
        });
    }

    let mut words = Vec::with_capacity(12 + ich_words.len() * 3 + 1);
    push(
        &mut words,
        Instruction::CsrLowImmediate {
            destination: EXC,
            low_20_bits: 1,
            flow: FlowControl::Pause,
        },
    );
    push(
        &mut words,
        Instruction::CsrHighImmediate {
            destination: EXC,
            high_12_bits: 0,
        },
    );
    push(
        &mut words,
        Instruction::CsrHighImmediate {
            destination: RSM,
            high_12_bits: 0,
        },
    );
    push(
        &mut words,
        Instruction::CsrLowImmediate {
            destination: RSM,
            low_20_bits: 1,
            flow: FlowControl::Continue,
        },
    );
    push(
        &mut words,
        Instruction::TcsLowImmediate {
            destination: TcsAddress(0),
            value: 0,
        },
    );
    push(
        &mut words,
        Instruction::TcsLowImmediate {
            destination: TcsAddress(1),
            value: -1,
        },
    );
    let loader_prologue = 0..words.len();

    let ich_start = words.len();
    push(
        &mut words,
        Instruction::CsrHighImmediate {
            destination: ICA,
            high_12_bits: 0,
        },
    );
    for (index, word) in ich_words.iter().copied().enumerate() {
        push(
            &mut words,
            Instruction::CsrLowImmediate {
                destination: ICA,
                low_20_bits: index as u32,
                flow: FlowControl::Continue,
            },
        );
        push(
            &mut words,
            Instruction::CsrHighImmediate {
                destination: ICD,
                high_12_bits: (word >> 20) as u16,
            },
        );
        push(
            &mut words,
            Instruction::CsrLowImmediate {
                destination: ICD,
                low_20_bits: word & 0x000f_ffff,
                flow: FlowControl::Continue,
            },
        );
    }
    let ich_download = ich_start..words.len();

    let launch_start = words.len();
    push(
        &mut words,
        Instruction::AtomicMask {
            destination: EXC,
            mask: nibble(0),
            source: AtomicOperand::Csr(EXC),
            flow: FlowControl::Continue,
        },
    );
    push(
        &mut words,
        Instruction::AtomicMask {
            destination: PTR,
            mask: nibble(2),
            source: AtomicOperand::Immediate(0),
            flow: FlowControl::Pause,
        },
    );
    push(
        &mut words,
        Instruction::CsrHighImmediate {
            destination: EHN,
            high_12_bits: (config.exception_handler_word >> 20) as u16,
        },
    );
    push(
        &mut words,
        Instruction::CsrLowImmediate {
            destination: EHN,
            low_20_bits: config.exception_handler_word & 0x000f_ffff,
            flow: FlowControl::Continue,
        },
    );
    push(
        &mut words,
        Instruction::AtomicMask {
            destination: STK,
            mask: nibble(2),
            source: AtomicOperand::Immediate(0),
            flow: FlowControl::Continue,
        },
    );
    push(
        &mut words,
        Instruction::AtomicMask {
            destination: EXC,
            mask: nibble(1),
            source: nibble(0),
            flow: FlowControl::Pause,
        },
    );
    let launch = launch_start..words.len();

    Ok(DownloadLoader {
        words,
        loader_prologue,
        ich_download,
        launch,
    })
}

const fn nibble(nibble: u8) -> AtomicOperand {
    AtomicOperand::Nibble {
        nibble,
        position: 0,
    }
}

fn push(words: &mut Vec<u32>, instruction: Instruction) {
    words.push(
        instruction
            .encode()
            .expect("fixed Direct loader instruction must fit the RTMQ encoding"),
    );
}

/// The board program cannot be represented by the selected target loader.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DownloadLoaderError {
    ProgramTooLarge { words: usize, capacity: usize },
}

impl Display for DownloadLoaderError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ProgramTooLarge { words, capacity } => write!(
                formatter,
                "ICH program has {words} words but the target capacity is {capacity}"
            ),
        }
    }
}

impl Error for DownloadLoaderError {}
