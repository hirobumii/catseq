/// MorphismPath - 线性指令缓冲区
///
/// 单通道操作序列的数据容器，支持 O(1) append 和 O(N) extend。
/// 这是 BoundMorphism 的 Rust 后端存储。

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use std::sync::Arc;

/// 单个操作步骤
#[derive(Clone, Debug)]
pub struct Step {
    pub duration: u64,
    pub opcode: u16,
    pub payload: Arc<Vec<u8>>,
}

/// 单通道的指令缓冲区
#[pyclass]
#[derive(Clone)]
pub struct MorphismPath {
    #[pyo3(get)]
    pub channel_id: u32,

    /// 操作步骤列表 (duration, opcode, payload)
    /// 使用 Arc<Vec<u8>> 确保 clone/extend 是零数据拷贝
    pub steps: Vec<Step>,

    #[pyo3(get)]
    pub total_duration: u64,
}

#[pymethods]
impl MorphismPath {
    /// 创建空的 MorphismPath
    #[new]
    pub fn new(channel_id: u32) -> Self {
        MorphismPath {
            channel_id,
            steps: Vec::with_capacity(64),
            total_duration: 0,
        }
    }

    /// 创建带预分配容量的 MorphismPath
    #[staticmethod]
    pub fn with_capacity(channel_id: u32, capacity: usize) -> Self {
        MorphismPath {
            channel_id,
            steps: Vec::with_capacity(capacity),
            total_duration: 0,
        }
    }

    /// O(1) 追加单个操作
    pub fn append(&mut self, duration: u64, opcode: u16, payload: Vec<u8>) {
        self.steps.push(Step {
            duration,
            opcode,
            payload: Arc::new(payload),
        });
        self.total_duration += duration;
    }

    /// O(N) 指针复制扩展（极速）
    ///
    /// 将另一个 MorphismPath 的所有步骤追加到本 path。
    /// 由于使用 Arc，payload 数据不会被复制。
    pub fn extend(&mut self, other: &MorphismPath) -> PyResult<()> {
        if self.channel_id != other.channel_id {
            return Err(PyValueError::new_err(format!(
                "Channel mismatch: {} vs {}",
                self.channel_id, other.channel_id
            )));
        }
        self.steps.extend_from_slice(&other.steps);
        self.total_duration += other.total_duration;
        Ok(())
    }

    /// 获取步骤数量
    pub fn len(&self) -> usize {
        self.steps.len()
    }

    /// 检查是否为空
    pub fn is_empty(&self) -> bool {
        self.steps.is_empty()
    }

    /// 克隆 MorphismPath
    #[pyo3(name = "clone")]
    pub fn py_clone(&self) -> Self {
        self.clone()
    }

    /// 创建恒等态射 (Identity Morphism)
    ///
    /// 物理语义：指定时长的 Wait 操作（保持状态不变）
    /// 代数语义：Id_t
    ///
    /// Args:
    ///     channel_id: 通道 ID
    ///     duration: 时长（时钟周期）
    ///     opcode: Wait 操作码（通常为 0x0000）
    #[staticmethod]
    pub fn identity(channel_id: u32, duration: u64, opcode: u16) -> Self {
        let mut path = MorphismPath::new(channel_id);
        if duration > 0 {
            path.steps.push(Step {
                duration,
                opcode,
                payload: Arc::new(Vec::new()),
            });
            path.total_duration = duration;
        }
        path
    }

    /// 对齐时间边界 (Align Boundary)
    ///
    /// 物理语义：在末尾补 Wait 直到达到 target_duration
    /// 代数语义：Self = Self >> Id_(target - current)
    ///
    /// 如果当前时长 >= target，则不做任何事。
    pub fn align(&mut self, target_duration: u64, opcode: u16) {
        if self.total_duration < target_duration {
            let diff = target_duration - self.total_duration;
            self.steps.push(Step {
                duration: diff,
                opcode,
                payload: Arc::new(Vec::new()),
            });
            self.total_duration = target_duration;
        }
    }

    /// 获取指定索引的步骤（用于 Python 迭代）
    pub fn get_step(&self, index: usize) -> PyResult<(u64, u16, Vec<u8>)> {
        if index >= self.steps.len() {
            return Err(PyValueError::new_err("Index out of bounds"));
        }
        let step = &self.steps[index];
        Ok((step.duration, step.opcode, (*step.payload).clone()))
    }

    /// 提供 Python 迭代器
    fn __iter__(slf: PyRef<'_, Self>) -> PyResult<PathIterator> {
        Ok(PathIterator {
            path: slf.clone(),
            index: 0,
        })
    }

    fn __len__(&self) -> usize {
        self.steps.len()
    }

    fn __repr__(&self) -> String {
        format!(
            "<MorphismPath channel={} steps={} duration={}>",
            self.channel_id,
            self.steps.len(),
            self.total_duration
        )
    }
}

/// Python 迭代器
#[pyclass]
pub struct PathIterator {
    path: MorphismPath,
    index: usize,
}

#[pymethods]
impl PathIterator {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self) -> Option<(u64, u16, Vec<u8>)> {
        if self.index >= self.path.steps.len() {
            return None;
        }
        let step = &self.path.steps[self.index];
        self.index += 1;
        Some((step.duration, step.opcode, (*step.payload).clone()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_append() {
        let mut path = MorphismPath::new(0);
        path.append(100, 0x0101, vec![1, 2, 3]);
        path.append(200, 0x0102, vec![4, 5]);

        assert_eq!(path.len(), 2);
        assert_eq!(path.total_duration, 300);
    }

    #[test]
    fn test_extend() {
        let mut path1 = MorphismPath::new(0);
        path1.append(100, 0x0101, vec![]);

        let mut path2 = MorphismPath::new(0);
        path2.append(200, 0x0102, vec![]);
        path2.append(50, 0x0103, vec![]);

        path1.extend(&path2).unwrap();

        assert_eq!(path1.len(), 3);
        assert_eq!(path1.total_duration, 350);
    }

    #[test]
    fn test_extend_channel_mismatch() {
        let mut path1 = MorphismPath::new(0);
        let path2 = MorphismPath::new(1);

        let result = path1.extend(&path2);
        assert!(result.is_err());
    }

    #[test]
    fn test_arc_zero_copy() {
        let mut path1 = MorphismPath::new(0);
        let large_payload = vec![0u8; 10000];
        path1.append(100, 0x0101, large_payload);

        // Clone should not copy the payload data
        let path2 = path1.clone();

        // Both should point to the same Arc
        assert!(Arc::ptr_eq(
            &path1.steps[0].payload,
            &path2.steps[0].payload
        ));
    }
}
