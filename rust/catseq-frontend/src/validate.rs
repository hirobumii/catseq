//! Semantic checks that require resolved scan-slot information.

use std::error::Error;
use std::fmt::{Display, Formatter};

use crate::hir::push_children;
use crate::{ExpressionId, HirKind, ScanSlotUse, SequenceHir, SourceSpan};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TopologyContext {
    CallTarget,
    ChannelDictionaryKey,
}

impl Display for TopologyContext {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::CallTarget => formatter.write_str("call target"),
            Self::ChannelDictionaryKey => formatter.write_str("channel dictionary key"),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidationError {
    file_name: String,
    span: SourceSpan,
    context: TopologyContext,
}

impl ValidationError {
    pub fn file_name(&self) -> &str {
        &self.file_name
    }

    pub const fn span(&self) -> SourceSpan {
        self.span
    }

    pub const fn context(&self) -> TopologyContext {
        self.context
    }
}

impl Display for ValidationError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "scan value cannot determine {} because that changes DAG topology at {}:{}:{}",
            self.context, self.file_name, self.span.start_line, self.span.start_column
        )
    }
}

impl Error for ValidationError {}

pub(crate) fn validate_scan_topology(
    file_name: &str,
    hir: &SequenceHir,
    scan_slots: &[ScanSlotUse],
) -> Result<(), ValidationError> {
    let mut tainted = vec![false; hir.expressions().len()];
    for slot in scan_slots {
        tainted[slot.expression().index() as usize] = true;
    }
    for index in 0..hir.expressions().len() {
        if tainted[index] {
            continue;
        }
        let mut children = Vec::new();
        push_children(hir.expressions()[index].kind(), &mut children);
        tainted[index] = children
            .into_iter()
            .any(|child| tainted[child.index() as usize]);
    }

    let reachable = hir.reachable_mask();
    for (index, expression) in hir.expressions().iter().enumerate() {
        if !reachable[index] {
            continue;
        }
        let context = match expression.kind() {
            HirKind::Call { function, .. } if is_tainted(&tainted, *function) => {
                Some(TopologyContext::CallTarget)
            }
            HirKind::Dictionary(entries)
                if entries
                    .iter()
                    .any(|(key, _value)| is_tainted(&tainted, *key)) =>
            {
                Some(TopologyContext::ChannelDictionaryKey)
            }
            _ => None,
        };
        if let Some(context) = context {
            return Err(ValidationError {
                file_name: file_name.to_owned(),
                span: expression.span(),
                context,
            });
        }
    }
    Ok(())
}

fn is_tainted(tainted: &[bool], expression: ExpressionId) -> bool {
    tainted[expression.index() as usize]
}
