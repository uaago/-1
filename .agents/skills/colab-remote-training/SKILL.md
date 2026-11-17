---
name: colab-remote-training
description: >-
  将本地多文件/多目录 Python 科研工程（深度学习、强化学习等）适配为 Google Colab 远程 GPU 训练与 Google Drive 双端持久同步架构。
  当用户需要将科研代码迁移到 Colab 运行、配置 VS Code Remote-SSH / .ipynb 启动器（含 GitHub 秒级拉取与 Drive 自动绑定/同步）、实现检查点与中间状态自动备份、或支持随时停止调试改代码/调参后断点续训时使用。
---

# Colab 多目录科研工程远程训练与持久化 Skill

## 适用场景
- 用户在本地（如 VS Code）调试完成多模块科研代码（PyTorch 深度学习、强化学习 PPO/SAC/TD3、科学计算等），准备迁移到 Google Colab 远程 GPU（A100/L4/T4）长期训练与调试。
- 希望既能用 **VS Code Remote-SSH** 像连接实验室 Linux 服务器一样直接打开远程项目、改代码、点 `▷` / `F5` 单步调试与挂 `tmux` 后台，也能保留 **`.ipynb` 笔记本遥控器** 和 **WSL2 `google-colab-cli`** 批处理能力。
- 需要解决 Colab 实例随时可能回收或断线问题，要求将源码工作区、检查点（Epoch/Update 级与 Batch/Step 级）、训练指标、模型权重与中间诊断状态自动持久化到 Google Drive。

---

## 核心架构规范

### 1. 多目录工程结构 + 三入口兼容（Remote-SSH / `.ipynb` / CLI）
- **配套 `.gitignore`**：必须屏蔽 `__pycache__/`、`*.py[cod]`、`dist/`、`runs/`、`_verification/`、`.ipynb_checkpoints/`、`wandb/`、`*.pt`、`*.pth`，保证 GitHub 只同步轻量源码与配置。仓库名建议纯英文短名，不以 `-` 开头；私有仓库用只读 Fine-grained Token 配合 `getpass` 或 Secrets 鉴权。
- **主入口 `train.py` 双模式运行**：
  - 文件顶部加入 `__package__` 路径兜底，确保既能 `python3 -m <pkg>.train ...`，也能在 VS Code 中直接点击 `▷` 运行 `python3 <pkg>/train.py` 或按 `F5`（配套 `.vscode/launch.json`）调试而不报 `ImportError`。
  - 未传入 `--run-id` 且处于交互式终端（需注意 Windows `NUL` 设备 `isatty()` 误判，捕获 `EOFError` 转为 `parser.error`）时，提供清晰的中文交互引导（选任务、输入/生成 `RUN_ID`、检测已有实验提示是否 `--resume auto`、可选覆盖 `epochs`/`lr`）。
