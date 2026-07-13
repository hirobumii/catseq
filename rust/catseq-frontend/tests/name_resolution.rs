use catseq_frontend::{PathRoot, SourceModule};

const SOURCE: &str = r#"
import numpy as np
from catseq.morphism import arena_build, identity
from rb1system.services.cooling import cooling_service
from rb1system.utils import get_end_state

class Experiment:
    @arena_build
    def sequence(self, params):
        prefix = cooling_service.mot_loading() >> identity(np.pi)
        state = get_end_state(prefix)
        return gates_service.rx_BB1(state, params[self.angle])
"#;

#[test]
fn imported_call_targets_resolve_without_importing_python_modules() {
    let module = SourceModule::parse("experiment.py", SOURCE).unwrap();
    let hir = module.lower_sequence("Experiment.sequence").unwrap();
    let targets = module.resolved_call_targets(&hir);
    let names: Vec<_> = targets
        .iter()
        .map(|target| target.qualified_name())
        .collect();

    assert!(names.contains(&"rb1system.services.cooling.cooling_service.mot_loading"));
    assert!(names.contains(&"catseq.morphism.identity"));
    assert!(names.contains(&"rb1system.utils.get_end_state"));
    assert!(names.contains(&"gates_service.rx_BB1"));
}

#[test]
fn resolver_distinguishes_imports_parameters_and_module_globals() {
    let module = SourceModule::parse("experiment.py", SOURCE).unwrap();
    let hir = module.lower_sequence("Experiment.sequence").unwrap();
    let paths = module.resolved_paths(&hir);

    assert!(
        paths.iter().any(|path| {
            path.root() == PathRoot::Imported && path.qualified_name() == "numpy.pi"
        })
    );
    assert!(paths.iter().any(|path| {
        path.root() == PathRoot::Parameter && path.qualified_name() == "self.angle"
    }));
    assert!(paths.iter().any(|path| {
        path.root() == PathRoot::ModuleGlobal && path.qualified_name() == "gates_service.rx_BB1"
    }));
}

#[test]
fn scan_parameter_subscripts_receive_stable_runtime_slots() {
    let module = SourceModule::parse(
        "scan.py",
        "@arena_build\ndef sequence(self, params: ExpParams):\n    first = identity(params[self.delay])\n    return first >> identity(params[self.delay])\n",
    )
    .unwrap();
    let hir = module.lower_sequence("sequence").unwrap();
    let slots = module.scan_slots(&hir);

    assert_eq!(slots.len(), 2);
    assert_eq!(slots[0].key(), "self.delay");
    assert_eq!(slots[0].runtime_value(), slots[1].runtime_value());
}

#[test]
fn ordinary_dictionary_parameter_is_not_misclassified_as_scan_input() {
    let module = SourceModule::parse(
        "dict.py",
        "@arena_build\ndef sequence(self, params: dict):\n    return identity(params[self.delay])\n",
    )
    .unwrap();
    let hir = module.lower_sequence("sequence").unwrap();

    assert!(module.scan_slots(&hir).is_empty());
}

#[test]
fn function_parameter_shadows_same_named_import() {
    let module = SourceModule::parse(
        "shadow.py",
        "import unrelated as params\n@arena_build\ndef sequence(params: ExpParams):\n    return identity(params[delay])\n",
    )
    .unwrap();
    let hir = module.lower_sequence("sequence").unwrap();
    let paths = module.resolved_paths(&hir);

    assert!(
        paths.iter().any(|path| {
            path.root() == PathRoot::Parameter && path.qualified_name() == "params"
        })
    );
    assert_eq!(module.scan_slots(&hir).len(), 1);
}

#[test]
fn dead_assignments_do_not_allocate_scan_slots_or_call_targets() {
    let module = SourceModule::parse(
        "dead.py",
        "@arena_build\ndef sequence(self, params: ExpParams):\n    unused = identity(params[self.dead])\n    return identity(params[self.live])\n",
    )
    .unwrap();
    let hir = module.lower_sequence("sequence").unwrap();

    assert_eq!(module.scan_slots(&hir).len(), 1);
    assert_eq!(module.scan_slots(&hir)[0].key(), "self.live");
    assert_eq!(module.resolved_call_targets(&hir).len(), 1);
}

#[test]
fn scan_value_cannot_be_used_as_dynamic_callable() {
    let module = SourceModule::parse(
        "callable.py",
        "@arena_build\ndef sequence(self, params: ExpParams):\n    return params[self.operation]()\n",
    )
    .unwrap();
    let hir = module.lower_sequence("sequence").unwrap();
    let error = module.validate_sequence_hir(&hir).unwrap_err();

    assert!(error.to_string().contains("call target"));
    assert!(error.to_string().contains("topology"));
}
