---
name: colab-remote-training
description: >-
  将本地多文件/多目录 Python 科研工程适配为 Google Colab 远程 GPU 训练与 Google Drive 双端持久同步架构。
  当用户需要将科研代码迁移到 Colab 运行、配置 .ipynb 启动器、实现检查点与中间状态自动备份、或支持随时停止调试改代码/调参后断点续训时使用。
---

# Colab 多目录科研工程远程训练与持久化 Skill

## 适用场景
- 用户在本地（如 VS Code）编写多模块科研代码（PyTorch 深度学习、强化学习、科学计算等），需要连接 Google Colab 远程 GPU 运行，但 Colab 只能通过 `.ipynb` 启动。
- 需要解决 Colab 运行时随时可能断线/回收导致的进度丢失问题，要求将代码工作区、检查点（Epoch 级和 Batch/Step 级）、训练指标、模型权重与中间诊断状态持久化到 Google Drive。
- 需要支持随时点击停止调试、修改 `.py` 代码或学习率/轮数等超参数后，继续从上次断点无缝恢复训练。

---

## 核心架构规范

### 1. 前台遥控器 + 后台多目录引擎分离
- **固定启动笔记本（`启动Colab.ipynb`）**：不放置核心训练算法，仅依次承担以下职责：
  1. **环境自检**：校验处于 Linux 云端容器、`torch` 可用、按需校验 `torch.cuda.is_available()`。
  2. **Drive 挂载与写入探针**：执行 `drive.mount("/content/drive")`，校验 `os.path.ismount("/content/drive")` 与 `MyDrive` 目录可用性，并实际写入/读回/删除探针文件，建立 `PERSISTENT_ROOT`（训练结果）与 `DRIVE_WORKSPACE`（代码备份）。
  3. **代码定位与双端自动同步**：
     - 本地上传至 `/content` 后，调用 `sync_workspace_to_drive(PROJECT, DRIVE_WORKSPACE)` 通过 SHA-256 增量备份所有子目录源码与配置。
     - 若断线更换新 Colab 实例且 `/content` 下尚无代码，自动从 `DRIVE_WORKSPACE` 调用 `restore_workspace_from_drive` 恢复完整多目录工程到 `/content/<project>`，实现免重传续训。
  4. **独立子进程启动**：通过 `subprocess.Popen([sys.executable, "-u", "-m", "<pkg>.train", ...], cwd=PROJECT)` 启动训练，流式打印输出，并在捕获 `KeyboardInterrupt` 时向子进程发送 `signal.SIGINT` 后等待其存盘退出。
- **科研主工程包（`<pkg>/`）**：
  - 按职责拆分为多目录子包（例如 `models/`、`datasets/`、`utils/`、`checkpoint.py`、`train.py`），在 `train.py` 中通过包内相对导入组合运行。
  - 源码递归扫描与 ZIP 打包脚本（如 `build_colab_zip.py`）须使用 `rglob("*.py")`（排除 `__pycache__`）覆盖所有子目录。

### 2. 临时盘与持久盘隔离
- **高速临时盘（`/content/runs/<RUN_ID>`）**：存放数据集缓存、逐轮/逐批日志与本地快照，避免高频 I/O 拖慢或阻塞 Google Drive。
- **持久盘（`/content/drive/MyDrive/<Project>/runs/<RUN_ID>`）**：
  - 严格校验 `persistent != run_dir` 且二者不互相嵌套。
  - 每次写入 `/content/drive` 前通过 `ensure_persistent_available` 核对挂载状态，严禁掉挂载后写入普通本地目录制造“假备份”。
  - 本地运行目录通过 SQLite 排他锁（`sqlite3.connect(..., timeout=0)` + `BEGIN EXCLUSIVE`）防止同机重复启动；崩溃后操作系统自动释放锁。

### 3. 原子检查点、SHA-256 完成标记与损坏回退
- **目录命名**：
  - 完整 Epoch 快照：`checkpoints/epoch_{epoch:08d}/`
  - Step/Batch 级中途快照：`checkpoints/epoch_{completed_epoch:08d}_step_{global_step:08d}/`
- **原子提交协议**：
  1. 在临时隐藏目录写入 `state.pt` 与快照时的 `metrics.csv`。
  2. 计算文件 SHA-256 后写入 `complete.json`（含 `epoch`、`global_step`、`mid_epoch`、`files` 哈希清单）。
  3. 通过 `os.replace` 发布快照；同步到 Drive 时先写入 `.uploading` 临时文件并核对哈希，**最后**再复制 `complete.json`。
