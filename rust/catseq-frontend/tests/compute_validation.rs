use std::sync::Arc;

use catseq_frontend::{
    BuiltinNameBindingInput, ComputeType, DefinitionNameBindingInput, DefinitionRegistrationInput,
    ModuleRegistrationInput, RegisteredBuiltin, RegisteredDefinitionRole, RegistrationInput,
    register_kernel_modules, validate_compute_roots,
};
use nac3core::toplevel::TopLevelDef;
use nac3core::toplevel::composer::SourceProfile;

fn registered_compute_module(source: &str) -> catseq_frontend::RegisteredKernelModules {
    registered_compute_module_with_bindings(
        source,
        &[("entry", 10), ("twice", 11), ("normalize", 12)],
        &[],
    )
}

fn registered_compute_module_with_bindings(
    source: &str,
    bindings: &[(&str, usize)],
    shadowed_builtins: &[&str],
) -> catseq_frontend::RegisteredKernelModules {
    register_kernel_modules(RegistrationInput {
        modules: vec![ModuleRegistrationInput {
            id: 7,
            import_name: "experiment".to_owned(),
            file_name: "/project/experiment.py".to_owned(),
            source: Arc::from(source),
        }],
        definitions: vec![
            DefinitionRegistrationInput {
                id: 10,
                module_id: 7,
                qualified_name: "entry".to_owned(),
                source_start_line: 1,
                role: RegisteredDefinitionRole::Kernel,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 11,
                module_id: 7,
                qualified_name: "twice".to_owned(),
                source_start_line: 5,
                role: RegisteredDefinitionRole::Compute,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 12,
                module_id: 7,
                qualified_name: "normalize".to_owned(),
                source_start_line: 9,
                role: RegisteredDefinitionRole::Compute,
                atomic_symbol: None,
            },
        ],
        definition_name_bindings: bindings
            .iter()
            .map(|(name, definition_id)| DefinitionNameBindingInput {
                module_id: 7,
                name: (*name).to_owned(),
                definition_id: *definition_id,
            })
            .collect(),
        builtin_name_bindings: [11, 12]
            .into_iter()
            .flat_map(|definition_id| {
                [
                    ("int", RegisteredBuiltin::Int32),
                    ("int32", RegisteredBuiltin::Int32),
                    ("bool", RegisteredBuiltin::Bool),
                    ("range", RegisteredBuiltin::Range),
                ]
                .into_iter()
                .filter(|(name, _)| !shadowed_builtins.contains(name))
                .map(move |(name, builtin)| BuiltinNameBindingInput {
                    definition_id,
                    name: name.to_owned(),
                    builtin,
                })
            })
            .collect(),
        entry_definition_id: 10,
    })
    .expect("fixture must register")
}

#[test]
fn validates_complete_compute_closure_and_retains_typed_units() {
    let registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    if value < 1:\n",
        "        return 1\n",
        "    return twice(value) + 1\n",
    ));

    let validation = validate_compute_roots(&registered, &[12])
        .expect("the two-function integer closure must validate");

    assert_eq!(
        validation
            .interfaces()
            .iter()
            .map(|interface| interface.definition_id())
            .collect::<Vec<_>>(),
        vec![11, 12]
    );
    let normalize = &validation.interfaces()[1];
    assert_eq!(validation.source_profile_id(), "catseq-int32-v1");
    assert_eq!(normalize.parameters(), &[ComputeType::Int32]);
    assert_eq!(normalize.result(), ComputeType::Int32);
    assert_eq!(normalize.abi_signature(), "(i32)->i32");
    assert_eq!(
        normalize.abi_hash(),
        "62874609153d80302e1ae51cca7ba1ed26300410029a62ed7145f757d30b0521"
    );
    assert_eq!(normalize.provenance().module(), "experiment");
    assert_eq!(normalize.provenance().file_name(), "/project/experiment.py");
    assert_eq!(normalize.provenance().line(), 9);
    assert_eq!(validation.unit_store().unit_count(), 2);
    assert_eq!(validation.unit_store().source_unit_count(), 1);
    assert_eq!(
        validation
            .unit_store()
            .top_level_context()
            .unifiers
            .1
            .size_t,
        32
    );
    assert_eq!(
        validation
            .unit_store()
            .top_level_context()
            .builtin_registry
            .source_profile(),
        SourceProfile::CatSeqInt32V1
    );
    assert_eq!(
        validation
            .unit_store()
            .typed_units()
            .iter()
            .map(|unit| unit.definition_id())
            .collect::<Vec<_>>(),
        vec![11, 12]
    );
    assert_eq!(
        validation.unit_store().source_units()[0].source().as_ref(),
        registered.modules()[0].source().as_ref()
    );
    let normalize_unit = &validation.unit_store().typed_units()[1];
    let definition = validation.unit_store().top_level_context().definitions
        [normalize_unit.nac3_definition_id().0]
        .read();
    let TopLevelDef::Function {
        instance_to_stmt, ..
    } = &*definition
    else {
        panic!("the mapped NAC3 typed unit must remain a function")
    };
    assert_eq!(instance_to_stmt.len(), 1);
}

