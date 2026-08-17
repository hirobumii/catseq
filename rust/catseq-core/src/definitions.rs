//! Backend-independent definition identifiers.

/// Slot populated when an experiment supplies scan values at link time.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct RuntimeValueId(u32);

impl RuntimeValueId {
    pub const fn from_index(index: u32) -> Self {
        Self(index)
    }

    pub const fn index(self) -> u32 {
        self.0
    }
}
