"""训练中间状态保存与无副作用梯度范数计算工具。"""

import math
import os
from pathlib import Path
from typing import Iterable

import torch


def compute_grad_norm(parameters: Iterable[torch.nn.Parameter]) -> float:
    """计算参数 L2 梯度范数，不修改梯度且不触发随机数生成器。"""
    total_sq = 0.0
    with torch.no_grad():
        for param in parameters:
            if param.grad is not None:
                norm = float(param.grad.detach().float().norm(2))
                total_sq += norm * norm
    return math.sqrt(total_sq)


def save_intermediate_state(run_dir: Path, payload: dict) -> Path:
    """原子写入 intermediate_state.pt，用于随时检查中间训练结果与调试变量。"""
    target = Path(run_dir) / "intermediate_state.pt"
    temporary = target.with_name(target.name + ".tmp")
    torch.save(payload, temporary)
    os.replace(temporary, target)
    return target
