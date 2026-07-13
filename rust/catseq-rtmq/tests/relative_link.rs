use catseq_core::definitions::RuntimeValueId;
use catseq_rtmq::{
    BoardId, LinkedBoardFragment, LinkedEvent, RelativeBoardFragment, RelativeEvent, RuntimeValues,
    TimeRelocation, TimeRelocationTarget,
};

#[test]
fn service_fragment_is_relocated_without_changing_relative_events() {
    let fragment = RelativeBoardFragment {
        board: BoardId(4),
        duration_cycles: 50,
        events: vec![
            RelativeEvent {
                offset_cycles: 0,
                operation_id: 7,
            },
            RelativeEvent {
                offset_cycles: 20,
                operation_id: 8,
            },
        ],
        time_relocations: vec![],
    };

    let linked = fragment.link_at(100, &RuntimeValues::new()).unwrap();

    assert_eq!(
        linked,
        LinkedBoardFragment {
            board: BoardId(4),
            duration_cycles: 50,
            events: vec![
                LinkedEvent {
                    timestamp_cycles: 100,
                    operation_id: 7
                },
                LinkedEvent {
                    timestamp_cycles: 120,
                    operation_id: 8
                },
            ]
        }
    );
    assert_eq!(fragment.events[1].offset_cycles, 20);
}

#[test]
fn scan_update_relinks_the_same_fragment_without_recompilation() {
    let scan_delay = RuntimeValueId::from_index(0);
    let fragment = RelativeBoardFragment {
        board: BoardId(1),
        duration_cycles: 100,
        events: vec![RelativeEvent {
            offset_cycles: 10,
            operation_id: 9,
        }],
        time_relocations: vec![TimeRelocation {
            target: TimeRelocationTarget::EventOffset(0),
            runtime_value: scan_delay,
        }],
    };

    let mut first_scan = RuntimeValues::new();
    first_scan.insert(scan_delay, 20);
    let mut second_scan = RuntimeValues::new();
    second_scan.insert(scan_delay, 35);

    assert_eq!(
        fragment.link_at(1_000, &first_scan).unwrap().events[0].timestamp_cycles,
        1_020
    );
    assert_eq!(
        fragment.link_at(1_000, &second_scan).unwrap().events[0].timestamp_cycles,
        1_035
    );
    assert_eq!(fragment.events[0].offset_cycles, 10);
}

#[test]
fn scan_dependent_duration_moves_the_next_serial_fragment() {
    let scan_duration = RuntimeValueId::from_index(1);
    let first = RelativeBoardFragment {
        board: BoardId(2),
        duration_cycles: 10,
        events: vec![],
        time_relocations: vec![TimeRelocation {
            target: TimeRelocationTarget::Duration,
            runtime_value: scan_duration,
        }],
    };
    let second = RelativeBoardFragment {
        board: BoardId(2),
        duration_cycles: 5,
        events: vec![RelativeEvent {
            offset_cycles: 0,
            operation_id: 12,
        }],
        time_relocations: vec![],
    };
    let mut scan = RuntimeValues::new();
    scan.insert(scan_duration, 40);

    let linked_first = first.link_at(100, &scan).unwrap();
    let linked_second = second
        .link_at(100 + linked_first.duration_cycles, &scan)
        .unwrap();

    assert_eq!(linked_first.duration_cycles, 40);
    assert_eq!(linked_second.events[0].timestamp_cycles, 140);
}
