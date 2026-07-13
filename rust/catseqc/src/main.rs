use std::env;
use std::fs;
use std::process::ExitCode;

use catseq_frontend::SourceModule;

fn main() -> ExitCode {
    match run(env::args().skip(1)) {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("catseqc: {message}");
            ExitCode::from(1)
        }
    }
}

fn run(mut args: impl Iterator<Item = String>) -> Result<(), String> {
    let command = args.next().ok_or_else(usage)?;
    if command != "check" {
        return Err(format!("unknown command {command:?}\n{}", usage()));
    }
    let path = args.next().ok_or_else(usage)?;
    let requested_entry = match args.next() {
        None => None,
        Some(flag) if flag == "--entry" => Some(args.next().ok_or_else(usage)?),
        Some(argument) => return Err(format!("unexpected argument {argument:?}\n{}", usage())),
    };
    if let Some(argument) = args.next() {
        return Err(format!("unexpected argument {argument:?}\n{}", usage()));
    }

    let source =
        fs::read_to_string(&path).map_err(|error| format!("cannot read {path}: {error}"))?;
    let module = SourceModule::parse(&path, &source).map_err(|error| error.to_string())?;
    if let Some(requested) = requested_entry {
        let entry = module
            .sequence_entry(&requested)
            .ok_or_else(|| format!("sequence entry {requested:?} not found in {path}"))?;
        println!("{}", entry.qualified_name());
        return Ok(());
    }
    for entry in module.sequence_entries() {
        println!("{}", entry.qualified_name());
    }
    Ok(())
}

fn usage() -> String {
    String::from("usage: catseqc check <source.py> [--entry <qualified-name>]")
}
