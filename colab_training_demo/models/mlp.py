"""基础多层感知机模型定义，保持权重 key 与原生 Sequential 完全兼容。"""

from torch import nn


class MLPModel(nn.Sequential):
    """兼容原 nn.Sequential 层命名与参数初始化顺序的 MLP 模型。"""

    def __init__(self, task: str, hidden_size: int):
        super().__init__(
            nn.Linear(2, hidden_size),
            nn.Tanh(),
            nn.Dropout(0.1),
            nn.Linear(hidden_size, hidden_size),
            nn.Tanh(),
            nn.Linear(hidden_size, 1 if task == "regression" else 2),
        )


def make_model(task: str, hidden_size: int) -> nn.Module:
    """根据任务类型构建模型。"""
    return MLPModel(task, hidden_size)
