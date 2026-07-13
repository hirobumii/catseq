//! RTMQ backend for CatSeq's backend-independent template IR.

use std::collections::BTreeMap;

use catseq_core::definitions::RuntimeValueId;

/// Stable identifier for one RTMQ board in a service hardware map.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct BoardId(pub u16);

/// One operation positioned relative to the start of a reusable template.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RelativeEvent {
    pub offset_cycles: u64,
    pub operation_id: u32,
}

/// A relocatable, board-local artifact emitted when a service template is compiled.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RelativeBoardFragment {
    pub board: BoardId,
    pub duration_cycles: u64,
    pub events: Vec<RelativeEvent>,
    /// Late-bound event offsets evaluated from scan-dependent expressions.
    pub time_relocations: Vec<TimeRelocation>,
}

/// Replace one event's relative timestamp with a runtime-evaluated value.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TimeRelocation {
    pub event_index: usize,
    pub runtime_value: RuntimeValueId,
}

/// Values of scan-dependent expressions, resolved before RTMQ linking.
pub type RuntimeValues = BTreeMap<RuntimeValueId, u64>;

/// A board-local event after runtime linking has assigned an absolute timestamp.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LinkedEvent {
    pub timestamp_cycles: u64,
    pub operation_id: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LinkError {
    MissingRuntimeValue {
        board: BoardId,
        runtime_value: RuntimeValueId,
    },
    InvalidEventIndex {
        board: BoardId,
        event_index: usize,
    },
    TimestampOverflow {
        board: BoardId,
        base_cycles: u64,
        offset_cycles: u64,
    },
}

impl RelativeBoardFragment {
    /// Bind scan-dependent offsets and relocate one precompiled fragment.
    ///
    /// The fragment and its source template DAG remain immutable, so another
    /// scan point can reuse both without template recompilation.
    pub fn link_at(
        &self,
        base_cycles: u64,
        runtime_values: &RuntimeValues,
    ) -> Result<Vec<LinkedEvent>, LinkError> {
        let mut offsets: Vec<u64> = self
            .events
            .iter()
            .map(|event| event.offset_cycles)
            .collect();
        for relocation in &self.time_relocations {
            let offset = runtime_values
                .get(&relocation.runtime_value)
                .copied()
                .ok_or(LinkError::MissingRuntimeValue {
                    board: self.board,
                    runtime_value: relocation.runtime_value,
                })?;
            let target =
                offsets
                    .get_mut(relocation.event_index)
                    .ok_or(LinkError::InvalidEventIndex {
                        board: self.board,
                        event_index: relocation.event_index,
                    })?;
            *target = offset;
        }

        self.events
            .iter()
            .zip(offsets)
            .map(|(event, offset_cycles)| {
                base_cycles
                    .checked_add(offset_cycles)
                    .map(|timestamp_cycles| LinkedEvent {
                        timestamp_cycles,
                        operation_id: event.operation_id,
                    })
                    .ok_or(LinkError::TimestampOverflow {
                        board: self.board,
                        base_cycles,
                        offset_cycles,
                    })
            })
            .collect()
    }
}

/// Runtime-linked RTMQ program grouped deterministically by board.
pub type LinkedProgram = BTreeMap<BoardId, Vec<LinkedEvent>>;
