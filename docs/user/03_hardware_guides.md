# 3. 硬件接口使用指南 (Hardware Guides)

`catseq` 通过 `catseq.hardware` 模块为不同类型的硬件提供了高级、易用的接口。这些接口封装了底层的原子操作，提供了面向用户任务的函数。

当前可用的硬件源语言接口包括：

- [TTL 接口定义](../../catseq/hardware/ttl.py)
- [RWG 接口定义](../../catseq/hardware/rwg.py)

设备寄存器、端口和硬件行为属于 device 文档，可参阅
[QCtrl RWG 设备参考](../dev/06_QCtrl_RWG.md)。后续面向用户的完整示例应继续
写在 `docs/user`，而不是混入设备参考目录。
