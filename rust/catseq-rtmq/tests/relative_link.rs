use catseq_core::definitions::RuntimeValueId;
use catseq_rtmq::{
    BoardId, LinkedEvent, RelativeBoardFragment, RelativeEvent, RuntimeValues, TimeRelocation,
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
        vec![
            LinkedEvent {
                timestamp_cycles: 100,
                operation_id: 7
            },
            LinkedEvent {
                timestamp_cycles: 120,
                operation_id: 8
            },
        ]
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
            event_index: 0,
            runtime_value: scan_delay,
        }],
    };

    let mut first_scan = RuntimeValues::new();
    first_scan.insert(scan_delay, 20);
    let mut second_scan = RuntimeValues::new();
    second_scan.insert(scan_delay, 35);

    assert_eq!(
        fragment.link_at(1_000, &first_scan).unwrap()[0].timestamp_cycles,
        1_020
    );
    assert_eq!(
        fragment.link_at(1_000, &second_scan).unwrap()[0].timestamp_cycles,
        1_035
    );
    assert_eq!(fragment.events[0].offset_cycles, 10);
}
