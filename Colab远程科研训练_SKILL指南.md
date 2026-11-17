# Colab 远程多文件科研训练：操作手册 & AI 工程改造 Skill 指南

这份文档既是**你的日常使用速查手册**，也是**可以直接发给其他 AI 的标准改造规范（Skill）**。下次你在本地写好一个新的科研核心程序想搬上 Google Colab 跑时，直接把这份文档（或仓库里的 [.agents/skills/colab-remote-training/SKILL.md](.agents/skills/colab-remote-training/SKILL.md)）交给 AI 照着改造即可。

---

## 第一部分：核心架构一图流（GitHub + Colab + Drive 三端闭环）

整套工作流由 **“本地开发 → GitHub 秒级同步 → `.ipynb` 前台遥控 → Colab 后台多目录训练 → Google 云盘双端持久归档”** 组成：

```text
你的本地 VS Code 电脑（写代码、跑本地单元测试）
 ├── Commit & Push (1秒) ──► GitHub 仓库（如 https://github.com/uaago/-1.git，由 .gitignore 屏蔽缓存/结果）
 └── 启动Colab.ipynb（前台遥控面板：只有 .ipynb 能连 Colab GPU 内核）
       ├── 第 1 步：确认云端 Linux + CUDA/GPU
       ├── 第 2 步：授权挂载 Google Drive (/content/drive)
       ├── 新增 Git 格：git clone --depth 1 / git pull ──► 拉取到高速盘 /content/github_repo（1~2秒）
       ├── 第 3 步：SHA-256 增量白名单筛选 ──► 仅把源码/配置同步到云盘 project_workspace（自动忽略 .git/）
       └── 第 4～7 步：在云端虚拟机执行系统命令启动独立进程
             └── python -u -m colab_training_demo.train ...
                   ├── import models/     （网络结构子包）
                   ├── import datasets/   （数据集与加载器子包）
                   ├── import utils/      （代码同步与中间状态诊断工具）
                   ├── 高速临时盘写日志   ──► /content/runs/<RUN_ID>/
                   └── 校验后原子同步云盘 ──► /content/drive/MyDrive/Colab_Training_Demo/runs/<RUN_ID>/
```

### 几个关键原理（用大白话记牢）
1. **为什么不用 `.py` 直接连 Colab？**  
   VS Code 的 Colab 插件规定只有 `.ipynb` 能连云端 GPU。因此固定用 [启动Colab.ipynb](启动Colab.ipynb) 当遥控器，用 `subprocess.Popen` 启动独立 Linux 子进程跑 [colab_training_demo/train.py](colab_training_demo/train.py)。每次启动都是全新子进程，更新代码后**不用重启笔记本内核**。
2. **为什么推荐 GitHub 拉取替代右键 `Upload to Colab`？**  
   右键上传会把零散小文件排队握手上传，很慢；而 Colab 虚拟机在谷歌机房直连 GitHub，`git clone --depth 1` 或 `git pull` 只需 **1～2 秒**。随后第 3 步只会把训练必需文件增量备份进云盘 `project_workspace/`，`.git/`、`docs/`、`_verification/` 一概不会弄乱云盘；同时 `train.py` 会自动读取 `.git` 并把精确的 `git_commit` 版本号写进实验档案 `code_version.json`。
3. **为什么换新 Kernel（重连或换显卡）后必须再跑一遍第 2 → 3 → 4 步，而且第 5 步会拦截已有的 `RUN_ID`？**  
   新分配的 Colab 实例就像一台刚还原的空白电脑：第 2 步插上你的 Google 云盘“移动硬盘”（弹窗点 `Continue` 授权），Git 格/第 3 步把代码拉到新机高速盘，第 4 步注册启动函数。正因为云盘里**已经存有之前跑过的 `RUN_ID` 存档**，为了防止换机器后手滑点第 5 步把心血覆盖清空，系统故意触发 `FileExistsError` 拦住——**接续旧实验请直接跳过第 5 步去点第 7 步！**

---

## 第二部分：日常操作速查表（连接、训练、改代码、断线恢复）

