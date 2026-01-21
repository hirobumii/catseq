import sys
import timeit
import tracemalloc
from dataclasses import dataclass
from functools import partial

# ==========================================
# 1. 定义三种类型的类
# ==========================================

# A. 普通 Python 类 (使用 __dict__)
class RegularClass:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

# B. 普通 Dataclass (默认使用 __dict__)
@dataclass
class StandardDataclass:
    x: int
    y: int
    z: int

# C. 带 Slot 的 Dataclass (无 __dict__)
@dataclass(slots=True)
class SlottedDataclass:
    x: int
    y: int
    z: int

# ==========================================
# 2. 测试工具函数
# ==========================================

def measure_memory(cls, count=100_000):
    """使用 tracemalloc 测量创建 count 个对象后的实际内存增量"""
    tracemalloc.start()
    
    # 创建对象列表
    objs = [cls(1, 2, 3) for _ in range(count)]
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # 转换为 MB
    memory_mb = current / (1024 * 1024)
    per_obj_bytes = current / count
    return memory_mb, per_obj_bytes

def measure_creation_time(cls, count=1_000_000):
    """测量创建 count 个对象所需的时间"""
    def create_loop():
        return [cls(i, i, i) for i in range(1000)]
    
    # 运行多次取平均值 (timeit 会自动决定 loop 次数，这里我们手动控制总数)
    loops = count // 1000
    t = timeit.timeit(create_loop, number=loops)
    return t

def measure_access_time(cls, count=10_000_000):
    """测量读取属性的时间"""
    obj = cls(1, 2, 3)
    
    def access_loop():
        # 模拟多次读取
        _ = obj.x
        _ = obj.y
        _ = obj.z
        _ = obj.x
        _ = obj.y
        _ = obj.z

    t = timeit.timeit(access_loop, number=count // 6) # 除以6是因为loop里读了6次
    return t

# ==========================================
# 3. 主程序
# ==========================================

def run_benchmark():
    classes = [
        ("Regular Class", RegularClass),
        ("Standard Dataclass", StandardDataclass),
        ("Slotted Dataclass", SlottedDataclass),
    ]

    print(f"{'Type':<20} | {'Memory (100k objs)':<20} | {'Create (1M ops)':<18} | {'Access (10M ops)':<18}")
    print("-" * 85)

    for name, cls in classes:
        # 1. 内存测试
        mem_total, mem_per_obj = measure_memory(cls, count=100_000)
        
        # 2. 创建速度测试
        create_time = measure_creation_time(cls, count=1_000_000)
        
        # 3. 访问速度测试
        access_time = measure_access_time(cls, count=10_000_000)

        print(f"{name:<20} | {mem_total:6.2f} MB ({int(mem_per_obj)} B/obj) | {create_time:6.4f} sec      | {access_time:6.4f} sec")

if __name__ == "__main__":
    print("Running benchmarks... (This may take a few seconds)\n")
    run_benchmark()
    
    # 验证是否存在 __dict__
    print("\n--- Structure Verification ---")
    r = RegularClass(1, 2, 3)
    s = StandardDataclass(1, 2, 3)
    sl = SlottedDataclass(1, 2, 3)
    
    print(f"RegularClass has __dict__?      {'__dict__' in dir(r)}")
    print(f"StandardDataclass has __dict__? {'__dict__' in dir(s)}")
    print(f"SlottedDataclass has __dict__?  {'__dict__' in dir(sl)}")