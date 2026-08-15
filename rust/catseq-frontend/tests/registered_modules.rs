use std::sync::Arc;

use catseq_frontend::{
    DefinitionRegistrationInput, ModuleRegistrationInput, RegisteredDefinitionRole,
    RegistrationInput, register_kernel_modules,
};
use nac3ast::StmtKind;

#[test]
fn registers_exact_definitions_from_one_parsed_module() {
    let source = Arc::<str>::from(concat!(
        "@kernel\n",
        "def helper(width: int):\n",
        "    return width\n",
        "\n",
        "@compute\n",
        "def normalize(width: int):\n",
        "    return width + 1\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params):\n",
        "        return helper(params)\n",
    ));
    let registered = register_kernel_modules(RegistrationInput {
        modules: vec![ModuleRegistrationInput {
            id: 7,
            import_name: "experiment".to_owned(),
            file_name: "/project/experiment.py".to_owned(),
            source: Arc::clone(&source),
        }],
        definitions: vec![
            DefinitionRegistrationInput {
                id: 11,
                module_id: 7,
                qualified_name: "helper".to_owned(),
                source_start_line: 1,
                role: RegisteredDefinitionRole::Kernel,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 13,
                module_id: 7,
                qualified_name: "normalize".to_owned(),
                source_start_line: 5,
                role: RegisteredDefinitionRole::Compute,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 12,
                module_id: 7,
                qualified_name: "Experiment.build_sequence".to_owned(),
                source_start_line: 10,
                role: RegisteredDefinitionRole::Kernel,
                atomic_symbol: None,
            },
        ],
        definition_name_bindings: Vec::new(),
        builtin_name_bindings: Vec::new(),
        entry_definition_id: 12,
    })
    .expect("registered source should parse and associate");

    assert_eq!(registered.entry_definition_id(), 12);
    assert_eq!(registered.modules().len(), 1);
    assert_eq!(registered.modules()[0].id(), 7);
    assert_eq!(registered.modules()[0].import_name(), "experiment");
    assert_eq!(
        registered.modules()[0].file_name(),
        "/project/experiment.py"
    );
    assert_eq!(registered.modules()[0].source().as_ref(), source.as_ref());
    assert_eq!(registered.definitions().len(), 3);

    let compute = registered
        .definition(13)
        .expect("Compute definition should remain addressable");
    assert_eq!(compute.qualified_name(), "normalize");
    assert_eq!(compute.role(), RegisteredDefinitionRole::Compute);

    let entry = registered
        .definition(12)
        .expect("entry definition should remain addressable");
    assert_eq!(entry.qualified_name(), "Experiment.build_sequence");
    assert_eq!(entry.role(), RegisteredDefinitionRole::Kernel);
    assert_eq!(
        entry.location().file.0.to_string(),
        "/project/experiment.py"
    );
    assert_eq!(entry.location().row, 10);
    assert_eq!(entry.location().column, 5);
    assert!(matches!(
        registered
            .definition_ast(12)
            .expect("Kernel definitions retain their parsed AST")
            .node,
        StmtKind::FunctionDef { .. }
    ));
}

#[test]
fn associates_nested_registered_definition_by_cpython_qualified_name() {
    let source = Arc::<str>::from(concat!(
        "@kernel\n",
        "def entry():\n",
        "    return None\n",
        "\n",
        "def host_factory():\n",
        "    with registration_scope:\n",
        "        @kernel\n",
        "        def nested():\n",
        "            return None\n",
        "    return nested\n",
    ));
    let registered = register_kernel_modules(RegistrationInput {
        modules: vec![ModuleRegistrationInput {
            id: 0,
            import_name: "nested_experiment".to_owned(),
            file_name: "/project/nested_experiment.py".to_owned(),
            source,
        }],
        definitions: vec![
            DefinitionRegistrationInput {
                id: 0,
                module_id: 0,
                qualified_name: "entry".to_owned(),
                source_start_line: 1,
                role: RegisteredDefinitionRole::Kernel,
                atomic_symbol: None,
            },
            DefinitionRegistrationInput {
                id: 1,
                module_id: 0,
                qualified_name: "host_factory.<locals>.nested".to_owned(),
                source_start_line: 7,
                role: RegisteredDefinitionRole::Kernel,
                atomic_symbol: None,
            },
        ],
        definition_name_bindings: Vec::new(),
        builtin_name_bindings: Vec::new(),
        entry_definition_id: 0,
    })
    .expect("registration associates source but does not validate closure semantics");

    let nested = registered
        .definition(1)
        .expect("nested definition remains registered for later source analysis");
    assert_eq!(nested.qualified_name(), "host_factory.<locals>.nested");
    assert_eq!(nested.location().row, 7);
}

#[test]
fn rejects_distinct_definition_identities_for_one_source_definition() {
    let source = Arc::<str>::from(concat!(
        "@compute\n",
        "def normalize(value: int) -> int:\n",
        "    return value + 1\n",
    ));
    let error = register_kernel_modules(RegistrationInput {
        modules: vec![ModuleRegistrationInput {
            id: 0,
            import_name: "reloaded".to_owned(),
            file_name: "/project/reloaded.py".to_owned(),
            source,
        }],
        definitions: [0, 1]
            .into_iter()
            .map(|id| DefinitionRegistrationInput {
                id,
                module_id: 0,
                qualified_name: "normalize".to_owned(),
                source_start_line: 1,
                role: RegisteredDefinitionRole::Compute,
                atomic_symbol: None,
            })
            .collect(),
        definition_name_bindings: Vec::new(),
        builtin_name_bindings: Vec::new(),
        entry_definition_id: 0,
    })
    .expect_err("an in-place reload must not associate two identities with one frozen AST");

    assert!(
        error
            .to_string()
            .contains("refer to the same source definition at /project/reloaded.py:1:1"),
        "{error}"
    );
}