| 步骤 / 单元 | 作用（大白话） | 首次运行 | 改完代码续跑 | 断线换新机器恢复 |
| :--- | :--- | :--- | :--- | :--- |
| **第 1 步** | 检查云端 Linux 和 GPU 显卡 | 必须运行 | 不用重跑 | 必须运行 |
| **第 2 步** | 弹窗授权并挂载 Google Drive | 必须运行 | 不用重跑 | 必须运行 |
| **Git 拉取格** | 执行 `git clone --depth 1` / `git pull` 拉取 `/content/github_repo` | 运行（首次克隆） | 本地 Push 后运行（1 秒 `pull`） | 运行（从 GitHub 1 秒克隆） |
| **第 3 步** | 锁定 `PROJECT`、按 SHA-256 白名单增量备份到云盘并装依赖 | 必须运行 | 运行（只更新改动的文件） | 必须运行（若无网络可改 `PROJECT = None` 自动从云盘恢复） |
| **第 4 步** | 选定 `TASK` 和存档名 `RUN_ID`，定义 `launch_training()` | 必须运行 | 不用重跑（除非换实验名） | 必须运行（**续训绝不改 `RUN_ID`**） |
| **第 5 步** | **开新实验按钮**（从第 1 轮开跑，已有同名存档会拒绝覆盖） | 运行一次 | **跳过！** | **跳过！** |
| **第 6 步** | “验货器”：查当前到第几轮、完整快照标记、`intermediate_state.pt` | 可选运行 | 可选运行 | 可运行确认已跑轮数 |
| **第 7 步** | **断点续训按钮**（`--resume auto` 自动加载最新完好快照续跑） | 运行跑完后续轮次 | **直接点运行（自动识别新代码/新参数）** | **直接点运行（跨机器/跨显卡接力）** |
| **第 8 步** | 绘制 1～最新轮次的 Loss 曲线并保存 `loss_curve.png` 到云盘 | 跑完后运行 | 跑完后运行 | 跑完后运行 |
| **第 9 步** | 云端“任务管理器”：网络闪断时检查后台是否还有 `train.py` | 不用运行 | 不用运行 | 仅网络卡顿不确定是否中断时运行 |

---

## 第三部分：选卡、GitHub、省钱与常见疑问速查

### 1. GitHub 操作避坑 4 条
- **仓库命名**：新建仓库和项目文件夹尽量用**纯英文简短命名，且不要以短横线 `-` 开头**（例如 `my-rl-project`）。若仓库名特殊，在 `git clone` 末尾务必显式指定干净的目标目录名，例如 `/content/github_repo`。
- **VS Code 建库快捷键 vs 已有仓库**：
  - 本地尚未绑定远程仓库时，VS Code 源代码管理面板的 **`Publish to GitHub` / `Publish Branch`** 会自动在 GitHub 建库并推送，以后新项目无需先去网页手动建空仓库；
  - 若已在网页建好空仓库（如 `https://github.com/uaago/-1.git`），只需在终端执行一次 `git remote add origin <URL>` 和 `git push -u origin main`，以后全用鼠标点 **`Commit` → `Sync Changes`**。
- **公开仓库 vs 私有仓库**：
  - 公开仓库（Public）拉取免密，但**绝不能提交 API Key、密码或私人数据**；
  - 科研未发表项目建议用 **私有仓库（Private）**，在 GitHub 生成仅含 `Contents: Read-only` 权限的 Fine-grained Token，在 Colab 用 `getpass` 或 Colab Secrets 传入：`https://oauth2:{token}@github.com/用户名/仓库名.git`。
- **防冲突**：使用 `/content/github_repo` 时，第 3 步建议明确设置 `PROJECT = Path("/content/github_repo")`，避免同一虚拟机同时存在 Git 目录与 Drive 恢复目录时触发多副本校验报错。

