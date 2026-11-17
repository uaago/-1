# 本地开发 → Colab 训练 → Drive 持久同步 → Step/Epoch 级断点续训

这是一个面向科研多文件工程的 Colab 远程训练模板项目。针对 Colab 只能通过 `.ipynb` 启动、随时可能断线或需要中途停下调试修改代码/超参的痛点，提供：

- **标准多目录科研工程结构**：支持 `models/`、`datasets/`、`utils/` 等多层子包导入 `train.py`，所有子目录文件自动递归追踪、打包和备份。
- **Google Drive 代码与检查点双端持久化**：首次上传后自动增量同步到云盘 `Colab_Training_Demo/project_workspace/`；Colab 断线更换新实例时，笔记本第 3 步会自动从 Drive 拉取代码到 `/content/colab_training_project`，**无需重新手动上传源码**。
- **Step/Batch 级安全中断与中间状态保存**：支持 `--stop-after-step`、`checkpoint_every_steps`、`checkpoint_every_seconds` 及点击单元格停止（`SIGINT`/`SIGTERM`）——会在**当前 Batch 完成后立即保存**完整断点（含精确的 Batch 内采样顺序与随机数状态）、`intermediate_state.pt`（batch loss、梯度范数、验证预测样本、进度快照）和 `last_model.pt`，并同步至 Drive。
- **灵活调试与改代码/改参续训**：默认 `--resume auto` 允许修改 `.py` 代码或调整学习率（`--lr`）、总轮数（`--epochs`）、`batch_size`（`--batch-size`）后直接续训（打印 `[resume-debug]` 变更记录并更新 `source.zip` 与 `code_version.json`）；需要严格校验时可显式加 `--strict-resume`。

## 先认清两个入口

- 本地 `.py` 的 Python 解释器：负责本地补全、检查和本地测试。可以继续选择你已有的 `Jupyter` 环境。
- **`启动Colab.ipynb` 右上角的 Kernel：选择 Colab，负责云端运行。** 普通 `.py` 的解释器不需要也不能通过这里变成 Colab。

启动笔记本通过 `sys.executable -u -m colab_training_demo.train` 启动独立云端进程，导入的 `models/`、`datasets/`、`utils/` 全部在云端执行。

## 第一次照着操作

### 1. 固定本地项目位置

在 VS Code 用“文件 → 打开文件夹”打开当前目录：

```text
D:\DesktopFILES\云端colab远程项目
```

项目自带 `.vscode/settings.json`，开启上传菜单，关闭实验性的 Server Mounting。云盘挂载仍由笔记本第 2 步完成。

### 2. 连接 GPU 服务器与挂载 Drive

1. 打开根目录 **`启动Colab.ipynb`**，右上角选择 `Select Kernel → Colab → New Colab Server → 可用 GPU → Python 内核`。
2. 运行笔记本 **第 1 步**，确认云端 Linux 环境与 `CUDA 可用: True`。
3. 运行笔记本 **第 2 步**，完成弹窗授权并验证读写。成功后持久目录为：
   - 训练输出：`/content/drive/MyDrive/Colab_Training_Demo/runs/`
   - 代码工作区：`/content/drive/MyDrive/Colab_Training_Demo/project_workspace/`

### 3. 上传项目并自动同步至 Drive

首次在 VS Code 左侧 **Explorer** 右键项目文件夹 **`云端colab远程项目` → Upload to Colab**（或多选 `colab_training_demo/`、`configs/`、`requirements-colab.txt` 上传到云端同一目录）。

运行笔记本 **第 3 步**：
- 若本地代码已上传到 `/content/...`，会自动递归扫描所有子目录并将最新代码增量同步到 `DRIVE_WORKSPACE`。
- 若遇到断线重连新运行时、`/content` 为空，第 3 步会自动从 `DRIVE_WORKSPACE` 拉取代码恢复到 `/content/colab_training_project`，**无需再次上传**。

### 4. 分段演练与 Step/Epoch 级续训

运行笔记本 **第 4 步**定义 `launch_training()`，随后：

1. 运行 **第 5 步**（默认 `--stop-after-epoch 3`；也可注释切换为 `--stop-after-step 40 --checkpoint-every-steps 20` 体验 Batch 级停止）。
2. 运行 **第 6 步**，查看本地与 Drive 中的快照目录、`status.json` 及 `intermediate_state.pt` 中间状态。
3. 运行 **第 7 步**执行 `launch_training("--resume", "auto")`，从停止的 Epoch 或精确的 Batch 位置继续训练至完成。
4. 运行 **第 8 步**绘制损失曲线并保存到 Drive。

## 日常调试、改代码与断线恢复

