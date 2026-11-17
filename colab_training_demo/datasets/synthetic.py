"""数据在运行时生成并缓存，无需联网下载。"""

from pathlib import Path
import torch


def make_data(config: dict, cache_dir: Path):
    """生成并缓存回归或分类示例数据集，返回 (train_x, train_y, val_x, val_y)。"""
    generator = torch.Generator().manual_seed(config["seed"] + 1000)
    count = config["train_samples"] + config["val_samples"]
    x = torch.rand(count, 2, generator=generator) * 4 - 2
    if config["task"] == "regression":
        y = (
            torch.sin(x[:, :1] * 2)
            + 0.3 * x[:, 1:] ** 2
            + 0.03 * torch.randn(count, 1, generator=generator)
        )
    else:
        y = (x.square().sum(dim=1) > 2).long()
    split = config["train_samples"]
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"x": x, "y": y}, cache_dir / "synthetic_data.pt")
    # 数据很小，整份放入显存；换成真实大型数据时应改为 DataLoader 分批读取。
    return x[:split], y[:split], x[split:], y[split:]