#[test]
fn validates_bool_interfaces_and_catseq_integer_operators() {
    let bool_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> bool:\n",
        "    return value < 0\n",
    ));
    let bool_validation = validate_compute_roots(&bool_registered, &[12])
        .expect("an Int32 comparison may produce a bool Compute interface");
    assert_eq!(
        bool_validation.interfaces()[0].parameters(),
        &[ComputeType::Int32]
    );
    assert_eq!(bool_validation.interfaces()[0].result(), ComputeType::Bool);
    assert_eq!(
        bool_validation.interfaces()[0].abi_signature(),
        "(i32)->bool"
    );

    let explicit_int32_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int32) -> int32:\n",
        "    return value + 1\n",
    ));
    let explicit_int32_validation = validate_compute_roots(&explicit_int32_registered, &[12])
        .expect("an exact int32 synonym must normalize to the Int32 Compute ABI");
    assert_eq!(
        explicit_int32_validation.interfaces()[0].abi_signature(),
        "(i32)->i32"
    );

    let division_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int, divisor: int) -> int:\n",
        "    edge = -2147483648 // -1\n",
        "    return edge + value // divisor + value % divisor\n",
    ));
    let division_validation = validate_compute_roots(&division_registered, &[12])
        .expect("CatSeqInt32V1 must retain typed division and remainder operations");
    assert_eq!(
        division_validation.interfaces()[0].abi_signature(),
        "(i32,i32)->i32"
    );

    let zero_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    return value // (2 - 1 - 1)\n",
    ));
    let zero_error = validate_compute_roots(&zero_registered, &[12])
        .expect_err("a CatSeqInt32V1 source-known zero divisor must fail");
    assert!(zero_error.to_string().contains("must not be zero"));
    assert!(
        zero_error
            .to_string()
            .contains("/project/experiment.py:11:")
    );

    let true_division_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    return value / 2\n",
    ));
    let true_division_error = validate_compute_roots(&true_division_registered, &[12])
        .expect_err("CatSeqInt32V1 must reject true division at the NAC3 semantic seam");
    assert!(
        true_division_error
            .to_string()
            .contains("operator `/` is not admitted by CatSeqInt32V1"),
        "{true_division_error}"
    );
}

#[test]
fn exact_alias_reaches_one_shared_callee_once() {
    let registered = registered_compute_module_with_bindings(
        concat!(
            "@kernel\n",
            "def entry():\n",
            "    pass\n",
            "\n",
            "@compute\n",
            "def twice(value: int) -> int:\n",
            "    return value * 2\n",
            "\n",
            "@compute\n",
            "def normalize(value: int) -> int:\n",
            "    return twice_alias(value) + twice(value)\n",
            "\n",
            "twice_alias = twice\n",
        ),
        &[
            ("entry", 10),
            ("twice", 11),
            ("twice_alias", 11),
            ("normalize", 12),
        ],
        &[],
    );

    let validation = validate_compute_roots(&registered, &[12, 12])
        .expect("an exact alias must retain the registered definition identity");

    assert_eq!(validation.interfaces().len(), 2);
    assert_eq!(validation.unit_store().unit_count(), 2);
}