### 2. Colab 选卡、防掉线与省计算单元技巧
- **A100 选 `Standard`，别乱点 `High-RAM`**：`Standard` vs `High-RAM` 指的是 CPU 主机内存，**不是 GPU 显存**。A100 `Standard` 默认自带满血 40GB 显存和约 83.5 GB 主机内存；选 `High-RAM` 极易因特殊资源池缺货而连接失败。晚高峰抢不到 A100 时改选 **`L4 + Standard`**，同一 `RUN_ID` 可跨显卡（如 T4 / L4 / A100）直接接力续训。
- **防止本机休眠导致误断线**：长训练期间把 Windows 电源设置中“接通电源时使设备进入睡眠状态”改为**从不**，避免本机断网失联超过超时阈值后被 Colab 回收实例。
- **及时关机省计算单元**：本地 VS Code 连着的实例在 Colab 网页端会显示为 **`未知笔记本 | GPU`**。训练结束不再使用时，在 Colab 网页“正在进行的会话”弹窗点击垃圾桶图标 🗑️ 终止实例，避免待机按小时继续扣除计算单元。

### 3. 训练存档与参数速查
- **为什么云盘 `checkpoints/` 只显示最近 3 个目录？**  
  这是配置 `"keep_last": 3` 的滚动保留机制，防止撑爆云盘并防止最新快照上传半截损坏时无版本可回退。**`best_model.pt`、`final_model.pt`、`last_model.pt`、`intermediate_state.pt` 和全程完整的 `metrics.csv` 全部永久保留**。
- **如何在第 7 步不重头跑、直接多训几轮或调参？**  
  直接在 `launch_training` 追加参数覆盖配置文件（总轮数需大于已完成轮数）：
  ```python
  launch_training("--resume", "auto", "--epochs", "50", "--lr", "0.0005", "--batch-size", "128")
  ```
- **开新实验 / 切换任务**：去第 4 步修改 `TASK` 或 `RUN_ID`（如 `RUN_ID = f"{TASK}_demo_002"`），运行第 4 步后点第 5 步从第 1 轮开始（每个 `RUN_ID` 在云盘 `runs/` 下各自独立成目录，互不干扰）。

---

## 第四部分：给 AI 看的工程改造规范（新项目本地写完迁移到 Colab 时使用）

> 当我在本地完成一个新科研项目的核心算法开发，准备搬到 Colab 运行时，你可以直接对 AI 说：**“请按 `Colab远程科研训练_SKILL指南.md` 第四部分（或 `.agents/skills/colab-remote-training/SKILL.md`）的标准，为我这个新项目搭建 Colab 启动器、GitHub + Drive 双端代码同步与 Step/Epoch 断点续训系统。”**

### 新科研项目必须适配的 7 条工程规范

1. **多目录工程结构与独立子进程入口**
   - 将核心科研代码组织为标准 Python 包（如 `<pkg>/models/`、`<pkg>/datasets/`、`<pkg>/utils/`、`<pkg>/checkpoint.py`、`<pkg>/train.py`），`train.py` 通过包内相对导入组装各模块。
   - 配套根目录 `.gitignore`，屏蔽 `__pycache__/`、`*.py[cod]`、`dist/`、`runs/`、`_verification/`、`.ipynb_checkpoints/`，确保 GitHub 只同步轻量源码、配置与文档。
   - 固定提供 `启动Colab.ipynb` 作为前台遥控器，按序完成：**环境自检 → Drive 挂载与写入探针 → GitHub `clone --depth 1` / `pull` + 白名单同步到 Drive `project_workspace`（无网/未上传时从 Drive 兜底恢复）→ 注册 `RUN_ID` 与 `launch_training()`**，并通过 `subprocess.Popen([sys.executable, "-u", "-m", "<pkg>.train", ...])` 启动独立云端训练进程，捕获 `KeyboardInterrupt` 并向子进程转发 `SIGINT`。

2. **双盘隔离与防伪云盘校验**
   - 本地临时盘（`/content/runs/<RUN_ID>`）：存放数据缓存、逐轮/逐步 `metrics.csv` 和本地快照。
   - 持久盘（`/content/drive/MyDrive/<Project>/runs/<RUN_ID>`）：禁止本地与持久目录重合或互相嵌套；每次写入 `/content/drive` 前校验 `os.path.ismount("/content/drive")` 与 `MyDrive` 目录存在，绝不在掉挂载后写入本地容器伪目录。

