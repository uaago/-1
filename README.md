# 本地开发 → GitHub 秒级拉取 → Colab 训练 → Drive 持久同步 → 断点续训

这是一个面向科研多文件工程的 Colab 远程训练模板项目。针对 Colab 只能通过 `.ipynb` 启动、右键上传零散文件夹慢、随时可能断线或需要中途停下调试修改代码/超参的痛点，提供：

- **标准多目录科研工程结构**：支持 `models/`、`datasets/`、`utils/` 等多层子包导入 `train.py`，所有子目录文件自动递归追踪、打包和备份。
- **GitHub 高速同步 + Google Drive 白名单持久化**：
  - 本地通过 `.gitignore` 屏蔽 `_verification/`、`dist/`、`runs/` 和 `__pycache__/`，用 VS Code `Commit & Push` 秒级推送到 GitHub。
  - 云端虚拟机通过 `git clone --depth 1` / `git pull` 秒级拉取到 `/content/github_repo`，再由第 3 步通过 SHA-256 增量白名单筛选核心源码与配置同步至 Google Drive `Colab_Training_Demo/project_workspace/`（自动忽略 `.git/`、文档与测试目录）；无网络时也可直接从 Drive 备份恢复工程。
  - `train.py` 自动检测 `.git` 并将当前 `git_commit` 记录到每次实验的 `code_version.json`。
- **Step/Batch 级安全中断与中间状态保存**：支持 `--stop-after-step`、`checkpoint_every_steps`、`checkpoint_every_seconds` 及点击单元格停止（`SIGINT`/`SIGTERM`）——会在**当前 Batch 完成后立即保存**完整断点（含精确的 Batch 内采样顺序与随机数状态）、`intermediate_state.pt`（batch loss、梯度范数、验证预测样本、进度快照）和 `last_model.pt`，并同步至 Drive。
- **灵活调试与改代码/改参续训**：默认 `--resume auto` 允许修改 `.py` 代码或调整学习率（`--lr`）、总轮数（`--epochs`）、`batch_size`（`--batch-size`）后直接续训（打印 `[resume-debug]` 变更记录并更新 `source.zip` 与 `code_version.json`）；需要严格校验时可显式加 `--strict-resume`。

## 先认清两个入口

- 本地 `.py` 的 Python 解释器：负责本地补全、检查和本地测试。可以继续选择你已有的 `Jupyter` 环境。
- **`启动Colab.ipynb` 右上角的 Kernel：选择 Colab，负责云端运行。** 普通 `.py` 的解释器不需要也不能通过这里变成 Colab。

启动笔记本通过 `sys.executable -u -m colab_training_demo.train` 启动独立云端进程，导入的 `models/`、`datasets/`、`utils/` 全部在云端执行。每次点击 `launch_training()` 都会开启新进程，更新代码后无需重启笔记本内核。

## 第一次照着操作

### 1. 固定本地项目位置与 GitHub 仓库

在 VS Code 用“文件 → 打开文件夹”打开当前目录：

```text
D:\DesktopFILES\云端colab远程项目
```

项目自带 `.vscode/settings.json` 与 `.gitignore`。推荐先将本项目推送到你的 GitHub 仓库（新项目可在 VS Code 源代码管理面板直接点 `Publish to GitHub` / `Publish Branch` 自动建库；若已在网页建好空仓库，终端执行 `git remote add origin <仓库URL>` + `git push -u origin main` 关联）。

> **提示**：仓库名与项目目录尽量使用纯英文且不要以 `-` 开头；若为公开仓库切勿提交密钥或私人数据；科研未公开项目建议使用私有仓库 + GitHub 只读 Token。

### 2. 连接 GPU 服务器与挂载 Drive

1. 打开根目录 **`启动Colab.ipynb`**，右上角选择 `Select Kernel → Colab → New Colab Server → 可用 GPU → Standard → Python 内核`。
   - **选卡建议**：A100 与 L4 均默认选择 **`Standard`** 即可（A100 `Standard` 已包含满血 40GB 显存和约 83GB 主机内存；`High-RAM` 仅增大 CPU 内存且配额极少，极易连接失败）。晚高峰抢不到 A100 时可选 **`L4 + Standard`**，跨卡可凭同一 `RUN_ID` 无缝续训。
2. 运行笔记本 **第 1 步**，确认云端 Linux 环境与 `CUDA 可用: True`。
3. 运行笔记本 **第 2 步**，按浏览器弹窗完成 Google 授权并验证读写。成功后持久目录为：
   - 训练输出：`/content/drive/MyDrive/Colab_Training_Demo/runs/`
   - 代码工作区：`/content/drive/MyDrive/Colab_Training_Demo/project_workspace/`

> **为什么新连接或断线重连后要再跑第 2～4 步？** 每次分配的新 Colab 实例相当于一台空白虚拟机，没有绑定你的个人云盘。跑第 2 步完成授权挂载、拉取代码并跑第 3 步同步、跑第 4 步注册 `RUN_ID` 与 `launch_training()` 后，直接**跳过第 5 步**运行第 7 步即可从云盘接续上次进度。

### 3. 拉取代码并自动白名单同步至 Drive