- **恢复与保留策略**：
  - 按 `(epoch_num, step_num)` 降序扫描本地和持久目录全部快照，只加载通过 `complete.json` 哈希校验的快照；遇到损坏或未传完快照时打印 `[skip]` 并自动回退至上一个有效版本，同时用快照附带的 `metrics.csv` 重建训练日志。
  - 仅在 Drive 备份成功后才执行 `prune(keep_last)`（仅删除 `checkpoints/` 内部受管旧目录）；备份失败重试并保留本地副本。

### 4. Step/Batch 级安全中断与中间状态保存
- **信号捕获与步级存盘**：注册 `SIGINT`/`SIGTERM` 处理器。收到停止信号或触发 `--stop-after-step` / `checkpoint_every_steps` / `checkpoint_every_seconds` 时，在**当前 Batch 完成后立即存盘**（无需等待整轮 Epoch 结束），同步 Drive 后退出。
- **完整状态保存清单**：
  - `state.pt`：模型权重、优化器状态、学习率调度器状态、`epoch`、`global_step`、`best_loss`、`best_epoch`、`best_model`、Python/NumPy/Torch/CUDA/采样器随机状态 `rng`，以及 Epoch 中途中断时的 `in_epoch`（`current_epoch`、`completed_batches`、`total_batches`、`order` 采样排列、`total_loss`、`seen_samples`）。
  - *扩展提示*：如新项目使用混合精度（AMP）需额外保存 `GradScaler.state_dict()`；如为强化学习需额外保存环境统计/Replay Buffer 游标。
  - 诊断与推理产物：每次存盘同步更新 `last_model.pt`、`best_model.pt`（存在时）、`final_model.pt`（完成总轮数时）、`status.json`、`evaluation.json` 与 `intermediate_state.pt`（含 `batch_loss`、`grad_norm`、验证集预测样本、`custom_state`）。

### 5. 灵活调试续训与严格校验模式
- **默认灵活调试模式（`--resume auto`）**：
  - 结构性键（如 `task`、`seed`、`train_samples`、`val_samples`、`hidden_size` 等决定模型维度或数据集本身的字段）变动仍报错拒绝，提示新建 `RUN_ID`。
  - 源码变动（`source_sha256`）及可调训练超参变动（`learning_rate` / `--lr`、`epochs` / `--epochs`、`batch_size` / `--batch-size`、`checkpoint_every_steps` 等）**允许直接续训**：打印 `[resume-debug]` 变更提示、同步更新优化器 `param_groups[i]["lr"]` 与调度器 `base_lrs`，在 `code_version.json` 追加 `history` 并更新 `source.zip`。
- **严格基准模式（`--strict-resume`）**：开启后对任何源码哈希或训练超参不一致抛出 `ValueError`，确保对照实验可复现性。

---

## 本仓库参考实现
- 训练主程序：[colab_training_demo/train.py](../../colab_training_demo/train.py)
- 检查点与 Drive 校验备份：[colab_training_demo/checkpoint.py](../../colab_training_demo/checkpoint.py)
- 多目录模块示例：[colab_training_demo/models/mlp.py](../../colab_training_demo/models/mlp.py)、[colab_training_demo/datasets/synthetic.py](../../colab_training_demo/datasets/synthetic.py)
- 代码同步与中间状态工具：[colab_training_demo/utils/code_sync.py](../../colab_training_demo/utils/code_sync.py)、[colab_training_demo/utils/state_bag.py](../../colab_training_demo/utils/state_bag.py)
- 云端启动器与 ZIP 打包：[启动Colab.ipynb](../../启动Colab.ipynb)、[build_colab_zip.py](../../build_colab_zip.py)
- 自动化测试套件：[tests/test_training.py](../../tests/test_training.py)
- 用户操作手册：[Colab远程科研训练_SKILL指南.md](../../Colab远程科研训练_SKILL指南.md)

---

## 交付检查清单
在将这套模式迁移到任何新科研项目后，必须完成以下本地与云端核验：
1. 本地 `unittest` 覆盖：连续训练 vs Epoch 边界续训一致性、Mid-Epoch（Step 级）中断恢复一致性、改代码/调超参灵活续训、`--strict-resume` 拦截、损坏快照回退、Drive 掉挂载拒绝假写入、多目录代码同步与空实例恢复。
2. ZIP 打包脚本包含所有递归子目录且 CRC 校验无误。
3. Notebook JSON 与全部代码单元语法解析无误。
