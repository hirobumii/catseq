use std::collections::BTreeMap;
use std::sync::Arc;

use catseq_frontend::{
    CallArgumentOrigin, DefinitionNameBindingInput, DefinitionRegistrationInput, DependencyRole,
    ModuleRegistrationInput, MorphismComposition, ParameterAuthority, RegisteredDefinitionRole,
    RegisteredKernelModules, RegisteredRequestResolver, RegistrationInput, RequestResolutionError,
    ResolvedCallTarget, ResolvedExternalRead, SourceBinding, SourceHirKind, SourceIntrinsic,
    SourceLiteral, TopologyEffect, ValueAvailability, ValueType, analyze_registered_entry,
    register_kernel_modules,
};

const MODULE_ID: usize = 7;
const MODULE_NAME: &str = "experiment";
const FILE_NAME: &str = "/project/experiment.py";

#[derive(Clone, Copy)]
struct DefinitionSpec {
    id: usize,
    qualified_name: &'static str,
    source_start_line: usize,
    role: RegisteredDefinitionRole,
}

fn register_fixture(
    source: &str,
    definitions: &[DefinitionSpec],
    bindings: &[(&str, usize)],
    entry_definition_id: usize,
) -> RegisteredKernelModules {
    register_kernel_modules(RegistrationInput {
        modules: vec![ModuleRegistrationInput {
            id: MODULE_ID,
            import_name: MODULE_NAME.to_owned(),
            file_name: FILE_NAME.to_owned(),
            source: Arc::from(source),
        }],
        definitions: definitions
            .iter()
            .map(|definition| DefinitionRegistrationInput {
                id: definition.id,
                module_id: MODULE_ID,
                qualified_name: definition.qualified_name.to_owned(),
                source_start_line: definition.source_start_line,
                role: definition.role,
                atomic_symbol: None,
            })
            .collect(),
        definition_name_bindings: bindings
            .iter()
            .map(|(name, definition_id)| DefinitionNameBindingInput {
                module_id: MODULE_ID,
                name: (*name).to_owned(),
                definition_id: *definition_id,
            })
            .collect(),
        builtin_name_bindings: Vec::new(),
        entry_definition_id,
    })
    .expect("analysis fixture must register")
}

#[derive(Default)]
struct InMemoryResolver {
    reads: BTreeMap<String, Result<ResolvedExternalRead, RequestResolutionError>>,
    callables: BTreeMap<String, SourceBinding>,
    queried_reads: Vec<String>,
}

impl InMemoryResolver {
    fn with_int32_read(mut self, attribute: &str, id: u32, value: i32) -> Self {
        self.reads.insert(
            attribute.to_owned(),
            Ok(ResolvedExternalRead {
                id,
                name: attribute.to_owned(),
                value_type: ValueType::Int32,
                availability: ValueAvailability::Compile,
                value: SourceLiteral::Int32(value),
            }),
        );
        self
    }

    fn with_host_rpc(mut self, path: &str) -> Self {
        self.callables.insert(
            path.to_owned(),
            SourceBinding::HostRpc {
                display_name: path.to_owned(),
            },
        );
        self
    }
}