#[test]
fn module_alias_roots_keep_independent_member_namespaces() {
    let registered = register_kernel_modules(RegistrationInput {
        modules: vec![ModuleRegistrationInput {
            id: 7,
            import_name: "experiment".to_owned(),
            file_name: "/project/experiment.py".to_owned(),
            source: Arc::from(concat!(
                "@kernel\n",
                "def entry():\n",
                "    pass\n",
                "\n",
                "@compute\n",
                "def unary(value: int) -> int:\n",
                "    return value\n",
                "\n",
                "@compute\n",
                "def binary(left: int, right: int) -> int:\n",
                "    return left + right\n",
                "\n",
                "@compute\n",
                "def combine(value: int) -> int:\n",
                "    return first.x(value) + second.x(value, value)\n",
            )),
        }],
        definitions: vec![
            DefinitionRegistrationInput {
                id: 10,
                module_id: 7,
                qualified_name: "entry".to_owned(),
                source_start_line: 1,
                role: RegisteredDefinitionRole::Kernel,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 11,
                module_id: 7,
                qualified_name: "unary".to_owned(),
                source_start_line: 5,
                role: RegisteredDefinitionRole::Compute,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 12,
                module_id: 7,
                qualified_name: "binary".to_owned(),
                source_start_line: 9,
                role: RegisteredDefinitionRole::Compute,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 13,
                module_id: 7,
                qualified_name: "combine".to_owned(),
                source_start_line: 13,
                role: RegisteredDefinitionRole::Compute,
                atomic_symbol: None,
            },
        ],
        definition_name_bindings: vec![
            DefinitionNameBindingInput {
                module_id: 7,
                name: "combine".to_owned(),
                definition_id: 13,
            },
            DefinitionNameBindingInput {
                module_id: 7,
                name: "first.x".to_owned(),
                definition_id: 11,
            },
            DefinitionNameBindingInput {
                module_id: 7,
                name: "second.x".to_owned(),
                definition_id: 12,
            },
        ],
        builtin_name_bindings: [11, 12, 13]
            .into_iter()
            .flat_map(|definition_id| {
                [
                    ("int", RegisteredBuiltin::Int32),
                    ("int32", RegisteredBuiltin::Int32),
                    ("bool", RegisteredBuiltin::Bool),
                    ("range", RegisteredBuiltin::Range),
                ]
                .into_iter()
                .map(move |(name, builtin)| BuiltinNameBindingInput {
                    definition_id,
                    name: name.to_owned(),
                    builtin,
                })
            })
            .collect(),
        entry_definition_id: 10,
    })
    .expect("the exact module namespace aliases must register");

    let validation = validate_compute_roots(&registered, &[13])
        .expect("same-spelled members under distinct roots must retain their own signatures");
    assert_eq!(validation.unit_store().unit_count(), 3);
}

