use catseq_core::control::{
    ControlBuildError, ControlBuilder, ControlDiagnostic, ControlDiagnosticCode,
    ControlDiagnosticSubject, ControlNode, ControlResultType, ControlSummary, MorphismAlgebra,
    MorphismTerm, OriginId, SerialTerm,
};

#[derive(Clone, Debug, PartialEq, Eq)]
enum TestMorphism {
    Id,
    Atom(&'static str),
    Serial(Vec<TestMorphism>),
    Parallel(Vec<TestMorphism>),
}

#[derive(Debug, PartialEq, Eq)]
struct TestMorphismError;

#[derive(Default)]
struct TestMorphismAlgebra;

impl MorphismAlgebra<TestMorphism> for TestMorphismAlgebra {
    type Error = TestMorphismError;

    fn is_identity(&self, morphism: &TestMorphism) -> bool {
        matches!(morphism, TestMorphism::Id)
    }

    fn serial(&mut self, morphisms: Vec<TestMorphism>) -> Result<TestMorphism, Self::Error> {
        let mut flattened = Vec::new();
        for morphism in morphisms {
            match morphism {
                TestMorphism::Serial(children) => flattened.extend(children),
                morphism => flattened.push(morphism),
            }
        }
        Ok(TestMorphism::Serial(flattened))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TestValueType {
    Int,
}

#[test]
fn mixed_serial_uses_the_right_operand_result_type() {
    let mut algebra = TestMorphismAlgebra;
    let mut builder = ControlBuilder::<TestMorphism, u32, TestValueType>::new();

    let pure = builder
        .serial(
            &mut algebra,
            SerialTerm::Morphism(MorphismTerm::new(
                TestMorphism::Atom("prepare"),
                OriginId::new(1),
            )),
            SerialTerm::Morphism(MorphismTerm::new(
                TestMorphism::Atom("capture"),
                OriginId::new(2),
            )),
            OriginId::new(3),
        )
        .unwrap();
    assert!(matches!(
        pure,
        SerialTerm::Morphism(MorphismTerm {
            morphism: TestMorphism::Serial(_),
            ..
        })
    ));

    let returned = builder.return_value(7, TestValueType::Int, OriginId::new(4));
    let morphism_then_control = builder
        .serial(
            &mut algebra,
            SerialTerm::Morphism(MorphismTerm::new(
                TestMorphism::Atom("capture"),
                OriginId::new(5),
            )),
            SerialTerm::Control(returned),
            OriginId::new(6),
        )
        .unwrap();
    let SerialTerm::Control(morphism_then_control) = morphism_then_control else {
        panic!("Morphism >> Control must produce Control");
    };
    assert_eq!(
        builder.result_type(morphism_then_control),
        ControlResultType::Value(TestValueType::Int)
    );

    let returned = builder.return_value(8, TestValueType::Int, OriginId::new(7));
    let control_then_morphism = builder
        .serial(
            &mut algebra,
            SerialTerm::Control(returned),
            SerialTerm::Morphism(MorphismTerm::new(
                TestMorphism::Atom("readout"),
                OriginId::new(8),
            )),
            OriginId::new(9),
        )
        .unwrap();
    let SerialTerm::Control(control_then_morphism) = control_then_morphism else {
        panic!("Control >> Morphism must produce Control");
    };
    assert_eq!(
        builder.result_type(control_then_morphism),
        ControlResultType::Unit
    );

    let left = builder.return_unit(OriginId::new(10));
    let right = builder.return_value(9, TestValueType::Int, OriginId::new(11));
    let control_then_control = builder
        .serial(
            &mut algebra,
            SerialTerm::Control(left),
            SerialTerm::Control(right),
            OriginId::new(12),
        )
        .unwrap();
    let SerialTerm::Control(control_then_control) = control_then_control else {
        panic!("Control >> Control must produce Control");
    };
    assert_eq!(
        builder.result_type(control_then_control),
        ControlResultType::Value(TestValueType::Int)
    );
}

#[test]
fn associative_then_normalizes_to_one_maximal_morphism_island() {
    let mut algebra = TestMorphismAlgebra;

    let mut left_grouped = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let a = left_grouped.lift(MorphismTerm::new(
        TestMorphism::Atom("a"),
        OriginId::new(20),
    ));
    let b = left_grouped.lift(MorphismTerm::new(
        TestMorphism::Atom("b"),
        OriginId::new(21),
    ));
    let c = left_grouped.lift(MorphismTerm::new(
        TestMorphism::Atom("c"),
        OriginId::new(22),
    ));
    let ab = left_grouped.then(&[a, b], &[OriginId::new(23)]);
    let abc = left_grouped.then(&[ab, c], &[OriginId::new(24)]);
    let left_grouped = left_grouped.finish(abc, &mut algebra).unwrap();

    let mut right_grouped = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let a = right_grouped.lift(MorphismTerm::new(
        TestMorphism::Atom("a"),
        OriginId::new(30),
    ));
    let b = right_grouped.lift(MorphismTerm::new(
        TestMorphism::Atom("b"),
        OriginId::new(31),
    ));
    let c = right_grouped.lift(MorphismTerm::new(
        TestMorphism::Atom("c"),
        OriginId::new(32),
    ));
    let bc = right_grouped.then(&[b, c], &[OriginId::new(33)]);
    let abc = right_grouped.then(&[a, bc], &[OriginId::new(34)]);
    let right_grouped = right_grouped.finish(abc, &mut algebra).unwrap();

    assert_eq!(left_grouped, right_grouped);
    assert_eq!(left_grouped.summary(), right_grouped.summary());
    assert_eq!(
        left_grouped.summary(),
        &ControlSummary {
            result_type: ControlResultType::Unit,
            has_normal_exit: true,
            has_failure_exit: false,
            morphism_island_count: 1,
        }
    );
    assert_eq!(left_grouped.arena().nodes().len(), 1);
    assert_eq!(
        left_grouped.arena().node(left_grouped.arena().root()),
        &ControlNode::Lift(TestMorphism::Serial(vec![
            TestMorphism::Atom("a"),
            TestMorphism::Atom("b"),
            TestMorphism::Atom("c"),
        ]))
    );
    assert_eq!(
        left_grouped.origins().node(left_grouped.arena().root()),
        [
            catseq_core::control::OriginContribution {
                origin: OriginId::new(20),
                role: catseq_core::control::OriginRole::Morphism,
            },
            catseq_core::control::OriginContribution {
                origin: OriginId::new(23),
                role: catseq_core::control::OriginRole::SerialOperator,
            },
            catseq_core::control::OriginContribution {
                origin: OriginId::new(21),
                role: catseq_core::control::OriginRole::Morphism,
            },
            catseq_core::control::OriginContribution {
                origin: OriginId::new(24),
                role: catseq_core::control::OriginRole::SerialOperator,
            },
            catseq_core::control::OriginContribution {
                origin: OriginId::new(22),
                role: catseq_core::control::OriginRole::Morphism,
            },
        ]
    );

    let normalized_twice = left_grouped.renormalize(&mut algebra).unwrap();
    assert_eq!(normalized_twice, left_grouped);
    assert_eq!(normalized_twice.summary(), left_grouped.summary());
    assert_eq!(normalized_twice.origins(), left_grouped.origins());
}

#[test]
fn identity_and_degenerate_then_reduce_to_the_control_unit_or_child() {
    let mut algebra = TestMorphismAlgebra;

    let mut identity = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let root = identity.lift(MorphismTerm::new(TestMorphism::Id, OriginId::new(40)));
    let identity = identity.finish(root, &mut algebra).unwrap();
    assert_eq!(
        identity.arena().node(identity.arena().root()),
        &ControlNode::Return(catseq_core::control::ControlResult::Unit)
    );

    let mut empty = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let root = empty.then(&[], &[]);
    let empty = empty.finish(root, &mut algebra).unwrap();
    assert_eq!(
        empty.arena().node(empty.arena().root()),
        &ControlNode::Return(catseq_core::control::ControlResult::Unit)
    );

    let mut single = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let value = single.return_value(42, TestValueType::Int, OriginId::new(41));
    let root = single.then(&[value], &[]);
    let single = single.finish(root, &mut algebra).unwrap();
    assert_eq!(
        single.arena().node(single.arena().root()),
        &ControlNode::Return(catseq_core::control::ControlResult::Value {
            reference: 42,
            value_type: TestValueType::Int,
        })
    );
}

#[test]
fn then_discards_non_final_results_and_a_redundant_final_unit() {
    let mut algebra = TestMorphismAlgebra;

    let mut value_result = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let discarded = value_result.return_value(1, TestValueType::Int, OriginId::new(50));
    let work = value_result.lift(MorphismTerm::new(
        TestMorphism::Atom("work"),
        OriginId::new(51),
    ));
    let returned = value_result.return_value(2, TestValueType::Int, OriginId::new(52));
    let root = value_result.then(
        &[discarded, work, returned],
        &[OriginId::new(53), OriginId::new(54)],
    );
    let value_result = value_result.finish(root, &mut algebra).unwrap();
    let ControlNode::Then(children) = value_result.arena().node(value_result.arena().root()) else {
        panic!("work followed by a returned value must remain a Then");
    };
    assert_eq!(children.len(), 2);
    assert!(matches!(
        value_result.arena().node(children[0]),
        ControlNode::Lift(TestMorphism::Atom("work"))
    ));
    assert!(matches!(
        value_result.arena().node(children[1]),
        ControlNode::Return(catseq_core::control::ControlResult::Value {
            reference: 2,
            value_type: TestValueType::Int,
        })
    ));
    assert_eq!(
        value_result.origins().node(children[0]),
        [
            catseq_core::control::OriginContribution {
                origin: OriginId::new(50),
                role: catseq_core::control::OriginRole::Return,
            },
            catseq_core::control::OriginContribution {
                origin: OriginId::new(53),
                role: catseq_core::control::OriginRole::SerialOperator,
            },
            catseq_core::control::OriginContribution {
                origin: OriginId::new(51),
                role: catseq_core::control::OriginRole::Morphism,
            },
        ]
    );
    assert_eq!(
        value_result
            .origins()
            .then_boundary(value_result.arena().root(), 0),
        [catseq_core::control::OriginContribution {
            origin: OriginId::new(54),
            role: catseq_core::control::OriginRole::SerialOperator,
        }]
    );

    let mut unit_result = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let work = unit_result.lift(MorphismTerm::new(
        TestMorphism::Atom("work"),
        OriginId::new(60),
    ));
    let unit = unit_result.return_unit(OriginId::new(61));
    let root = unit_result.then(&[work, unit], &[OriginId::new(62)]);
    let unit_result = unit_result.finish(root, &mut algebra).unwrap();
    assert_eq!(
        unit_result.arena().node(unit_result.arena().root()),
        &ControlNode::Lift(TestMorphism::Atom("work"))
    );
}

#[test]
fn fail_with_a_successor_is_rejected_at_the_serial_boundary() {
    let mut algebra = TestMorphismAlgebra;
    let mut builder = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let fail = builder.fail(
        "acquisition failed",
        ControlResultType::Value(TestValueType::Int),
        OriginId::new(70),
    );
    let successor = builder.lift(MorphismTerm::new(
        TestMorphism::Atom("readout"),
        OriginId::new(71),
    ));
    let root = builder.then(&[fail, successor], &[OriginId::new(72)]);

    let error = builder.finish(root, &mut algebra).unwrap_err();
    assert_eq!(
        error,
        ControlBuildError::Diagnostic(ControlDiagnostic {
            code: ControlDiagnosticCode::NoNormalContinuation,
            subject: ControlDiagnosticSubject::ThenBoundary {
                left_child_index: 0,
            },
            primary_origin: OriginId::new(72),
            related_origins: vec![OriginId::new(70), OriginId::new(71)],
        })
    );
}

#[test]
fn a_final_fail_keeps_its_typed_failure_exit() {
    let mut algebra = TestMorphismAlgebra;
    let mut builder = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let work = builder.lift(MorphismTerm::new(
        TestMorphism::Atom("acquire"),
        OriginId::new(75),
    ));
    let fail = builder.fail(
        "acquisition failed",
        ControlResultType::Value(TestValueType::Int),
        OriginId::new(76),
    );
    let root = builder.then(&[work, fail], &[OriginId::new(77)]);
    let normalized = builder.finish(root, &mut algebra).unwrap();

    assert_eq!(
        normalized.summary(),
        &ControlSummary {
            result_type: ControlResultType::Value(TestValueType::Int),
            has_normal_exit: false,
            has_failure_exit: true,
            morphism_island_count: 1,
        }
    );
    let ControlNode::Then(children) = normalized.arena().node(normalized.arena().root()) else {
        panic!("work followed by Fail must remain a Then");
    };
    assert!(matches!(
        normalized.arena().node(children[1]),
        ControlNode::Fail {
            message,
            result_type: ControlResultType::Value(TestValueType::Int),
        } if message == "acquisition failed"
    ));
}

#[test]
fn lift_homomorphism_and_pure_parallel_preserve_morphism_semantics() {
    let mut algebra = TestMorphismAlgebra;

    let mut direct = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let root = direct.lift(MorphismTerm::new(
        TestMorphism::Serial(vec![TestMorphism::Atom("a"), TestMorphism::Atom("b")]),
        OriginId::new(80),
    ));
    let direct = direct.finish(root, &mut algebra).unwrap();

    let mut expanded = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let a = expanded.lift(MorphismTerm::new(
        TestMorphism::Atom("a"),
        OriginId::new(81),
    ));
    let b = expanded.lift(MorphismTerm::new(
        TestMorphism::Atom("b"),
        OriginId::new(82),
    ));
    let root = expanded.then(&[a, b], &[OriginId::new(83)]);
    let expanded = expanded.finish(root, &mut algebra).unwrap();

    assert_eq!(direct, expanded);
    assert_eq!(direct.summary(), expanded.summary());

    let parallel_morphism =
        TestMorphism::Parallel(vec![TestMorphism::Atom("ttl0"), TestMorphism::Atom("ttl1")]);
    let parallel_origins = vec![
        catseq_core::control::OriginContribution {
            origin: OriginId::new(84),
            role: catseq_core::control::OriginRole::Morphism,
        },
        catseq_core::control::OriginContribution {
            origin: OriginId::new(85),
            role: catseq_core::control::OriginRole::MorphismOperator,
        },
        catseq_core::control::OriginContribution {
            origin: OriginId::new(86),
            role: catseq_core::control::OriginRole::Morphism,
        },
    ];
    let mut parallel = ControlBuilder::<TestMorphism, u32, TestValueType>::new();
    let root = parallel.lift(MorphismTerm::from_origins(
        parallel_morphism.clone(),
        parallel_origins.clone(),
    ));
    let parallel = parallel.finish(root, &mut algebra).unwrap();
    assert_eq!(parallel.arena().nodes().len(), 1);
    assert_eq!(
        parallel.arena().node(parallel.arena().root()),
        &ControlNode::Lift(parallel_morphism)
    );
    assert_eq!(
        parallel.origins().node(parallel.arena().root()),
        parallel_origins
    );
}
