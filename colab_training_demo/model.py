"""向后兼容导出：转发至 colab_training_demo.models。"""

from .models import MLPModel, make_model

__all__ = ["MLPModel", "make_model"]
