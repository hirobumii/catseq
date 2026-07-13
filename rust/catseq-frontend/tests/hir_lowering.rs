use catseq_frontend::{CompositionKind, HirKind, SourceModule};

const SOURCE: &str = r#"
from catseq.morphism import Morphism, arena_build, identity

class RydbergTransferExp:
    @arena_build
    def build_sequence(self, params: ExpParams) -> Morphism:
        pulse_time = params[self.pulse_time] * us
        morphism = (
            initialize_service.init()
            >> cooling_service.mot_loading()
            >> {qcmos_trig: pulse(10 * us) >> hold(100 * ms)}
        )
        current_state = get_end_state(morphism)
        morphism = (
            morphism
            >> gates_service.rx_BB1(current_state, np.pi, 0.0)
            >> cz_service.rydberg_pulse(
                pulse_time,
                amp2=self.amp_420,
            )
        )
        return morphism >> identity(1 * us)
"#;

#[test]
fn lowers_realistic_sequence_body_without_executing_python() {
    let module = SourceModule::parse("rydberg_transfer.py", SOURCE).unwrap();
    let hir = module
        .lower_sequence("RydbergTransferExp.build_sequence")
        .unwrap();

    assert_eq!(hir.parameters(), ["self", "params"]);
    assert!(matches!(
        hir.expression(hir.root()).kind(),
        HirKind::Compose {
            kind: CompositionKind::AutoSerial,
            ..
        }
    ));
    assert_eq!(hir.call_count(), 8);
    assert_eq!(hir.composition_count(CompositionKind::AutoSerial), 6);
}

#[test]
fn local_assignments_share_hir_nodes_instead_of_expanding_source() {
    let module = SourceModule::parse(
        "sharing.py",
        "@arena_build\ndef sequence():\n    prefix = first() >> second()\n    return prefix >> third()\n",
    )
    .unwrap();
    let hir = module.lower_sequence("sequence").unwrap();

    let HirKind::Compose { left, .. } = hir.expression(hir.root()).kind() else {
        panic!("root should be a composition")
    };
    assert!(matches!(
        hir.expression(*left).kind(),
        HirKind::Compose {
            kind: CompositionKind::AutoSerial,
            ..
        }
    ));
    assert_eq!(hir.composition_count(CompositionKind::AutoSerial), 2);
}

#[test]
fn unsupported_statement_is_a_compile_error_inside_sequence_entry() {
    let module = SourceModule::parse(
        "unsupported.py",
        "@arena_build\ndef sequence(flag):\n    while flag:\n        side_effect()\n    return identity(1)\n",
    )
    .unwrap();
    let error = module.lower_sequence("sequence").unwrap_err();

    assert!(error.to_string().contains("while_statement"));
    assert!(error.to_string().contains("unsupported.py"));
}
