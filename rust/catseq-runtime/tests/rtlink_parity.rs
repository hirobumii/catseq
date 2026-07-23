use catseq_rtmq::download::{DownloadLoaderConfig, materialize_download_loader};
use catseq_runtime::protocol::{RtlinkFrame, encode_word_stream};
use serde_json::Value;

#[test]
fn rust_loader_and_rtlink_match_every_frozen_oasm_download_byte() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/oasm_parity/v1/runtime/two_board_noop_download.json"
    ))
    .unwrap();
    let ich_words = hex_words(&fixture["ich_program"]["words"]);
    let exception_handler_word = fixture["ich_program"]["exception_handler_word"]
        .as_u64()
        .unwrap() as u32;
    let loader = materialize_download_loader(
        &ich_words,
        DownloadLoaderConfig {
            instruction_capacity_words: 131_072,
            exception_handler_word,
        },
    )
    .unwrap();

    assert_eq!(
        loader.words(),
        hex_words(&fixture["loader_program"]["words"])
    );
    assert_eq!(loader.loader_prologue_range(), 0..6);
    assert_eq!(loader.ich_download_range(), 6..193);
    assert_eq!(loader.launch_range(), 193..199);

    for write in fixture["rtlink"]["writes"].as_array().unwrap() {
        let node = write["node"].as_u64().unwrap() as u16;
        let expected = write["frames"]
            .as_array()
            .unwrap()
            .iter()
            .map(|frame| frame.as_str().unwrap())
            .collect::<Vec<_>>();
        let actual = encode_word_stream(4, 0, node, 0, loader.words())
            .unwrap()
            .into_iter()
            .map(|frame| hex(&frame.encode()))
            .collect::<Vec<_>>();
        assert_eq!(actual, expected);
        for encoded in actual {
            let decoded = RtlinkFrame::decode(&decode_hex(&encoded)).unwrap();
            assert_eq!(
                (decoded.flag(), decoded.channel(), decoded.node()),
                (4, 0, node)
            );
        }
    }
}

#[test]
fn odd_word_stream_is_zero_padded_without_changing_header() {
    let frames = encode_word_stream(4, 7, 5, 0, &[1, 2, 3]).unwrap();

    assert_eq!(frames.len(), 2);
    assert_eq!(frames[0].payload(), [1, 2]);
    assert_eq!(frames[1].payload(), [3, 0]);
    assert_eq!(
        (frames[1].flag(), frames[1].channel(), frames[1].node()),
        (4, 7, 5)
    );
}

fn hex_words(value: &Value) -> Vec<u32> {
    value
        .as_array()
        .unwrap()
        .iter()
        .map(|word| u32::from_str_radix(word.as_str().unwrap(), 16).unwrap())
        .collect()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn decode_hex(value: &str) -> Vec<u8> {
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
        .collect()
}
