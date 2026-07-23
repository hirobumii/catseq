use catseq_runtime::{
    AssembledOasmBoard, AssembledOasmProgram, BoardEndpoint, LinuxRawEthernetRuntimeConfig,
    OasmAddress, RuntimeContractErrorCode, derive_destination_mac, validate_runtime_handoff,
};

#[test]
fn valid_runtime_handoff_keeps_download_and_reply_channels_distinct() {
    let program = AssembledOasmProgram::new(
        1,
        20,
        3,
        vec![
            AssembledOasmBoard::new(OasmAddress::Main, vec![0x00d0_0000, 0x00e0_0000], 1).unwrap(),
        ],
    )
    .unwrap();
    let config = LinuxRawEthernetRuntimeConfig::new(
        1,
        "enp1s0".to_owned(),
        Some([0x02, 0, 0, 0, 0, 4]),
        2_000,
        vec![BoardEndpoint::new(OasmAddress::Main, 2, 0, 1024).unwrap()],
    )
    .unwrap();

    validate_runtime_handoff(&program, &config).unwrap();

    assert_eq!(program.schema_version(), 1);
    assert_eq!(program.reply_node(), 20);
    assert_eq!(program.reply_channel(), 3);
    assert_eq!(program.boards()[0].address(), OasmAddress::Main);
    assert_eq!(program.boards()[0].ich_words(), [0x00d0_0000, 0x00e0_0000]);
    assert_eq!(config.boards()[0].channel(), 0);
}

#[test]
fn unsupported_schema_versions_are_rejected_at_construction() {
    let board = board(OasmAddress::Main, 2, 1);
    let error = AssembledOasmProgram::new(2, 20, 0, vec![board]).unwrap_err();
    assert_eq!(
        error.code(),
        RuntimeContractErrorCode::UnsupportedSchemaVersion
    );

    let error = LinuxRawEthernetRuntimeConfig::new(2, "enp1s0".to_owned(), None, 2_000, vec![])
        .unwrap_err();
    assert_eq!(
        error.code(),
        RuntimeContractErrorCode::UnsupportedSchemaVersion
    );
}

#[test]
fn unknown_board_addresses_are_rejected() {
    let error = "rwg12".parse::<OasmAddress>().unwrap_err();

    assert_eq!(error.code(), RuntimeContractErrorCode::UnknownBoardAddress);
}

#[test]
fn executable_program_requires_unique_boards() {
    let error = AssembledOasmProgram::new(1, 20, 0, vec![]).unwrap_err();
    assert_eq!(error.code(), RuntimeContractErrorCode::EmptyProgram);

    let error = AssembledOasmProgram::new(
        1,
        20,
        0,
        vec![
            board(OasmAddress::Main, 2, 1),
            board(OasmAddress::Main, 2, 1),
        ],
    )
    .unwrap_err();
    assert_eq!(
        error.code(),
        RuntimeContractErrorCode::DuplicateBoardAddress
    );
}

#[test]
fn exception_handler_must_index_its_board_program() {
    let error = AssembledOasmBoard::new(OasmAddress::Main, vec![0x00d0_0000], 1).unwrap_err();

    assert_eq!(
        error.code(),
        RuntimeContractErrorCode::ExceptionHandlerOutOfRange
    );
}

#[test]
fn every_channel_must_fit_the_pinned_five_bit_protocol_field() {
    let error =
        AssembledOasmProgram::new(1, 20, 32, vec![board(OasmAddress::Main, 2, 1)]).unwrap_err();
    assert_eq!(error.code(), RuntimeContractErrorCode::InvalidChannel);

    let error = BoardEndpoint::new(OasmAddress::Main, 2, 32, 1024).unwrap_err();
    assert_eq!(error.code(), RuntimeContractErrorCode::InvalidChannel);
}

