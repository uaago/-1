"""模型子包，统一导出训练模型构建函数。"""

from .mlp import MLPModel, make_model

__all__ = ["MLPModel", "make_model"]