根据网络和个人习惯，有 **3 种**代码上云方式（推荐方式 A）：

- **方式 A（GitHub 秒级拉取，最推荐）**：
  1. 在第 3 步上方单元格运行 `git clone --depth 1 <REPO_URL> /content/github_repo`（若目录已存在则自动执行 `git pull --ff-only`）。
  2. 第 3 步指定 `PROJECT = Path("/content/github_repo")`，运行后会自动把训练必需文件按 SHA-256 增量同步到 `DRIVE_WORKSPACE`（不混入 `.git/` 等无关文件），并检查安装依赖。
  3. 以后每次本地改完代码：VS Code `Commit & Sync Changes` 推送 → Colab 运行 Git 拉取格 + 第 3 步（约 1～2 秒完成全部更新）。
- **方式 B（Drive 免重传自动恢复）**：
  若曾同步过 `DRIVE_WORKSPACE` 且换了新机器未拉 GitHub，将第 3 步设回 `PROJECT = None` 并保持 `/content` 下无其它源码副本，第 3 步会自动从 `DRIVE_WORKSPACE` 拉回工程到 `/content/colab_training_project`。
- **方式 C（VS Code 右键上传或单 ZIP 备用）**：
  若无法使用 GitHub，可在本地运行 `build_colab_zip.py` 生成单文件 `dist/colab_training_demo.zip` 上传解压，或右键上传 `colab_training_demo/`、`configs/`、`requirements-colab.txt`。

### 4. 分段演练与 Step/Epoch 级续训

运行笔记本 **第 4 步**定义 `TASK`、`RUN_ID` 与 `launch_training()`，随后：

1. 运行 **第 5 步**（首次演示 `--stop-after-epoch 3`；也可切为 `--stop-after-step 40 --checkpoint-every-steps 20` 体验 Batch 级停止）。
   - **防覆盖保护**：若云盘 `runs/` 下已存在同名 `RUN_ID`，不带 `--resume auto` 的第 5 步会抛出 `FileExistsError` 阻止覆盖。要接续旧实验请**直接跳过第 5 步运行第 7 步**；要开新实验请去第 4 步更换 `TASK` 或 `RUN_ID`（如 `demo_002`）并运行第 4 步。
2. 运行 **第 6 步**，查看本地与 Drive 中的快照目录、`status.json` 及 `intermediate_state.pt` 中间状态。
3. 运行 **第 7 步**执行 `launch_training("--resume", "auto")`，从停止的 Epoch 或精确的 Batch 位置继续训练至完成（如已跑完 12 轮或 30 轮想继续往后训，需追加更大的 `--epochs`，如 `launch_training("--resume", "auto", "--epochs", "50")`）。
4. 运行 **第 8 步**绘制损失曲线并保存到 Drive。

## 日常调试、改代码与断线恢复

| 场景 | 操作 |
|---|---|
| 本地改代码后云端续训 | VS Code `Commit & Sync Changes` → Colab 运行 Git 拉取格 + 第 3 步 → 直接运行第 7 步 `--resume auto` |
| 随时点击停止调试 | 点击第 4/5/7 步运行中单元格的停止按钮（发送 `SIGINT`），训练将在**当前 Batch 完成后立即存盘并同步 Drive** |
| 按固定步数保存 | 在配置中设置 `"checkpoint_every_steps": 50` 或传入 `--checkpoint-every-steps 50` |
| 调试期修改超参数续训 | 直接传参覆盖，例如 `launch_training("--resume", "auto", "--lr", "0.001", "--epochs", "20", "--batch-size", "128")` |
| 严格锁定代码与配置 | 追加 `"--strict-resume"`，任何源码或关键超参变动都会拒绝续训并提示使用原 `source.zip` |
| 原运行时已被回收 / 换新卡 | 新连运行时，保持 `RUN_ID` 不变，顺序执行第 1～2 步 → Git 拉取格 + 第 3 步 → 第 4 步 → **跳过第 5 步直接执行第 7 步** |
| 同运行时网络闪断排查 | 先执行第 9 步检查云端 `train.py` 进程，确认旧进程已退出再执行第 7 步 |
| 训练结束省计算单元 | 在 Colab 网页“正在进行的会话”找到对应 `未知笔记本 | GPU`，点击垃圾桶图标终止实例；长训期间建议把本机 Windows 睡眠设为“从不” |

> **注意**：`task`、`seed`、`train_samples`、`val_samples`、`hidden_size` 属于模型结构与数据集定义键，修改这些结构键时仍要求更换新的 `RUN_ID` 新建实验。

## 多目录工程结构与输出布局

