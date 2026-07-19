use catseq_rtmq::download::{DownloadLoaderConfig, materialize_download_loader};
use serde::Deserialize;

#[derive(Deserialize)]
struct Fixture {
    ich_program: WordProgram,
    loader_program: LoaderProgram,
}

#[derive(Deserialize)]
struct WordProgram {
    words: Vec<String>,
}

#[derive(Deserialize)]
struct LoaderProgram {
    words: Vec<String>,
    sections: Sections,
}

#[derive(Deserialize)]
struct Sections {
    loader_prologue: Section,
    ich_download: Section,
    launch: Section,
}

#[derive(Deserialize)]
struct Section {
    start: usize,
    end: usize,
}

fn words(encoded: &[String]) -> Vec<u32> {
    encoded
        .iter()
        .map(|word| u32::from_str_radix(word, 16).unwrap())
        .collect()
}

#[test]
fn native_download_loader_matches_the_complete_frozen_oasm_loader() {
    let fixture: Fixture = serde_json::from_str(include_str!(
        "../../../tests/fixtures/oasm_parity/v1/runtime/two_board_noop_download.json"
    ))
    .unwrap();
    let ich_words = words(&fixture.ich_program.words);
    let expected_loader = words(&fixture.loader_program.words);

    let loader = materialize_download_loader(
        &ich_words,
        DownloadLoaderConfig {
            instruction_capacity_words: 131_072,
            exception_handler_word: 20,
        },
    )
    .unwrap();

    assert_eq!(loader.words(), expected_loader);
    assert_eq!(
        loader.loader_prologue_range(),
        fixture.loader_program.sections.loader_prologue.start
            ..fixture.loader_program.sections.loader_prologue.end
    );
    assert_eq!(
        loader.ich_download_range(),
        fixture.loader_program.sections.ich_download.start
            ..fixture.loader_program.sections.ich_download.end
    );
    assert_eq!(
        loader.launch_range(),
        fixture.loader_program.sections.launch.start..fixture.loader_program.sections.launch.end
    );
}

#[test]
fn loader_rejects_an_ich_program_larger_than_the_target_capacity() {
    let error = materialize_download_loader(
        &[0x00d0_0000, 0x00d0_0000],
        DownloadLoaderConfig {
            instruction_capacity_words: 1,
            exception_handler_word: 0,
        },
    )
    .unwrap_err();

    assert_eq!(
        error.to_string(),
        "ICH program has 2 words but the target capacity is 1"
    );
}