| 场景 | 操作 |
|---|---|
| 随时点击停止调试 | 点击第 4/5/7 步运行中单元格的停止按钮（发送 `SIGINT`），训练将在**当前 Batch 完成后立即存盘并同步 Drive** |
| 按固定步数保存 | 在配置中设置 `"checkpoint_every_steps": 50` 或传入 `--checkpoint-every-steps 50` |
| 修改 `.py` 代码后续训 | 保存并重新上传后（第 3 步会自动更新云盘工作区），直接 `launch_training("--resume", "auto")` 继续训练 |
| 调试期修改超参数续训 | 直接传参覆盖，例如 `launch_training("--resume", "auto", "--lr", "0.001", "--epochs", "20", "--batch-size", "128")` |
| 严格锁定代码与配置 | 追加 `"--strict-resume"`，任何源码或关键超参变动都会拒绝续训并提示使用原 `source.zip` |
| 原运行时已被回收 | 新连运行时，顺序执行第 1～4 步（第 3 步自动从 Drive 恢复代码），保持 `RUN_ID` 不变，直接执行第 7 步 |
| 同运行时中断排查 | 先执行第 9 步检查云端进程，确认旧进程已退出再执行第 7 步 |

> **注意**：`task`、`seed`、`train_samples`、`val_samples`、`hidden_size` 属于模型结构与数据集定义键，修改这些结构键时仍要求更换新的 `RUN_ID` 新建实验。

## 多目录工程结构与输出布局

```text
本地项目/
├── 启动Colab.ipynb                    # 云端启动、Drive 挂载与代码同步入口
├── colab_training_demo/
│   ├── train.py                       # 训练主程序（支持 Epoch/Step 级中断与调试续训）
│   ├── checkpoint.py                  # 快照写入、SHA-256 校验、Drive 备份与保留策略
│   ├── model.py / data.py             # 向后兼容重导出入口
│   ├── models/
│   │   ├── __init__.py
│   │   └── mlp.py                     # 模型定义子包（实际科研工程可新增多网络模块）
│   ├── datasets/
│   │   ├── __init__.py
│   │   └── synthetic.py               # 数据集子包（实际科研工程可新增多数据集模块）
│   └── utils/
│       ├── __init__.py
│       ├── code_sync.py               # 多目录源码递归扫描、Drive 增量同步与自动恢复
│       └── state_bag.py               # 梯度范数计算与 intermediate_state.pt 原子保存
├── configs/
│   ├── regression.json
│   └── classification.json
├── requirements-colab.txt
├── build_colab_zip.py
└── tests/test_training.py
```

Drive 持久目录结构：

```text
Colab_Training_Demo/
├── project_workspace/                 # 自动同步的多目录工程代码副本（供新实例免重传恢复）
└── runs/<RUN_ID>/
    ├── config.json
    ├── code_version.json              # 含历次续训源码哈希与超参变更 history
    ├── source.zip                     # 最新源码多目录归档
    ├── environment.json
    ├── status.json
    ├── metrics.csv
    ├── evaluation.json
    ├── intermediate_state.pt          # 最新进度、batch loss、grad_norm、val 预测样本等中间状态
    ├── last_model.pt                  # 最新一次保存时的模型权重
    ├── best_model.pt                  # 最佳验证损失对应的推理权重
    ├── final_model.pt                 # 达到总 epochs 后生成
    ├── loss_curve.png
    └── checkpoints/
        ├── epoch_00000003/            # 完整 Epoch 快照
        └── epoch_00000003_step_00000100/  # Step/Batch 级中断快照
            ├── state.pt               # 含模型、优化器、调度器、RNG 及精确的 in_epoch 采样状态
            ├── metrics.csv
            └── complete.json          # SHA-256 完成标记
```

## ZIP 网页备用路线

如果 VS Code 登录或上传扩展异常，可在网页 Colab 运行：

1. 本地运行 `python build_colab_zip.py` 生成 `dist/colab_training_demo.zip`（自动包含 `models/`、`datasets/`、`utils/`）。
2. 在 [Colab 网页](https://colab.research.google.com/) 打开 `启动Colab.ipynb`，选择 GPU 并运行第 1～2 步。
3. 上传 ZIP 至 `/content/colab_training_demo.zip`，在第 3 步之前解压到 `/content`：

```python
from pathlib import Path
import zipfile

archive = Path("/content/colab_training_demo.zip")
destination = Path("/content")
assert not (destination / "colab_training_demo").exists(), "已有源码目录，请先确认版本或使用新运行时"
with zipfile.ZipFile(archive) as bundle:
    for member in bundle.infolist():
        target = (destination / member.filename).resolve()
        assert target.is_relative_to(destination), "ZIP 路径越界"
    bundle.extractall(destination)
```

4. 继续运行第 3～8 步。

## 本地验证命令

```powershell
& 'E:\Users\lenovo1\anaconda3\envs\Jupyter\python.exe' -m unittest discover -s tests -v
& 'E:\Users\lenovo1\anaconda3\envs\Jupyter\python.exe' build_colab_zip.py
```