```text
本地项目/
├── 启动Colab.ipynb                    # 云端启动、GitHub 拉取、Drive 挂载与代码同步入口
├── Colab远程科研训练_SKILL指南.md      # 小白速查手册 + AI 工程改造规范
├── .agents/skills/colab-remote-training/SKILL.md  # Agent 自动加载 Skill
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
├── project_workspace/                 # 自动白名单同步的多目录核心源码副本（不含 .git/、tests/ 等杂物）
└── runs/<RUN_ID>/
    ├── config.json
    ├── code_version.json              # 含历次续训源码哈希、git_commit 与超参变更 history
    ├── source.zip                     # 最新源码多目录归档
    ├── environment.json
    ├── status.json
    ├── metrics.csv                    # 完整全轮次指标记录（永久保留）
    ├── evaluation.json
    ├── intermediate_state.pt          # 最新进度、batch loss、grad_norm、val 预测样本等中间状态
    ├── last_model.pt                  # 最新一次保存时的模型权重
    ├── best_model.pt                  # 最佳验证损失对应的推理权重（永久保留）
    ├── final_model.pt                 # 达到总 epochs 后生成
    ├── loss_curve.png
    └── checkpoints/                   # 默认按 keep_last=3 滚动保留最新 3 个完整断点防损坏
        ├── epoch_00000011/            # 完整 Epoch 快照
        └── epoch_00000011_step_00000360/  # Step/Batch 级中断快照
            ├── state.pt               # 含模型、优化器、调度器、RNG 及精确的 in_epoch 采样状态
            ├── metrics.csv
            └── complete.json          # SHA-256 完成标记
```

## ZIP 网页备用路线

如果 VS Code 登录或 Git 网络受限，可在网页 Colab 运行：

1. 本地运行 `build_colab_zip.py` 生成 `dist/colab_training_demo.zip`（自动包含 `models/`、`datasets/`、`utils/`）。
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

4. 第 3 步设回 `PROJECT = None` 后继续运行第 3～8 步。

## WSL2 / Linux / macOS 进阶：`google-colab-cli` 免 `.ipynb` 命令行启动

如果你在 WSL2（Ubuntu）、Linux 或 macOS 终端中操作，官方 `google-colab-cli` 可以不打开 `.ipynb` 笔记本，直接通过 `colab new` + `colab drivemount` + `colab ssh` 驱动本项目同一套 `train.py` 与 Google Drive 存档（且两者云盘检查点 100% 互通）：

1. **在 WSL2（Ubuntu 20.04）安装**：官方要求 Python `>= 3.12`，建议使用 `uv` 自动独立托管 Python 3.12（避免与 Ubuntu 20.04 自带 Python 3.8 冲突）：
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   export PATH="$HOME/.local/bin:$PATH"
   uv tool install --python 3.12 google-colab-cli
   ```
2. **使用仓库自带的一键脚本 [scripts/colab_cli_train.sh](scripts/colab_cli_train.sh)**：
   ```bash
   cd /mnt/d/DesktopFILES/云端colab远程项目
   # 首次运行（分配 L4 GPU、引导 Drive 授权挂载、拉取 GitHub 并跑完自动释放实例）
   bash scripts/colab_cli_train.sh --gpu L4 --task classification --run-id cls_cli_001 --auto-stop

   # 接着之前笔记本跑过的存档继续在 A100 上训到 70 轮
   bash scripts/colab_cli_train.sh --gpu A100 --task classification --run-id classification_demo_001 -- --resume auto --epochs 70 --lr 0.0005

   # 云端后台运行 + 随时查看 GPU/进程 + 优雅按 Batch 存盘停止
   bash scripts/colab_cli_train.sh --gpu L4 --task regression --run-id reg_bg_001 --detach
   bash scripts/colab_cli_train.sh --status
   bash scripts/colab_cli_train.sh --stop-remote
   ```
3. **每日新开并在 VS Code Remote-SSH 直接打开远程代码与训练（推荐实验室服务器手感）**：
   - 本地 `C:\Users\<用户>\.ssh\config` 已预置动态别名 `colab-active`、`colab-a100`、`colab-l4`、`colab-t4` 与通配符 `colab-s-*`（通过 `wsl.exe` 桥接 `colab ssh --proxy-mode`）。
   - 每天新开机器 2 步直达：
     ```bash
     # 步骤 A（本地 WSL 终端）：按需申请显卡 + 挂载 Drive + GitHub 拉取到 /content/github_repo
     bash scripts/colab_ssh_up.sh --gpu A100   # 或 --gpu L4 / -s colab-s-exp1 --gpu A100
     ```
     接着在 **VS Code 左侧 Remote Explorer → SSH** 点击对应的 **`colab-a100`**（或 `colab-l4` / `colab-active`），打开远程目录 `/content/github_repo`，在 VS Code 远程终端运行：
     ```bash
     # 步骤 B（VS Code Remote-SSH 云端终端）：不写死任务/实验名，直接开跑或续训
     bash scripts/remote_train.sh --task classification --run-id cls_ssh_001
     bash scripts/remote_train.sh --task classification --run-id classification_demo_001 -- --resume auto --epochs 70 --lr 0.0005
     bash scripts/remote_train.sh --task classification --run-id cls_ssh_001 --tmux   # 后台持久化跑
     ```
   - 不再使用时在本地 WSL 运行 `colab stop -s colab-a100` 释放实例即可。

## 本地验证命令

```powershell
& 'E:\Users\lenovo1\anaconda3\envs\Jupyter\python.exe' -m unittest discover -s tests -v
& 'E:\Users\lenovo1\anaconda3\envs\Jupyter\python.exe' build_colab_zip.py
```