fn registered_same_file_modules(
    second_has_range: bool,
) -> catseq_frontend::RegisteredKernelModules {
    register_kernel_modules(RegistrationInput {
        modules: vec![
            ModuleRegistrationInput {
                id: 7,
                import_name: "first".to_owned(),
                file_name: "/project/shared.py".to_owned(),
                source: Arc::from(concat!(
                    "@kernel\n",
                    "def entry():\n",
                    "    pass\n",
                    "\n",
                    "@compute\n",
                    "def normalize(value: int) -> int:\n",
                    "    return external(value)\n",
                )),
            },
            ModuleRegistrationInput {
                id: 8,
                import_name: "first".to_owned(),
                file_name: "/project/shared.py".to_owned(),
                source: Arc::from(concat!(
                    "@compute\n",
                    "def normalize(value: int) -> int:\n",
                    "    return value\n",
                )),
            },
        ],
        definitions: vec![
            DefinitionRegistrationInput {
                id: 10,
                module_id: 7,
                qualified_name: "entry".to_owned(),
                source_start_line: 1,
                role: RegisteredDefinitionRole::Kernel,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 12,
                module_id: 7,
                qualified_name: "normalize".to_owned(),
                source_start_line: 5,
                role: RegisteredDefinitionRole::Compute,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 11,
                module_id: 8,
                qualified_name: "normalize".to_owned(),
                source_start_line: 1,
                role: RegisteredDefinitionRole::Compute,
                atomic_symbol: None,
            },
        ],
        definition_name_bindings: vec![
            DefinitionNameBindingInput {
                module_id: 7,
                name: "entry".to_owned(),
                definition_id: 10,
            },
            DefinitionNameBindingInput {
                module_id: 7,
                name: "normalize".to_owned(),
                definition_id: 12,
            },
            DefinitionNameBindingInput {
                module_id: 7,
                name: "external".to_owned(),
                definition_id: 11,
            },
            DefinitionNameBindingInput {
                module_id: 8,
                name: "normalize".to_owned(),
                definition_id: 11,
            },
        ],
        builtin_name_bindings: [12, 11]
            .into_iter()
            .flat_map(|definition_id| {
                [
                    ("int", RegisteredBuiltin::Int32),
                    ("int32", RegisteredBuiltin::Int32),
                    ("bool", RegisteredBuiltin::Bool),
                    ("range", RegisteredBuiltin::Range),
                ]
                .into_iter()
                .filter(move |(name, _)| {
                    definition_id != 11 || second_has_range || *name != "range"
                })
                .map(move |(name, builtin)| BuiltinNameBindingInput {
                    definition_id,
                    name: name.to_owned(),
                    builtin,
                })
            })
            .collect(),
        entry_definition_id: 10,
    })
    .expect("the exact modules register independently before Compute validation")
}

#[test]
fn same_file_modules_must_share_frozen_builtin_authority() {
    let identical = registered_same_file_modules(true);
    let validation = validate_compute_roots(&identical, &[12])
        .expect("same-file exact modules with identical authority can share NAC3 source identity");
    assert_eq!(validation.unit_store().unit_count(), 2);

    let divergent = registered_same_file_modules(false);
    let error = validate_compute_roots(&divergent, &[12])
        .expect_err("same-file exact modules cannot retain different builtin authority");
    assert!(
        error
            .to_string()
            .contains("cannot retain distinct builtin authority"),
        "{error}"
    );
    assert!(
        error.to_string().contains("/project/shared.py:5:"),
        "{error}"
    );
}

#[test]
fn rejects_non_compute_calls_and_float_with_source_provenance() {
    let call_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    return entry()\n",
    ));
    let call_error = validate_compute_roots(&call_registered, &[12])
        .expect_err("Compute-to-Kernel calls must fail");
    assert!(call_error.to_string().contains("Kernel"));
    assert!(
        call_error
            .to_string()
            .contains("/project/experiment.py:11:")
    );

    let float_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> float:\n",
        "    return value / 2.0\n",
    ));
    let float_error = validate_compute_roots(&float_registered, &[12])
        .expect_err("every floating-point type and operation must fail");
    assert!(
        float_error
            .to_string()
            .contains("type annotation is not admitted by CatSeqInt32V1"),
        "{float_error}"
    );
    assert!(
        float_error
            .to_string()
            .contains("/project/experiment.py:10:")
    );
}

#[test]
fn preserves_nac3_type_diagnostic_source_locations() {
    let registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    return value < 1\n",
    ));

    let error = validate_compute_roots(&registered, &[12])
        .expect_err("NAC3 must reject a bool body result for an Int32 ABI result");
    assert!(error.to_string().contains("/project/experiment.py:11:"));
}