3. **白名单代码同步与版本溯源**
   - 启动器第 3 步通过 `iter_project_files` 只将核心 `.py`、配置 `.json`、依赖列表等文件按 SHA-256 增量同步至 Drive `project_workspace`，自动忽略 `.git/`、`tests/`、`docs/` 等目录。
   - `train.py` 递归计算所有子包源码 SHA-256 并自动检测 `.git` 记录 `git_commit`，打包 `source.zip` 与维护含变更 `history` 的 `code_version.json`。

4. **原子检查点、SHA-256 完成标记与损坏回退**
   - 完整轮次目录：`checkpoints/epoch_{epoch:08d}/`；Step/Batch 中途目录：`checkpoints/epoch_{completed_epoch:08d}_step_{global_step:08d}/`。
   - 先写临时目录里的 `state.pt` 与 `metrics.csv` 快照，再写哈希清单 `complete.json`，最后 `os.replace` 发布；上传 Drive 先写 `.uploading` 并二次校验，最后再传 `complete.json`。
   - 恢复时按 `(epoch_num, step_num)` 倒序加载首个完整有效的快照，跳过损坏版本并重建 `metrics.csv`；Drive 备份成功后才执行 `prune(keep_last)`。

5. **Step/Batch 级安全中断与中间诊断状态保存**
   - 捕获 `SIGINT`/`SIGTERM`，收到停止信号或触发 `--stop-after-step` / `checkpoint_every_steps` / `checkpoint_every_seconds` 时，在**当前 Batch 完成后立即保存**并同步 Drive 后安全退出。
   - `state.pt` 须保存模型、优化器、调度器、`epoch`、`global_step`、`best_*`、Python/NumPy/Torch/CUDA/采样器随机状态 `rng`，以及 `in_epoch`（`current_epoch`、`completed_batches`、`total_batches`、`order`、`total_loss`、`seen_samples`）。如使用 AMP 额外保存 `GradScaler`，如为强化学习额外保存环境统计与 Replay Buffer 游标。
   - 每次保存同步输出 `last_model.pt`、`best_model.pt`（存在时）、`final_model.pt`（完成时）和 `intermediate_state.pt`（含 `batch_loss`、`grad_norm`、`learning_rate`、`val_loss`、验证集预测样本与 `custom_state`）。

6. **灵活调试续训与防覆盖保护**
   - 默认 `--resume auto` 允许修改 `.py` 代码及可调超参（`--lr`、`--epochs`、`--batch-size`、`--checkpoint-every-steps`），自动打印 `[resume-debug]` 变更并动态更新优化器 `param_groups` 与调度器 `base_lrs`；结构性字段（任务、种子、样本量、网络骨架尺寸）变化或显式传入 `--strict-resume` 时拒绝续训。
   - 不带 `--resume auto` 启动且本地或云盘已存在同名 `RUN_ID` 时，必须抛出 `FileExistsError` 拦截覆盖。

7. **进程锁与本地自动化测试**
   - 使用 `sqlite3.connect(..., timeout=0)` + `BEGIN EXCLUSIVE` 保护本地实验目录防并发。
   - 提供完整 `unittest`：验证 Epoch 级与 Mid-Epoch Step 级中断恢复逐位一致、改代码/调超参灵活续训、`--strict-resume` 拦截、损坏快照回退、Drive 掉挂载拒绝假写入、多目录工作区同步恢复以及 ZIP/Notebook 校验。

---

## 第五部分：WSL2 + `google-colab-cli` 免 `.ipynb` 命令行/SSH 进阶模式

