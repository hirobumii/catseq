use std::collections::BTreeMap;
use std::sync::Arc;

use catseq_core::control::{ControlNode, OriginRole};
use catseq_frontend::{
    CallArgumentOrigin, DefinitionNameBindingInput, DefinitionRegistrationInput, DependencyRole,
    DurationUnit, FrontendElaborationErrorCode, FrontendMorphismNode, FrontendProgram,
    FrontendValueKind, ModuleRegistrationInput, MorphismComposition, ParameterAuthority,
    RegisteredDefinitionRole, RegisteredKernelModules, RegisteredRequestResolver,
    RegistrationInput, RequestResolutionError, ResolvedCallTarget, ResolvedExternalRead,
    SourceBinding, SourceHirKind, SourceIntrinsic, SourceLiteral, SourceValueOperation,
    TopologyEffect, ValueAvailability, ValueType, analyze_registered_entry,
    elaborate_frontend_program, register_kernel_modules,
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
                atomic_symbol: matches!(
                    definition.role,
                    RegisteredDefinitionRole::Atomic | RegisteredDefinitionRole::Intrinsic
                )
                .then(|| format!("test::{}", definition.qualified_name)),
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

struct InMemoryResolver {
    reads: BTreeMap<String, Result<ResolvedExternalRead, RequestResolutionError>>,
    callables: BTreeMap<String, SourceBinding>,
    queried_reads: Vec<String>,
    entry_definition_id: usize,
}

impl Default for InMemoryResolver {
    fn default() -> Self {
        Self {
            reads: BTreeMap::new(),
            callables: BTreeMap::new(),
            queried_reads: Vec::new(),
            entry_definition_id: 12,
        }
    }
}

impl InMemoryResolver {
    fn with_entry_definition_id(mut self, definition_id: usize) -> Self {
        self.entry_definition_id = definition_id;
        self
    }

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
        Ok(definition_id == self.entry_definition_id)
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

    fn resolve_duration_unit(
        &mut self,
        _definition_id: usize,
        path: &str,
        _anchor: &catseq_frontend::SourceAnchor,
    ) -> Result<DurationUnit, RequestResolutionError> {
        match path {
            "s" => Ok(DurationUnit::Second),
            "ms" => Ok(DurationUnit::Millisecond),
            "us" => Ok(DurationUnit::Microsecond),
            "ns" => Ok(DurationUnit::Nanosecond),
            _ => Err(RequestResolutionError::new(format!(
                "physical Duration unit `{path}` is not exact"
            ))),
        }
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

fn elaborate_closed_entry(source: &str, source_start_line: usize) -> FrontendProgram {
    elaborate_closed_definition(source, source_start_line, 12, "Experiment.build_sequence")
}

fn elaborate_closed_definition(
    source: &str,
    source_start_line: usize,
    definition_id: usize,
    qualified_name: &'static str,
) -> FrontendProgram {
    let registered = register_fixture(
        source,
        &[DefinitionSpec {
            id: definition_id,
            qualified_name,
            source_start_line,
            role: RegisteredDefinitionRole::Kernel,
        }],
        &[],
        definition_id,
    );
    let analysis = analyze_registered_entry(
        &registered,
        &mut InMemoryResolver::default().with_entry_definition_id(definition_id),
    )
    .expect("the closed source should type-check");
    elaborate_frontend_program(analysis.report()).expect("the closed source should elaborate")
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

    let program = elaborate_frontend_program(report)
        .expect("the pure Morphism Definition should inline during elaboration");
    assert_eq!(program.summaries().temporal().exact_cycle_delta(), Some(19));
    assert_eq!(program.summaries().topology().morphism_island_count(), 1);
}

#[test]
fn inlined_value_operations_use_argument_availability() {
    let source = concat!(
        "@morphism\n",
        "def pulse(width: int, count: int) -> Morphism:\n",
        "    return Wait(width * us) >> Wait(cycles(count))\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        width = params[self.width]\n",
        "        count = params[self.count]\n",
        "        return pulse(width, count)\n",
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
    let mut resolver = InMemoryResolver::default();
    resolver.reads.insert(
        "width".to_owned(),
        Ok(ResolvedExternalRead {
            id: 0,
            name: "width".to_owned(),
            value_type: ValueType::Int32,
            availability: ValueAvailability::Link,
            value: SourceLiteral::Int32(2),
        }),
    );
    resolver.reads.insert(
        "count".to_owned(),
        Ok(ResolvedExternalRead {
            id: 1,
            name: "count".to_owned(),
            value_type: ValueType::Int32,
            availability: ValueAvailability::Link,
            value: SourceLiteral::Int32(3),
        }),
    );
    let analysis = analyze_registered_entry(&registered, &mut resolver).unwrap();

    let program = elaborate_frontend_program(analysis.report()).unwrap();

    assert_eq!(program.values().nodes().len(), 4);
    assert!(program.values().nodes().iter().any(|node| {
        matches!(
            node.kind(),
            FrontendValueKind::ScaleDuration(DurationUnit::Microsecond)
        )
    }));
    assert!(
        program
            .values()
            .nodes()
            .iter()
            .any(|node| { matches!(node.kind(), FrontendValueKind::Cycles) })
    );
    assert!(
        program
            .values()
            .nodes()
            .iter()
            .all(|node| node.availability() == ValueAvailability::Link)
    );
    assert_eq!(program.summaries().values().compile_count(), 0);
    assert_eq!(program.summaries().values().link_count(), 4);
}

#[test]
fn retains_exact_si_duration_scale_in_typed_hir() {
    let source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return Wait(2 * us)\n",
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

    let analysis = analyze_registered_entry(&registered, &mut InMemoryResolver::default())
        .expect("an exact SI-unit Duration should analyze");
    let hir = analysis.report().definitions()[0].hir();
    let (scale_id, scale) = hir
        .nodes()
        .iter()
        .enumerate()
        .find(|(_, node)| node.value_operation() == Some(SourceValueOperation::ScaleDuration))
        .expect("the HIR should retain physical Duration scaling");
    let [scalar_id, unit_id] = hir.edges()
        [scale.edge_start() as usize..(scale.edge_start() + scale.edge_count()) as usize]
    else {
        panic!("physical Duration scaling should have scalar and unit inputs")
    };

    assert_eq!(scale.kind(), SourceHirKind::Binary);
    assert_eq!(scale.anchor().file_name(), "/project/experiment.py");
    assert_eq!(scale.anchor().line(), 4);
    assert_eq!(
        hir.nodes()[scalar_id as usize].literal(),
        Some(&SourceLiteral::Int32(2))
    );
    assert_eq!(
        hir.facts()[scalar_id as usize].value_type(),
        Some(&ValueType::Int32)
    );
    assert_eq!(hir.nodes()[unit_id as usize].symbol(), Some("us"));
    assert_eq!(
        hir.facts()[unit_id as usize].source_binding(),
        Some(&SourceBinding::DurationUnit(DurationUnit::Microsecond))
    );
    assert_eq!(hir.nodes()[unit_id as usize].anchor().line(), 4);
    assert_eq!(
        hir.facts()[scale_id].value_type(),
        Some(&ValueType::Duration)
    );
    assert_eq!(
        hir.facts()[scale_id].availability(),
        ValueAvailability::Compile
    );
    assert_eq!(
        hir.facts()[scale_id].topology_effect(),
        TopologyEffect::Empty
    );
    assert_eq!(hir.facts()[scale_id].roles(), [DependencyRole::Relocatable]);

    let program = elaborate_frontend_program(analysis.report())
        .expect("physical Duration should remain target-independent during elaboration");
    let FrontendMorphismNode::Wait(duration) = program
        .morphisms()
        .node(program.morphisms().root())
        .unwrap()
    else {
        panic!("nonzero physical Duration should remain a Wait")
    };
    assert_eq!(
        program.values().node(*duration).unwrap().kind(),
        &FrontendValueKind::ScaleDuration(DurationUnit::Microsecond)
    );
    assert_eq!(program.summaries().temporal().exact_cycle_delta(), None);
}

#[test]
fn elaborates_the_loop_free_entry_into_one_frontend_program() {
    let source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        width = params[self.width]\n",
        "        first = Wait(cycles(width))\n",
        "        return Id() >> first >> Wait(cycles(2))\n",
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
    let mut resolver = InMemoryResolver::default().with_int32_read("width", 3, 4);
    let analysis = analyze_registered_entry(&registered, &mut resolver).unwrap();

    let program = elaborate_frontend_program(analysis.report()).unwrap();

    assert_eq!(program.values().nodes().len(), 4);
    assert_eq!(program.morphisms().nodes().len(), 3);
    let root = program.morphisms().root();
    let FrontendMorphismNode::Serial {
        edge_start,
        edge_count,
    } = program.morphisms().node(root).unwrap()
    else {
        panic!("the Id unit should disappear from one flat Serial Morphism")
    };
    let children = program.morphisms().children(root).unwrap();
    assert_eq!((*edge_start, *edge_count), (0, 2));
    assert_eq!(program.morphisms().edges(), children);
    assert_eq!(children.len(), 2);
    let cycle_deltas = children
        .iter()
        .map(|child| match program.morphisms().node(*child).unwrap() {
            FrontendMorphismNode::Wait(duration) => program.values().exact_cycle_delta(*duration),
            node => panic!("expected Wait child, found {node:?}"),
        })
        .collect::<Vec<_>>();
    assert_eq!(cycle_deltas, [Some(4), Some(2)]);

    let control = program.control();
    assert_eq!(control.nodes().len(), 1);
    assert_eq!(
        control.node(control.root()),
        &ControlNode::Lift(program.morphisms().root())
    );

    assert_eq!(program.summaries().temporal().exact_cycle_delta(), Some(6));
    assert_eq!(program.summaries().values().node_count(), 4);
    assert_eq!(program.summaries().values().compile_count(), 4);
    assert_eq!(program.summaries().values().structural_count(), 0);
    assert_eq!(program.summaries().values().relocatable_count(), 4);
    assert_eq!(program.summaries().logical_resources().resource_count(), 0);
    assert_eq!(program.summaries().topology().morphism_node_count(), 3);
    assert_eq!(program.summaries().topology().morphism_island_count(), 1);
    assert!(program.summaries().completion().has_normal_exit());
    assert!(!program.summaries().failure().has_failure_exit());

    let roles = program
        .origins()
        .contributions()
        .map(|contribution| contribution.role)
        .collect::<Vec<_>>();
    for required in [
        OriginRole::Entry,
        OriginRole::Assignment,
        OriginRole::Call,
        OriginRole::Return,
        OriginRole::SerialOperator,
    ] {
        assert!(roles.contains(&required), "missing {required:?} origin");
    }
    assert!(!program.origins().morphism_boundary(root, 0).is_empty());
}

#[test]
fn request_local_external_ids_do_not_affect_program_equality() {
    let direct_source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        width = params[self.width]\n",
        "        return Wait(cycles(width))\n",
    );
    let direct_registered = register_fixture(
        direct_source,
        &[DefinitionSpec {
            id: 12,
            qualified_name: "Experiment.build_sequence",
            source_start_line: 2,
            role: RegisteredDefinitionRole::Kernel,
        }],
        &[],
        12,
    );
    let direct_analysis = analyze_registered_entry(
        &direct_registered,
        &mut InMemoryResolver::default().with_int32_read("width", 0, 4),
    )
    .unwrap();
    let direct = elaborate_frontend_program(direct_analysis.report()).unwrap();

    let prefixed_source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        ignored = params[self.ignored]\n",
        "        width = params[self.width]\n",
        "        return Wait(cycles(width))\n",
    );
    let prefixed_registered = register_fixture(
        prefixed_source,
        &[DefinitionSpec {
            id: 12,
            qualified_name: "Experiment.build_sequence",
            source_start_line: 2,
            role: RegisteredDefinitionRole::Kernel,
        }],
        &[],
        12,
    );
    let prefixed_analysis = analyze_registered_entry(
        &prefixed_registered,
        &mut InMemoryResolver::default()
            .with_int32_read("ignored", 0, 99)
            .with_int32_read("width", 1, 4),
    )
    .unwrap();
    let prefixed = elaborate_frontend_program(prefixed_analysis.report()).unwrap();

    assert_eq!(direct, prefixed);
}

#[test]
fn normalizes_serial_association_and_id_without_losing_origins() {
    let left_associated = elaborate_closed_entry(
        concat!(
            "class Experiment:\n",
            "    @kernel\n",
            "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
            "        return (Wait(cycles(1)) >> Id()) >> Wait(cycles(2))\n",
        ),
        2,
    );
    let right_associated = elaborate_closed_definition(
        concat!(
            "# the same program starts one line later\n",
            "class OtherExperiment:\n",
            "    @kernel\n",
            "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
            "        return Wait(cycles(1)) >> (Id() >> Wait(cycles(2)))\n",
        ),
        3,
        99,
        "OtherExperiment.build_sequence",
    );

    assert_eq!(left_associated, right_associated);
    assert_ne!(
        left_associated.entry_definition_id(),
        right_associated.entry_definition_id()
    );
    assert_ne!(left_associated.entry(), right_associated.entry());
    assert_eq!(left_associated.morphisms().nodes().len(), 3);
    assert_ne!(
        left_associated
            .origins()
            .anchor(left_associated.origins().entry()[0].origin)
            .unwrap()
            .line(),
        right_associated
            .origins()
            .anchor(right_associated.origins().entry()[0].origin)
            .unwrap()
            .line()
    );
    for program in [&left_associated, &right_associated] {
        assert!(
            program
                .origins()
                .contributions()
                .any(|origin| origin.role == OriginRole::SerialOperator)
        );
    }
}

#[test]
fn normalizes_proven_zero_waits_to_the_same_id_program() {
    let id = elaborate_closed_entry(
        concat!(
            "class Experiment:\n",
            "    @kernel\n",
            "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
            "        return Id()\n",
        ),
        2,
    );
    let zero_cycles = elaborate_closed_entry(
        concat!(
            "# shifted origin\n",
            "class Experiment:\n",
            "    @kernel\n",
            "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
            "        return Wait(cycles(0))\n",
        ),
        3,
    );
    let zero_si_duration = elaborate_closed_entry(
        concat!(
            "class Experiment:\n",
            "    @kernel\n",
            "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
            "        return Wait(0 * us)\n",
        ),
        2,
    );

    assert_eq!(id, zero_cycles);
    assert_eq!(id, zero_si_duration);
    assert!(id.values().nodes().is_empty());
    assert_eq!(id.morphisms().nodes(), [FrontendMorphismNode::Id]);
    assert!(matches!(
        id.control().node(id.control().root()),
        ControlNode::Return(_)
    ));
}

#[test]
fn rejects_a_discarded_morphism_expression_statement_at_its_source() {
    let source = concat!(
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        Wait(cycles(1))\n",
        "        return Id()\n",
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
    let analysis = analyze_registered_entry(&registered, &mut InMemoryResolver::default())
        .expect("typed source should retain the discarded Morphism for elaboration");

    let error = elaborate_frontend_program(analysis.report())
        .expect_err("discarding a Morphism must not become an empty program");

    assert_eq!(
        error.code(),
        FrontendElaborationErrorCode::DiscardedMorphism
    );
    assert_eq!(error.primary_anchor().unwrap().line(), 4);
}

#[test]
fn rejects_a_morphism_argument_discarded_by_its_definition() {
    let source = concat!(
        "@morphism\n",
        "def drop_morphism(value: Morphism) -> Morphism:\n",
        "    return Id()\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return drop_morphism(Wait(cycles(1)))\n",
    );
    let registered = register_fixture(
        source,
        &[
            DefinitionSpec {
                id: 11,
                qualified_name: "drop_morphism",
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
        &[("drop_morphism", 11)],
        12,
    );
    let analysis = analyze_registered_entry(&registered, &mut InMemoryResolver::default())
        .expect("the Morphism Definition call should type-check");

    let error = elaborate_frontend_program(analysis.report())
        .expect_err("a Morphism argument must contribute to the returned Morphism");

    assert_eq!(
        error.code(),
        FrontendElaborationErrorCode::DiscardedMorphism
    );
    assert!(error.message().contains("argument `value`"), "{error}");
    assert_eq!(error.primary_anchor().unwrap().line(), 8);
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
fn rejects_bodyless_atomic_at_its_call_site() {
    let source = concat!(
        "@atomic_morphism\n",
        "def pulse() -> Morphism:\n",
        "    return Id()\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return pulse()\n",
    );
    let registered = register_fixture(
        source,
        &[
            DefinitionSpec {
                id: 11,
                qualified_name: "pulse",
                source_start_line: 1,
                role: RegisteredDefinitionRole::Atomic,
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
    let analysis = analyze_registered_entry(&registered, &mut InMemoryResolver::default())
        .expect("registered Atomic helpers retain a body-less typed definition");

    let error = elaborate_frontend_program(analysis.report())
        .expect_err("Atomic lowering is outside the initial frontend tracer");

    assert_eq!(
        error.code(),
        FrontendElaborationErrorCode::UnsupportedSource
    );
    assert_eq!(
        error.message(),
        "atomic calls are outside the initial frontend tracer"
    );
    assert_eq!(error.primary_anchor().unwrap().line(), 8);
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
fn elaborates_optional_compatible_helper_arguments() {
    let source = concat!(
        "@morphism\n",
        "def consume(value: int | None) -> Morphism:\n",
        "    return Id()\n",
        "\n",
        "@morphism\n",
        "def forward(value: int | None = None) -> Morphism:\n",
        "    return consume(value)\n",
        "\n",
        "class Experiment:\n",
        "    @kernel\n",
        "    def build_sequence(self, params: ExpParams) -> Morphism:\n",
        "        return forward(1) >> forward()\n",
    );
    let registered = register_fixture(
        source,
        &[
            DefinitionSpec {
                id: 10,
                qualified_name: "consume",
                source_start_line: 1,
                role: RegisteredDefinitionRole::MorphismDefinition,
            },
            DefinitionSpec {
                id: 11,
                qualified_name: "forward",
                source_start_line: 5,
                role: RegisteredDefinitionRole::MorphismDefinition,
            },
            DefinitionSpec {
                id: 12,
                qualified_name: "Experiment.build_sequence",
                source_start_line: 10,
                role: RegisteredDefinitionRole::Kernel,
            },
        ],
        &[("consume", 10), ("forward", 11)],
        12,
    );
    let analysis = analyze_registered_entry(&registered, &mut InMemoryResolver::default())
        .expect("Optional-compatible helper calls should type-check");

    let program = elaborate_frontend_program(analysis.report())
        .expect("elaboration should preserve the typed Optional compatibility rule");

    assert!(program.values().nodes().is_empty());
    assert_eq!(program.morphisms().nodes(), [FrontendMorphismNode::Id]);
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
