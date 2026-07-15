use std::env;
use std::process::ExitCode;

use catseq_compiler::{CompilerThreadError, run_cli, run_compiler_thread};

fn main() -> ExitCode {
    let args = env::args().skip(1).collect::<Vec<_>>();
    match run_compiler_thread(move || run_cli(args)) {
        Ok(result) => run_exit_code(result),
        Err(error) => {
            eprintln!("catseqc: {error}");
            if matches!(error, CompilerThreadError::Panic) {
                return ExitCode::from(101);
            }
            ExitCode::from(1)
        }
    }
}

fn run_exit_code(result: Result<(), String>) -> ExitCode {
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("catseqc: {message}");
            ExitCode::from(1)
        }
    }
}