#[test]
fn runtime_configuration_requires_unique_addresses_and_nodes() {
    let duplicate_address = LinuxRawEthernetRuntimeConfig::new(
        1,
        "enp1s0".to_owned(),
        None,
        2_000,
        vec![
            endpoint(OasmAddress::Main, 2, 0, 1024),
            endpoint(OasmAddress::Main, 5, 0, 1024),
        ],
    )
    .unwrap_err();
    assert_eq!(
        duplicate_address.code(),
        RuntimeContractErrorCode::DuplicateBoardAddress
    );

    let duplicate_node = LinuxRawEthernetRuntimeConfig::new(
        1,
        "enp1s0".to_owned(),
        None,
        2_000,
        vec![
            endpoint(OasmAddress::Main, 2, 0, 1024),
            endpoint(OasmAddress::Rwg0, 2, 0, 1024),
        ],
    )
    .unwrap_err();
    assert_eq!(
        duplicate_node.code(),
        RuntimeContractErrorCode::DuplicatePhysicalNode
    );
}

#[test]
fn runtime_configuration_requires_a_device_and_nonzero_timeout() {
    let empty_interface =
        LinuxRawEthernetRuntimeConfig::new(1, String::new(), None, 2_000, vec![]).unwrap_err();
    assert_eq!(
        empty_interface.code(),
        RuntimeContractErrorCode::EmptyInterface
    );

    let zero_timeout =
        LinuxRawEthernetRuntimeConfig::new(1, "enp1s0".to_owned(), None, 0, vec![]).unwrap_err();
    assert_eq!(zero_timeout.code(), RuntimeContractErrorCode::ZeroTimeout);
}

#[test]
fn topology_must_map_every_and_only_program_board() {
    let program = program(vec![board(OasmAddress::Main, 2, 1)]);
    let missing = config(vec![]);
    let error = validate_runtime_handoff(&program, &missing).unwrap_err();
    assert_eq!(error.code(), RuntimeContractErrorCode::TopologyMismatch);

    let extra = config(vec![
        endpoint(OasmAddress::Main, 2, 0, 1024),
        endpoint(OasmAddress::Rwg0, 5, 0, 1024),
    ]);
    let error = validate_runtime_handoff(&program, &extra).unwrap_err();
    assert_eq!(error.code(), RuntimeContractErrorCode::TopologyMismatch);
}

#[test]
fn assembled_program_must_fit_the_physical_instruction_capacity() {
    let program = program(vec![board(OasmAddress::Main, 3, 1)]);
    let config = config(vec![endpoint(OasmAddress::Main, 2, 0, 2)]);

    let error = validate_runtime_handoff(&program, &config).unwrap_err();

    assert_eq!(error.code(), RuntimeContractErrorCode::CapacityOverflow);
}

#[test]
fn default_destination_mac_is_checked_as_a_48_bit_addition() {
    assert_eq!(
        derive_destination_mac([0x02, 0, 0, 0, 0, 0xff]).unwrap(),
        [0x02, 0, 0, 0, 1, 1]
    );

    let error = derive_destination_mac([0xff; 6]).unwrap_err();
    assert_eq!(error.code(), RuntimeContractErrorCode::MacOverflow);
}

fn board(
    address: OasmAddress,
    word_count: usize,
    exception_handler_word: u32,
) -> AssembledOasmBoard {
    AssembledOasmBoard::new(
        address,
        vec![0x00d0_0000; word_count],
        exception_handler_word,
    )
    .unwrap()
}

fn program(boards: Vec<AssembledOasmBoard>) -> AssembledOasmProgram {
    AssembledOasmProgram::new(1, 20, 3, boards).unwrap()
}

fn endpoint(
    address: OasmAddress,
    node: u16,
    channel: u8,
    instruction_capacity_words: usize,
) -> BoardEndpoint {
    BoardEndpoint::new(address, node, channel, instruction_capacity_words).unwrap()
}

fn config(boards: Vec<BoardEndpoint>) -> LinuxRawEthernetRuntimeConfig {
    LinuxRawEthernetRuntimeConfig::new(1, "enp1s0".to_owned(), None, 2_000, boards).unwrap()
}
