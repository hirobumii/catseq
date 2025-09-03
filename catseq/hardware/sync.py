"""
Global synchronization operations for multi-board coordination.
"""

from ..morphism import MorphismDef, from_atomic
from ..types import Channel, State, AtomicMorphism, OperationType


def global_sync(sync_code: int) -> MorphismDef:
    """创建全局同步操作，根据板卡类型自动选择 master/slave 角色
    
    Args:
        sync_code: 同步代码，用于识别同步组
        
    Returns:
        MorphismDef: 可以应用到单个或多个通道的同步操作定义
    """
    
    def generator(channel: Channel, start_state: State) -> "Morphism":
        board_id = channel.board.id
        
        # 根据板卡类型选择操作
        if board_id == "main":
            # Master 板卡：触发所有 slave
            operation_type = OperationType.SYNC_MASTER
        else:
            # Slave 板卡：等待 master 触发
            operation_type = OperationType.SYNC_SLAVE
            
        op = AtomicMorphism(
            channel=channel,
            start_state=start_state,
            end_state=start_state,  # 同步不改变状态，只是时间分界点
            duration_cycles=0,  # 时间不确定，用 0 表示
            operation_type=operation_type,
        )
        return from_atomic(op)
    
    return MorphismDef(generator)