impl RegisteredRequestResolver for InMemoryResolver {
    fn is_entry_owner_method(
        &mut self,
        definition_id: usize,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<bool, RequestResolutionError> {
        Ok(definition_id == 12)
    }

    fn resolve_annotation_binding(
        &mut self,
        _definition_id: usize,
        path: &str,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<SourceBinding, RequestResolutionError> {
        match path {
            "int" => Ok(SourceBinding::ValueType(ValueType::Int32)),
            "bool" => Ok(SourceBinding::ValueType(ValueType::Bool)),
            "float" => Ok(SourceBinding::ValueType(ValueType::Float64)),
            "ExpParams" => Ok(SourceBinding::ExpParams),
            "Morphism" => Ok(SourceBinding::ValueType(ValueType::Morphism)),
            _ => Err(RequestResolutionError::new(format!(
                "unsupported annotation `{path}`"
            ))),
        }
    }

    fn resolve_callable_binding(
        &mut self,
        _definition_id: usize,
        path: &str,
        _bound_entry_owner: bool,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<SourceBinding, RequestResolutionError> {
        if let Some(callable) = self.callables.get(path) {
            return Ok(callable.clone());
        }
        Ok(match path {
            "cycles" => SourceBinding::Intrinsic(SourceIntrinsic::Cycles),
            "Id" => SourceBinding::Intrinsic(SourceIntrinsic::Id),
            "Wait" => SourceBinding::Intrinsic(SourceIntrinsic::Wait),
            _ => SourceBinding::Unsupported {
                display_name: path.to_owned(),
            },
        })
    }

    fn resolve_exp_param(
        &mut self,
        _definition_id: usize,
        owner_attribute: &str,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<ResolvedExternalRead, RequestResolutionError> {
        self.queried_reads.push(owner_attribute.to_owned());
        self.reads.get(owner_attribute).cloned().unwrap_or_else(|| {
            Err(RequestResolutionError::new(format!(
                "missing ExpParam `{owner_attribute}`"
            )))
        })
    }
}

#[test]
fn analyzes_exact_loop_free_entry_reachability_hir_and_read_edges() {
    let source = concat!(
        "@morphism\n",
        "def pulse(width: int) -> Morphism:\n",
        "    return Id() >> Wait(cycles(width)) >> Wait(cycles(2))\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        width = params[self.width]\n",
        "        return pulse(width)\n",
    );
    let registered = register_fixture(
        source,
        &[
            DefinitionSpec {
                id: 11,
                qualified_name: "pulse",
                source_start_line: 1,
                role: RegisteredDefinitionRole::MorphismDefinition,
            },
            DefinitionSpec {
                id: 12,
                qualified_name: "Experiment.build_sequence",
                source_start_line: 6,
                role: RegisteredDefinitionRole::Kernel,
            },
        ],
        &[("pulse", 11)],
        12,
    );
    let mut resolver = InMemoryResolver::default().with_int32_read("width", 3, 17);

    let analysis = analyze_registered_entry(&registered, &mut resolver)
        .expect("the exact loop-free tracer should analyze");
    let report = analysis.report();

    assert_eq!(report.entry_definition_id(), 12);
    assert_eq!(report.entry(), "experiment.Experiment.build_sequence");
    assert_eq!(
        report
            .definitions()
            .iter()
            .map(|definition| definition.definition_id())
            .collect::<Vec<_>>(),
        vec![12, 11]
    );
    assert_eq!(report.call_edges().len(), 1);
    assert_eq!(report.call_edges()[0].caller_definition_id(), 12);
    assert_eq!(report.call_edges()[0].callee_definition_id(), 11);
    assert_eq!(
        report.call_edges()[0].callee_role(),
        RegisteredDefinitionRole::MorphismDefinition
    );
    assert_eq!(report.external_reads().len(), 1);
    assert_eq!(report.external_reads()[0].id(), 3);
    assert_eq!(report.external_reads()[0].name(), "width");
    assert_eq!(
        report.external_reads()[0].value(),
        &SourceLiteral::Int32(17)
    );
    assert_eq!(resolver.queried_reads, ["width"]);

    let entry = report
        .definitions()
        .iter()
        .find(|definition| definition.definition_id() == 12)
        .expect("entry remains in the report");
    assert_eq!(
        entry.signature().parameters()[0].authority(),
        Some(&ParameterAuthority::EntryOwner)
    );
    assert_eq!(
        entry.signature().parameters()[1].authority(),
        Some(&ParameterAuthority::ExpParams)
    );
    assert_eq!(entry.signature().parameters()[0].value_type(), None);
    assert_eq!(entry.signature().parameters()[1].value_type(), None);
    assert_eq!(entry.signature().return_type(), &ValueType::Morphism);
    assert!(
        entry
            .hir()
            .nodes()
            .iter()
            .enumerate()
            .any(|(node_id, node)| {
                node.symbol() == Some("params")
                    && entry.hir().facts()[node_id].value_type().is_none()
                    && entry.hir().facts()[node_id].source_binding()
                        == Some(&SourceBinding::ExpParams)
            })
    );
    assert!(
        entry
            .hir()
            .nodes()
            .iter()
            .enumerate()
            .any(|(node_id, node)| {
                node.symbol() == Some("self.width")
                    && entry.hir().facts()[node_id].value_type().is_none()
                    && entry.hir().facts()[node_id].source_binding()
                        == Some(&SourceBinding::ExpParam {
                            id: 3,
                            name: "width".to_owned(),
                            value_type: ValueType::Int32,
                        })
            })
    );
    assert!(
        entry
            .hir()
            .nodes()
            .iter()
            .enumerate()
            .any(|(node_id, node)| {
                node.symbol() == Some("pulse")
                    && entry.hir().facts()[node_id].value_type().is_none()
                    && entry.hir().facts()[node_id].source_binding()
                        == Some(&SourceBinding::Definition {
                            definition_id: 11,
                            role: RegisteredDefinitionRole::MorphismDefinition,
                        })
            })
    );
    assert!(
        entry
            .hir()
            .nodes()
            .iter()
            .enumerate()
            .any(|(node_id, node)| {
                node.kind() == SourceHirKind::Subscript
                    && entry.hir().facts()[node_id].external_read_id() == Some(3)
                    && entry.hir().facts()[node_id].value_type() == Some(&ValueType::Int32)
                    && entry.hir().facts()[node_id].availability() == ValueAvailability::Compile
                    && entry.hir().facts()[node_id].roles() == [DependencyRole::Relocatable]
            })
    );

    let helper = report
        .definitions()
        .iter()
        .find(|definition| definition.definition_id() == 11)
        .expect("reachable helper remains in the report");
    assert_eq!(
        helper.signature().parameters()[0].value_type(),
        Some(&ValueType::Int32)
    );
    assert_eq!(helper.signature().parameters()[0].authority(), None);
    let morphism_intrinsics = helper
        .hir()
        .facts()
        .iter()
        .filter_map(|fact| match fact.resolved_call() {
            Some(ResolvedCallTarget::Intrinsic(SourceIntrinsic::Id)) => {
                Some((SourceIntrinsic::Id, fact.call_arguments()))
            }
            Some(ResolvedCallTarget::Intrinsic(SourceIntrinsic::Wait)) => {
                Some((SourceIntrinsic::Wait, fact.call_arguments()))
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(
        morphism_intrinsics
            .iter()
            .map(|(intrinsic, _)| *intrinsic)
            .collect::<Vec<_>>(),
        vec![
            SourceIntrinsic::Id,
            SourceIntrinsic::Wait,
            SourceIntrinsic::Wait
        ]
    );
    assert!(morphism_intrinsics[0].1.is_empty());
    assert!(morphism_intrinsics[1..].iter().all(|(_, arguments)| {
        arguments.len() == 1
            && arguments[0].parameter() == "duration"
            && helper.hir().facts()[arguments[0].value_node() as usize].value_type()
                == Some(&ValueType::Duration)
    }));
    assert!(
        helper
            .hir()
            .nodes()
            .iter()
            .enumerate()
            .any(|(node_id, node)| {
                node.kind() == SourceHirKind::Binary
                    && node.morphism_composition() == Some(MorphismComposition::AutoSerial)
                    && helper.hir().facts()[node_id].value_type() == Some(&ValueType::Morphism)
                    && helper.hir().facts()[node_id].topology_effect() == TopologyEffect::Morphism
                    && helper.hir().facts()[node_id]
                        .roles()
                        .contains(&DependencyRole::Structural)
            })
    );
}

#[test]
fn rejects_unitless_wait_zero() {
    let source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return Wait(0)\n",
    );
    let registered = register_fixture(
        source,
        &[DefinitionSpec {
            id: 12,
            qualified_name: "Experiment.build_sequence",
            source_start_line: 2,
            role: RegisteredDefinitionRole::Kernel,
        }],
        &[],
        12,
    );

    let error = analyze_registered_entry(&registered, &mut InMemoryResolver::default())
        .err()
        .expect("Wait requires an actual Duration even when its value is zero");

    assert!(
        error
            .to_string()
            .contains("value type mismatch: expected duration, found i32"),
        "{error}"
    );
    assert!(
        error.to_string().contains("/project/experiment.py:4:"),
        "{error}"
    );
}

#[test]
fn ignores_unreachable_registered_definition_with_unsupported_syntax() {
    let source = concat!(
        "@morphism\n",
        "def pulse(width: int) -> Morphism:\n",
        "    return Wait(cycles(width))\n",
        "\n",
        "@kernel\n",
        "def unused(flag: bool) -> Morphism:\n",
        "    if flag:\n",
        "        return Wait(cycles(1))\n",
        "    return Id()\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return pulse(4)\n",
    );
    let registered = register_fixture(
        source,
        &[
            DefinitionSpec {
                id: 10,
                qualified_name: "pulse",
                source_start_line: 1,
                role: RegisteredDefinitionRole::MorphismDefinition,
            },
            DefinitionSpec {
                id: 11,
                qualified_name: "unused",
                source_start_line: 5,
                role: RegisteredDefinitionRole::Kernel,
            },
            DefinitionSpec {
                id: 12,
                qualified_name: "Experiment.build_sequence",
                source_start_line: 12,
                role: RegisteredDefinitionRole::Kernel,
            },
        ],
        &[("pulse", 10), ("unused", 11)],
        12,
    );
    let mut resolver = InMemoryResolver::default();

    let analysis = analyze_registered_entry(&registered, &mut resolver)
        .expect("an unreachable invalid definition has no semantic effect");

    assert_eq!(
        analysis
            .report()
            .definitions()
            .iter()
            .map(|definition| definition.definition_id())
            .collect::<Vec<_>>(),
        vec![12, 10]
    );
}

#[test]
fn rejects_reachable_if_at_its_source_location() {
    let source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        if False:\n",
        "            return Id()\n",
        "        return Wait(cycles(1))\n",
    );
    let registered = register_fixture(
        source,
        &[DefinitionSpec {
            id: 12,
            qualified_name: "Experiment.build_sequence",
            source_start_line: 2,
            role: RegisteredDefinitionRole::Kernel,
        }],
        &[],
        12,
    );
    let mut resolver = InMemoryResolver::default();

    let error = analyze_registered_entry(&registered, &mut resolver)
        .err()
        .expect("reachable Python control flow is not in the initial source subset");

    assert!(
        error.to_string().contains(
            "unsupported statement in the initial loop-free Kernel/Morphism source subset"
        ),
        "{error}"
    );
    assert!(
        error.to_string().contains("/project/experiment.py:4:9"),
        "{error}"
    );
}

#[test]
fn rejects_direct_ordinary_host_rpc_at_the_call_site() {
    let source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return host_helper(1)\n",
    );
    let registered = register_fixture(
        source,
        &[DefinitionSpec {
            id: 12,
            qualified_name: "Experiment.build_sequence",
            source_start_line: 2,
            role: RegisteredDefinitionRole::Kernel,
        }],
        &[],
        12,
    );
    let mut resolver = InMemoryResolver::default().with_host_rpc("host_helper");

    let error = analyze_registered_entry(&registered, &mut resolver)
        .err()
        .expect("Host RPC is recognized but not implemented by #52");

    assert!(
        error
            .to_string()
            .contains("unimplemented: host RPC calls are not implemented (host_helper)"),
        "{error}"
    );
    assert!(
        error.to_string().contains("/project/experiment.py:4:"),
        "{error}"
    );
}

#[test]
fn rejects_direct_kernel_recursion_at_the_recursive_call() {
    let source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return self.build_sequence(params)\n",
    );
    let registered = register_fixture(
        source,
        &[DefinitionSpec {
            id: 12,
            qualified_name: "Experiment.build_sequence",
            source_start_line: 2,
            role: RegisteredDefinitionRole::Kernel,
        }],
        &[("self.build_sequence", 12)],
        12,
    );
    let mut resolver = InMemoryResolver::default();

    let error = analyze_registered_entry(&registered, &mut resolver)
        .err()
        .expect("direct reachable Kernel recursion is unsupported");

    assert!(
        error
            .to_string()
            .contains("recursive Kernel/Morphism calls are unsupported"),
        "{error}"
    );
    assert!(
        error.to_string().contains("/project/experiment.py:4:"),
        "{error}"
    );
}

#[test]
fn rejects_mutual_kernel_recursion_at_the_back_edge() {
    let source = concat!(
        "@kernel\n",
        "def first(value: int) -> Morphism:\n",
        "    return second(value)\n",
        "\n",
        "@kernel\n",
        "def second(value: int) -> Morphism:\n",
        "    return first(value)\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return first(1)\n",
    );
    let registered = register_fixture(
        source,
        &[
            DefinitionSpec {
                id: 10,
                qualified_name: "first",
                source_start_line: 1,
                role: RegisteredDefinitionRole::Kernel,
            },
            DefinitionSpec {
                id: 11,
                qualified_name: "second",
                source_start_line: 5,
                role: RegisteredDefinitionRole::Kernel,
            },
            DefinitionSpec {
                id: 12,
                qualified_name: "Experiment.build_sequence",
                source_start_line: 10,
                role: RegisteredDefinitionRole::Kernel,
            },
        ],
        &[("first", 10), ("second", 11)],
        12,
    );
    let mut resolver = InMemoryResolver::default();

    let error = analyze_registered_entry(&registered, &mut resolver)
        .err()
        .expect("mutual reachable Kernel recursion is unsupported");

    assert!(
        error
            .to_string()
            .contains("recursive Kernel/Morphism calls are unsupported"),
        "{error}"
    );
    assert!(
        error.to_string().contains("/project/experiment.py:7:"),
        "{error}"
    );
}

#[test]
fn rejects_a_referenced_missing_exp_param_at_the_read() {
    let source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        width = params[self.width]\n",
        "        return Wait(cycles(width))\n",
    );
    let registered = register_fixture(
        source,
        &[DefinitionSpec {
            id: 12,
            qualified_name: "Experiment.build_sequence",
            source_start_line: 2,
            role: RegisteredDefinitionRole::Kernel,
        }],
        &[],
        12,
    );
    let mut resolver = InMemoryResolver::default();

    let error = analyze_registered_entry(&registered, &mut resolver)
        .err()
        .expect("a referenced missing ExpParam must fail closed");

    assert!(
        error.to_string().contains("missing ExpParam `width`"),
        "{error}"
    );
    assert!(
        error.to_string().contains("/project/experiment.py:4:"),
        "{error}"
    );
    assert_eq!(resolver.queried_reads, ["width"]);
}

#[test]
fn rejects_a_referenced_exp_param_with_an_unsupported_source_type() {
    let source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        width = params[self.width]\n",
        "        return Wait(cycles(width))\n",
    );
    let registered = register_fixture(
        source,
        &[DefinitionSpec {
            id: 12,
            qualified_name: "Experiment.build_sequence",
            source_start_line: 2,
            role: RegisteredDefinitionRole::Kernel,
        }],
        &[],
        12,
    );
    let mut resolver = InMemoryResolver::default();
    resolver.reads.insert(
        "width".to_owned(),
        Ok(ResolvedExternalRead {
            id: 3,
            name: "width".to_owned(),
            value_type: ValueType::Duration,
            availability: ValueAvailability::Compile,
            value: SourceLiteral::Int32(17),
        }),
    );

    let error = analyze_registered_entry(&registered, &mut resolver)
        .err()
        .expect("the initial tracer accepts only bool and Int32 ExpParam values");

    assert!(
        error
            .to_string()
            .contains("ExpParam `width` has unsupported type duration"),
        "{error}"
    );
    assert!(
        error.to_string().contains("/project/experiment.py:4:"),
        "{error}"
    );
    assert_eq!(resolver.queried_reads, ["width"]);
}

#[test]
fn does_not_query_bad_exp_param_read_in_an_unreachable_definition() {
    let source = concat!(
        "@kernel\n",
        "def unused(self, params: ExpParams) -> Morphism:\n",
        "    return Wait(cycles(params[self.bad]))\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        width = params[self.width]\n",
        "        return Wait(cycles(width))\n",
    );
    let registered = register_fixture(
        source,
        &[
            DefinitionSpec {
                id: 10,
                qualified_name: "unused",
                source_start_line: 1,
                role: RegisteredDefinitionRole::Kernel,
            },
            DefinitionSpec {
                id: 12,
                qualified_name: "Experiment.build_sequence",
                source_start_line: 6,
                role: RegisteredDefinitionRole::Kernel,
            },
        ],
        &[("unused", 10)],
        12,
    );
    let mut resolver = InMemoryResolver::default().with_int32_read("width", 3, 17);

    let analysis = analyze_registered_entry(&registered, &mut resolver)
        .expect("unreachable reads must not query the request resolver");

    assert_eq!(resolver.queried_reads, ["width"]);
    assert_eq!(
        analysis
            .report()
            .definitions()
            .iter()
            .map(|definition| definition.definition_id())
            .collect::<Vec<_>>(),
        vec![12]
    );
    assert_eq!(analysis.report().external_reads().len(), 1);
    assert_eq!(analysis.report().external_reads()[0].name(), "width");
}

#[test]
fn preserves_and_applies_registered_source_defaults() {
    let source = concat!(
        "@morphism\n",
        "def configured(carrier: float, enabled: bool = False, label: int = 1) -> Morphism:\n",
        "    return Wait(cycles(1))\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return configured(100e6, label=7)\n",
    );
    let registered = register_fixture(
        source,
        &[
            DefinitionSpec {
                id: 10,
                qualified_name: "configured",
                source_start_line: 1,
                role: RegisteredDefinitionRole::MorphismDefinition,
            },
            DefinitionSpec {
                id: 12,
                qualified_name: "Experiment.build_sequence",
                source_start_line: 6,
                role: RegisteredDefinitionRole::Kernel,
            },
        ],
        &[("configured", 10)],
        12,
    );

    let analysis = analyze_registered_entry(&registered, &mut InMemoryResolver::default())
        .expect("an omitted registered default must satisfy the call shape");
    let configured = analysis
        .report()
        .definitions()
        .iter()
        .find(|definition| definition.definition_id() == 10)
        .expect("the called Morphism Definition is reachable");

    assert_eq!(configured.signature().parameters().len(), 3);
    assert_eq!(
        configured.signature().parameters()[1].default(),
        Some(&SourceLiteral::Bool(false))
    );
    assert_eq!(
        configured.signature().parameters()[2].default(),
        Some(&SourceLiteral::Int32(1))
    );

    let entry = analysis
        .report()
        .definitions()
        .iter()
        .find(|definition| definition.definition_id() == 12)
        .expect("entry remains in the report");
    let call_fact = entry
        .hir()
        .facts()
        .iter()
        .find(|fact| {
            matches!(
                fact.resolved_call(),
                Some(ResolvedCallTarget::Definition {
                    definition_id: 10,
                    ..
                })
            )
        })
        .expect("the configured call remains in entry HIR");
    assert_eq!(
        call_fact
            .call_arguments()
            .iter()
            .map(|argument| (argument.parameter(), argument.origin()))
            .collect::<Vec<_>>(),
        vec![
            ("carrier", CallArgumentOrigin::Positional),
            ("enabled", CallArgumentOrigin::Default),
            ("label", CallArgumentOrigin::Keyword),
        ]
    );
    let enabled = &call_fact.call_arguments()[1];
    assert_eq!(
        entry.hir().nodes()[enabled.value_node() as usize].literal(),
        Some(&SourceLiteral::Bool(false))
    );
    assert_eq!(
        entry.hir().facts()[enabled.value_node() as usize].value_type(),
        Some(&ValueType::Bool)
    );
}