#[test]
fn rejects_unknown_rebound_name_and_recursive_compute_closure() {
    let rebound_registered = registered_compute_module_with_bindings(
        concat!(
            "@kernel\n",
            "def entry():\n",
            "    pass\n",
            "\n",
            "@compute\n",
            "def twice(value: int) -> int:\n",
            "    return value * 2\n",
            "\n",
            "@compute\n",
            "def normalize(value: int) -> int:\n",
            "    return twice(value)\n",
        ),
        &[("entry", 10), ("normalize", 12)],
        &[],
    );
    let rebound_error = validate_compute_roots(&rebound_registered, &[12])
        .expect_err("a same-name non-Compute binding must not gain authority");
    assert!(
        rebound_error
            .to_string()
            .contains("Host RPC or dynamic callee")
    );
    assert!(
        rebound_error
            .to_string()
            .contains("/project/experiment.py:11:")
    );

    let recursive_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    return normalize(value - 1)\n",
    ));
    let recursion_error = validate_compute_roots(&recursive_registered, &[12])
        .expect_err("runtime recursion is outside the initial Compute profile");
    assert!(
        recursion_error
            .to_string()
            .contains("recursive Compute call")
    );
    assert!(
        recursion_error
            .to_string()
            .contains("/project/experiment.py:11:")
    );
}

#[test]
fn accepts_only_statically_bounded_initial_compute_loops() {
    let bounded_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    result = value\n",
        "    for _ in range(4):\n",
        "        result = (result * 3 + 1) // 4\n",
        "    return result\n",
    ));
    let validation = validate_compute_roots(&bounded_registered, &[12])
        .expect("a literal-bounded scalar range loop must validate");
    assert_eq!(validation.interfaces().len(), 1);

    let bounded_while_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    result = value\n",
        "    iteration = 0\n",
        "    while iteration < 4:\n",
        "        result = (result * 3 + 1) // 4\n",
        "        iteration += 1\n",
        "    return result\n",
    ));
    let validation = validate_compute_roots(&bounded_while_registered, &[12])
        .expect("a literal-initialized monotonic while loop must validate");
    assert_eq!(validation.interfaces().len(), 1);

    let unbounded_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    while value > 0:\n",
        "        value -= 1\n",
        "    return value\n",
    ));
    let error = validate_compute_roots(&unbounded_registered, &[12])
        .expect_err("a runtime-bounded while loop must not acquire a static work bound");
    assert!(error.to_string().contains("literal-initialized counter"));
    assert!(error.to_string().contains("/project/experiment.py:11:"));

    let overflowing_registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    iteration = 2147483647\n",
        "    while iteration <= 2147483647:\n",
        "        iteration += 1\n",
        "    return value\n",
    ));
    let error = validate_compute_roots(&overflowing_registered, &[12])
        .expect_err("an overflowing counter update does not prove a finite while bound");
    assert!(
        error
            .to_string()
            .contains("unconditional monotonic counter update")
    );
}

#[test]
fn rejects_zero_step_static_range() {
    let registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    for _ in range(0, 4, 0):\n",
        "        value += 1\n",
        "    return value\n",
    ));

    let error = validate_compute_roots(&registered, &[12])
        .expect_err("range with a zero step has no valid static work bound");
    assert!(error.to_string().contains("step must not be zero"));
    assert!(error.to_string().contains("/project/experiment.py:11:"));
}

#[test]
fn rejects_first_class_registered_functions() {
    let registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    callback = twice\n",
        "    return value\n",
    ));
    let error = validate_compute_roots(&registered, &[12])
        .expect_err("registered Compute functions must not become first-class values");
    assert!(error.to_string().contains("first-class"));
    assert!(error.to_string().contains("/project/experiment.py:11:"));
}

#[test]
fn rejects_non_scalar_body_values_even_when_unused() {
    let registered = registered_compute_module(concat!(
        "@kernel\n",
        "def entry():\n",
        "    pass\n",
        "\n",
        "@compute\n",
        "def twice(value: int) -> int:\n",
        "    return value * 2\n",
        "\n",
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    unused = 'not a scalar Compute value'\n",
        "    return value\n",
    ));
    let error = validate_compute_roots(&registered, &[12])
        .expect_err("non-scalar values must not enter a validated Compute unit");
    assert!(
        error
            .to_string()
            .contains("string values are not admitted by CatSeqInt32V1"),
        "{error}"
    );
    assert!(error.to_string().contains("/project/experiment.py:11:"));
}