如果你电脑有 **WSL2（如 Ubuntu 20.04）**，除了在 Windows VS Code 里点 `启动Colab.ipynb`，还可以使用官方 [google-colab-cli](https://github.com/googlecolab/google-colab-cli) 直接在终端操控远程 GPU（**无需改造 `train.py`，与 `.ipynb` 共享同一个 Google Drive 存档目录**）：

### 1. WSL2（Ubuntu 20.04）一次安装注意点
- 官方 `google-colab-cli` 要求 **Python >= 3.12**，而 Ubuntu 20.04 系统自带 Python 是 3.8，直接 `pip install` 会报错。
- 推荐按官方推荐用 `uv` 安装（自动带独立 Python 3.12，不动系统环境）：
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  source ~/.local/bin/env 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"
  uv tool install --python 3.12 google-colab-cli
  ```

### 2. 一键脚本 [scripts/colab_cli_train.sh](scripts/colab_cli_train.sh) 帮你自动串起了官方全链路
脚本封装了官方推荐的标准生命周期：`colab new` → `colab drivemount`（若终端未自动弹出浏览器，复制终端链接到 Windows 浏览器授权即可）→ `colab upload` 上传临时作业脚本 → `colab ssh` 执行 GitHub 拉取、白名单同步与 `train.py` → 可选 `colab stop`：
```bash
cd /mnt/d/DesktopFILES/云端colab远程项目

# 1) 申请 L4，跑完后自动停机释放计算单元（再也不怕忘关机扣额度）
bash scripts/colab_cli_train.sh --gpu L4 --task classification --run-id cls_cli_001 --auto-stop

# 2) 用 A100 续训之前在启动笔记本跑过的实验（无缝互通）
bash scripts/colab_cli_train.sh --gpu A100 --task classification --run-id classification_demo_001 -- --resume auto --epochs 70

# 3) 后台挂起训练 / 查余额与 nvidia-smi / 发送 SIGINT 优雅存盘停止
bash scripts/colab_cli_train.sh --gpu L4 --detach
bash scripts/colab_cli_train.sh --status
bash scripts/colab_cli_train.sh --stop-remote
```

### 3. VS Code Remote-SSH 每日新开与直连方案（像实验室服务器一样用）
- Windows `~/.ssh/config`（`C:\Users\lenovo1\.ssh\config`）与 WSL2 `~/.ssh/config` 已配置好**不写死会话**的动态别名：
  - `colab-active`：自动连向当前唯一在跑的任意会话（如手头正开着的 `test1`）；
  - `colab-a100` / `colab-l4` / `colab-t4`：每次点击自动复用或按需新开对应显卡；
  - `colab-s-*`：通配符别名（如 `colab-s-exp1`）可同时开多个独立命名会话。
- **每天新开显卡跑实验只需 3 步**：
  1. **准备机器与云盘**（在本地 WSL 终端运行）：
     ```bash
     bash /mnt/d/DesktopFILES/云端colab远程项目/scripts/colab_ssh_up.sh --gpu A100   # 或 --gpu L4
     ```
     它会自动创建对应名称会话（`colab-a100` / `colab-l4`）、挂载 `/content/drive`、拉取最新 GitHub 代码到 `/content/github_repo` 并同步 Drive `project_workspace`。
  2. **VS Code 一键连入**：点 VS Code 左侧 Remote Explorer → SSH → **`colab-a100`**（或 `colab-l4` / `colab-active`），打开远程目录 **`/content/github_repo`**。
  3. **在远程终端启动或续训**（利用 [scripts/remote_train.sh](scripts/remote_train.sh)，不写死参数且自动同步代码到 Drive）：
     ```bash
     bash scripts/remote_train.sh --task classification --run-id cls_ssh_001
     bash scripts/remote_train.sh --task classification --run-id classification_demo_001 -- --resume auto --epochs 70 --lr 0.0005
     bash scripts/remote_train.sh --task regression --run-id reg_ssh_001 --tmux
     ```
  4. **结束省额度**：在 WSL 执行 `colab stop -s colab-a100` 释放虚拟机。

### 4. 官方 CLI 常用指令速查
- `colab new -s <名> --gpu A100`：新建标准 A100 实例（默认不加 `--high-mem` 即 Standard 83.5GB 内存；L4 忽略 `--high-mem`）。
- `colab drivemount -s <名>`：挂载 `/content/drive`。
- `colab ssh -s <名>`：直接打开交互式云端 Linux 终端（可实时跑 `watch -n 1 nvidia-smi`）。
- `colab usage` / `colab stop -s <名>`：查看计算单元余量与手动销毁虚拟机。
