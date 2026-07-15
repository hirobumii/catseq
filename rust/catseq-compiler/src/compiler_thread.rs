use std::fmt::{Display, Formatter};
use std::io;
use std::thread;

const COMPILER_STACK_BYTES: usize = 16 * 1024 * 1024;

#[derive(Debug)]
pub enum CompilerThreadError {
    Start(io::Error),
    Panic,
}

impl Display for CompilerThreadError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Start(error) => write!(formatter, "cannot start compiler thread: {error}"),
            Self::Panic => formatter.write_str("internal compiler thread panicked"),
        }
    }
}

impl std::error::Error for CompilerThreadError {}

pub fn run_compiler_thread<T, F>(task: F) -> Result<T, CompilerThreadError>
where
    T: Send + 'static,
    F: FnOnce() -> T + Send + 'static,
{
    thread::Builder::new()
        .name("catseqc".into())
        .stack_size(COMPILER_STACK_BYTES)
        .spawn(task)
        .map_err(CompilerThreadError::Start)?
        .join()
        .map_err(|_| CompilerThreadError::Panic)
}
