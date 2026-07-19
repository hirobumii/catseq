use catseq_rtmq::isa::{
    AtomicOperand, CsrAddress, DecodedInstruction, FlowControl, Instruction, TcsAddress,
};

#[test]
fn primitive_encodings_match_frozen_oasm_words() {
    let cases = [
        (Instruction::Nop(FlowControl::Continue), 0x00d0_0000),
        (Instruction::Nop(FlowControl::Halt), 0x00e0_0000),
        (Instruction::Nop(FlowControl::Pause), 0x00f0_0000),
        (
            Instruction::CsrHighImmediate {
                destination: CsrAddress(8),
                high_12_bits: 0x00d,
            },
            0x0880_000d,
        ),
        (
            Instruction::CsrLowImmediate {
                destination: CsrAddress(8),
                low_20_bits: 0,
                flow: FlowControl::Continue,
            },
            0x0890_0000,
        ),
        (
            Instruction::TcsLowImmediate {
                destination: TcsAddress(1),
                value: -1,
            },
            0x012f_ffff,
        ),
        (
            Instruction::AtomicMask {
                destination: CsrAddress(3),
                mask: AtomicOperand::Nibble {
                    nibble: 0,
                    position: 0,
                },
                source: AtomicOperand::Csr(CsrAddress(3)),
                flow: FlowControl::Continue,
            },
            0x03d4_0003,
        ),
    ];

    for (instruction, expected) in cases {
        assert_eq!(instruction.encode().unwrap(), expected);
        assert_eq!(
            DecodedInstruction::decode(expected),
            DecodedInstruction::Known(instruction)
        );
    }
}

#[test]
fn diagnostic_decoder_preserves_unknown_words() {
    let decoded = DecodedInstruction::decode(0x1234_5678);

    assert_eq!(decoded, DecodedInstruction::Unknown(0x1234_5678));
    assert_eq!(decoded.to_string(), ".word 0x12345678");

    let malformed_atomic = DecodedInstruction::decode(0x00dc_0000);
    assert_eq!(malformed_atomic, DecodedInstruction::Unknown(0x00dc_0000));
}

#[test]
fn encoder_rejects_values_that_do_not_fit_the_primitive_fields() {
    let high = Instruction::CsrHighImmediate {
        destination: CsrAddress(8),
        high_12_bits: 0x1000,
    };
    let low = Instruction::CsrLowImmediate {
        destination: CsrAddress(8),
        low_20_bits: 0x10_0000,
        flow: FlowControl::Continue,
    };
    let tcs = Instruction::TcsLowImmediate {
        destination: TcsAddress(0),
        value: 0x8_0000,
    };

    assert!(high.encode().is_err());
    assert!(low.encode().is_err());
    assert!(tcs.encode().is_err());
}