- **入口 1：VS Code Remote-SSH（推荐日常科研主力）**
  - 利用官方 `google-colab-cli`（WSL2/Linux/macOS 通过 `uv tool install --python 3.12 google-colab-cli --with keyrings.alt` 安装，配合 `PlaintextKeyring` 与 `BROWSER=wslview`）在全局 `~/.ssh/config` 配置非写死的动态别名：`colab-active`、`colab-a100`、`colab-l4`、`colab-t4` 及通配符 `colab-s-*`（Windows 通过 `C:/Windows/System32/wsl.exe -e ... colab ssh --proxy-mode ...` 桥接，使用 `UserKnownHostsFile NUL` 与共用的 `id_ed25519` 密钥）。
  - **Remote-SSH 稳定性铁律**：
    1. 连接成功后后台由 VS Code 独立托管 `wsl.exe` 隧道，可关闭手工打开的 WSL 终端，但**禁止在连接期间运行 `wsl --shutdown`**；
    2. 申请卡前先跑 `colab sessions` 与 `colab usage` 检查是否有 `[?]` 遗留外部会话占用配额（有则去 Colab 网页关掉），统一选 **`Standard`** 内存配置；
    3. 重要长训配合 `scripts/remote_train.sh --tmux`（或 `nohup`）放云端后台，并在远程安装 `ms-python.python` 扩展（不需装 `google.colab`）；
    4. 终端复制复杂命令避免带尾随空格的 `\` 断行；训练结束跑 `colab stop -s <name>` 并在 `colab usage` 确认归零。
- **入口 2：固定启动笔记本（`启动Colab.ipynb`）**
  - 按序完成：环境自检 → Drive 挂载与写入探针 → GitHub `clone --depth 1` / `pull` + 白名单增量同步 Drive `project_workspace`（无网时从 Drive 兜底恢复）→ `subprocess.Popen` 启动独立子进程并转发 `SIGINT`。
- **入口 3：WSL2 纯命令行批处理（`scripts/colab_cli_train.sh`、`scripts/colab_ssh_up.sh`）**
  - 封装 `colab new` → `colab drivemount` → `colab upload` + `colab ssh` → 可选 `--auto-stop`（完成后自动 `colab stop`）。

### 2. 临时盘与持久盘隔离 + Colab 自动绑定 Drive
- **自动绑定 Drive**：`train.py` 实现 `_resolve_persistent_root`——当未显式传入 `--persistent-root` 且未传 `--no-persistent` 时，自动检测 `os.path.ismount("/content/drive") and Path("/content/drive/MyDrive").is_dir()`，若成立则自动绑定至 `/content/drive/MyDrive/<Project>/runs/<RUN_ID>`（确保直接点 `▷` 或 `F5` 运行也自动存云盘）；本地或无挂载测试时不绑定；若在 `/content` 容器内却未挂载 Drive 则输出明确警告。
- **双盘隔离与防伪云盘**：禁止 `local_root` 与 `persistent_root` 重合或互相嵌套；每次写入 Drive 前校验挂载状态；本地运行目录使用 SQLite 排他文件锁防并发。

### 3. 原子检查点、SHA-256 完成标记与损坏回退
- **目录命名**：`checkpoints/epoch_{epoch:08d}/` 与 `checkpoints/epoch_{completed_epoch:08d}_step_{global_step:08d}/`。
- **原子提交协议**：先在临时目录写入 `state.pt` 与快照时的 `metrics.csv`，再写 SHA-256 清单 `complete.json`，通过 `os.replace` 发布；同步 Drive 时先写 `.uploading` 并二次校验，最后复制 `complete.json`。
- **恢复与保留策略**：按 `(epoch_num, step_num)` 倒序加载首个完整有效的快照，跳过损坏版本并重建 `metrics.csv`；仅在 Drive 备份成功后执行 `prune(keep_last)`；`best_model.pt`、`final_model.pt`、`metrics.csv` 单独永久保留。

### 4. Step/Batch 级安全中断与中间状态保存（含强化学习 RL 迁移规范）
- **信号捕获与步级存盘**：捕获 `SIGINT`/`SIGTERM`，收到信号或达到 `--stop-after-step` / `checkpoint_every_steps` / `checkpoint_every_seconds` 时，在**当前 Batch / Update 完成后立即存盘**并同步 Drive 后安全退出。
- **完整状态保存清单**：
  - 通用：`state.pt` 须含模型、优化器、LR 调度器、`epoch`、`global_step`、`best_*`、Python/NumPy/Torch/CUDA/采样器随机状态 `rng` 及 `in_epoch` 断点状态（如用 AMP 额外保存 `GradScaler.state_dict()`）。
  - **强化学习（RL）项目专项扩展**：
    - 除策略/价值/目标网络与对应优化器外，还须保存环境归一化统计量（如 `VecNormalize` 的 `obs_rms`/`ret_rms`）、探索系数/熵温度（如 `alpha`）、课程学习进度；
    - On-policy（PPO）Rollout 结束边界天然适合做 Step/Update 级快照；
    - Off-policy（SAC/TD3/DQN）的大型 Replay Buffer 切勿每个小步全量上传 Drive，应先写临时盘并在较长间隔（或 `SIGINT` 安全退出时）增量/单独同步 `buffer.pt` 到云盘，避免阻塞训练与撑爆 Drive I/O。
  - 诊断产物：同步更新 `last_model.pt`、`best_model.pt`、`final_model.pt`、`status.json`、`evaluation.json` 与 `intermediate_state.pt`（`batch_loss`、`grad_norm`、验证集/评估指标快照、`custom_state`）。

### 5. 灵活调试续训、防覆盖保护与严格模式
- **防覆盖保护**：不带 `--resume auto` 且本地或云盘已有同名 `RUN_ID` 时，必须抛出 `FileExistsError` 拦截覆盖。
- **默认灵活调试模式（`--resume auto`）**：结构性字段（模型骨架尺寸、任务类型、种子、样本/环境维度）变化或开启 `--strict-resume` 时拒绝续训；允许修改 `.py` 源码及可调超参（`--lr`、`--epochs`、`--batch-size`、`--checkpoint-every-steps`），打印 `[resume-debug]` 并动态更新优化器 `param_groups` 与调度器 `base_lrs`，记录 `code_version.json` 历史与 `git_commit`。

---

## 本仓库参考实现
- 训练主程序：[colab_training_demo/train.py](../../colab_training_demo/train.py)
- 检查点与 Drive 校验备份：[colab_training_demo/checkpoint.py](../../colab_training_demo/checkpoint.py)
- 多目录模块示例：[colab_training_demo/models/mlp.py](../../colab_training_demo/models/mlp.py)、[colab_training_demo/datasets/synthetic.py](../../colab_training_demo/datasets/synthetic.py)
- 代码同步与中间状态工具：[colab_training_demo/utils/code_sync.py](../../colab_training_demo/utils/code_sync.py)、[colab_training_demo/utils/state_bag.py](../../colab_training_demo/utils/state_bag.py)
- 启动器、SSH/CLI 脚本与调试配置：[启动Colab.ipynb](../../启动Colab.ipynb)、[.vscode/launch.json](../../.vscode/launch.json)、[scripts/colab_ssh_up.sh](../../scripts/colab_ssh_up.sh)、[scripts/remote_train.sh](../../scripts/remote_train.sh)、[scripts/colab_cli_train.sh](../../scripts/colab_cli_train.sh)、[build_colab_zip.py](../../build_colab_zip.py)
- 自动化测试套件：[tests/test_training.py](../../tests/test_training.py)
- 用户操作手册：[Colab远程科研训练_SKILL指南.md](../../Colab远程科研训练_SKILL指南.md)

---

## 交付检查清单
在将这套模式迁移到任何新科研项目（含 RL）后，必须完成以下核验：
1. 本地 `unittest` 覆盖：Epoch 级与 Mid-Epoch Step 级中断恢复一致性、直接运行 `train.py` 与 Drive 自动绑定、改代码/调超参灵活续训、`--strict-resume` 拦截、损坏快照回退、掉挂载拒绝假写入、多目录工作区同步恢复。
2. `.gitignore` 屏蔽了大权重/日志/缓存，`launch.json` 与 `.sh` 脚本（纯 `LF` 换行）语法解析无误。
3. ZIP 打包脚本包含所有递归子目录且 CRC 校验无误；Notebook JSON 与单元格语法合法。
