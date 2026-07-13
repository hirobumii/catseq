use catseq_frontend::{FrontendError, SourceModule};

const SOURCE: &str = r#"
from catseq.morphism import Morphism, arena_build, identity

class RydbergTransferExp:
    amp_420 = 0.11

    @arena_build
    def build_sequence(self, params) -> Morphism:
        pulse_time = params[self.pulse_time]
        morphism = cooling_service.mot_loading() >> identity(10)
        return morphism >> cz_service.rydberg_pulse(
            pulse_time,
            amp2=self.amp_420,
        )

    def prepare_run(self):
        arbitrary_python_is_not_part_of_the_compiler()
"#;

#[test]
fn discovers_decorated_sequence_method_without_executing_python() {
    let module = SourceModule::parse("rydberg_transfer.py", SOURCE).unwrap();

    assert_eq!(module.sequence_entries().len(), 1);
    assert_eq!(
        module.sequence_entries()[0].qualified_name(),
        "RydbergTransferExp.build_sequence"
    );
    assert!(
        module.sequence_entries()[0]
            .source()
            .contains("params[self.pulse_time]")
    );
}

#[test]
fn unrelated_python_methods_are_not_sequence_entries() {
    let module = SourceModule::parse("rydberg_transfer.py", SOURCE).unwrap();

    assert!(
        module
            .sequence_entry("RydbergTransferExp.prepare_run")
            .is_none()
    );
}

#[test]
fn syntax_errors_are_reported_before_semantic_lowering() {
    let error = SourceModule::parse(
        "broken.py",
        "@arena_build\ndef build_sequence(:\n    return identity(1)",
    )
    .unwrap_err();

    assert!(matches!(error, FrontendError::Syntax { .. }));
    assert!(error.to_string().contains("broken.py"));
}
