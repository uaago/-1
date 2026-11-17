# Colab 远程多文件科研训练：操作手册 & AI 工程改造 Skill 指南

这份文档既是**你的日常使用速查手册**，也是**可以直接发给其他 AI 的标准改造规范（Skill）**。下次你在本地写好强化学习（PPO/SAC 等）或深度学习新项目准备搬到 Colab 上跑时，直接把这份文档（或仓库里的 [.agents/skills/colab-remote-training/SKILL.md](.agents/skills/colab-remote-training/SKILL.md)）交给 AI 照着接入即可。

---

## 第一部分：核心架构一图流（Local + GitHub + Colab Remote-SSH + Drive）

```text
本地 Windows VS Code（写核心算法、跑本地单元测试）
 ├── Commit & Push (1秒) ──► GitHub 仓库（.gitignore 屏蔽 runs/、_verification/、__pycache__/、*.pt）
 │
 ├──【日常主力路线：VS Code Remote-SSH】全局配置在 C:\Users\lenovo1\.ssh\config（新开任何 VS Code 都有）
 │     ├── 本地 WSL：colab new -s colab-a100 --gpu A100  ──► 申请算力（没货换 colab-l4）
 │     ├── 本地 WSL：colab drivemount -s colab-a100      ──► 授权挂载 /content/drive
 │     ├── VS Code 点 colab-a100 / colab-l4 / colab-active 连入云端（连接后可关掉独立 WSL 黑框）
 │     └── 在云端 /content/github_repo 直接改代码、按 ▷ / F5 调试、或运行 scripts/remote_train.sh --tmux
 │
 └──【备选遥控路线：启动Colab.ipynb】无需 WSL2/SSH，支持画曲线图（第 8 步）
       └── 依次运行 1 → 2 → Git 拉取 → 3 → 4 → 5/7 → 8
             │
             ▼ 两条路线最终跑的是同一套引擎 & 读写同一个云盘目录
      python3 (-m) colab_training_demo.train
        ├── import models/、datasets/、utils/（支持直接点 ▷ 运行且自动识别挂载的 Google Drive）
        ├── 高速临时盘：/content/runs/<RUN_ID>/
        └── Google 云盘：/content/drive/MyDrive/<Project>/runs/<RUN_ID>/
```

---

## 第二部分：日常最常用流程（VS Code Remote-SSH 实验室手感）

### 1. 我新开一个 VS Code 窗口 / 新科研项目，还有这些 Remote-SSH 选项吗？
**有！永久都有！**
* 因为 `colab-active`、`colab-a100`、`colab-l4`、`colab-t4`、`colab-s-*` 已经保存在你的 Windows 全局 SSH 配置 `C:\Users\lenovo1\.ssh\config` 里（不在单个项目里），**以后你新开任何 VS Code 窗口或任何新项目**，左侧 **Remote Explorer (`SSH`)** 里永远都会直接列出这几个主机：
  * **`colab-a100` / `colab-l4` / `colab-t4`**：每次点击自动复用或新开对应 GPU 实例；
  * **`colab-active`**：自动连当前唯一在跑的任意会话；
  * **`colab-s-*`**：需要同时开多台独立命名机器时使用（如 `colab-s-rl1`）。

### 2. 每天新开一台 GPU 服务器跑训练的标准 5 步
1. **在本地 WSL 终端开卡并查残留**（请用 **`Windows Terminal`** 或 **VS Code 集成 WSL 终端**，避免旧黑框误触`选择`卡死和右键失效）：
   ```bash
   colab sessions                         # 若看到 [?] 残留且不再用，去 Colab 网页点垃圾桶关掉省配额
   colab new -s colab-a100 --gpu A100     # 抢不到 A100 就改开 colab new -s colab-l4 --gpu L4
   colab drivemount -s colab-a100         # 浏览器选同一 Google 账号点允许，看到提示后回终端按 Enter
   ```
2. **用 VS Code Remote-SSH 连进去**：
   左侧 **Remote Explorer (`SSH`)** 点刷新 `↻` → 点 **`colab-a100`**（或 `colab-l4`）右侧连接箭头（选 `Linux`）。
   *(连上新机器若弹出安装扩展推荐，点 **`Show Recommendations`** 只装 **`Python` (`ms-python.python`)** 即可，不用装 `Google Colab` 插件。)*
3. **拉取 GitHub 代码并打开远程目录**：
   在远程 VS Code 终端（`Ctrl + ~`）首次执行：
   ```bash
   git clone --depth 1 https://github.com/你的用户名/你的仓库.git /content/github_repo
   ```
   接着在左侧点 **Open Folder → `/content/github_repo`**（以后本地更新推上 GitHub 后，远程终端直接敲 `git pull` 即可）。
4. **直接点运行或开跑训练**（3 种方式任选，均自动保存权重和中间状态到 Google Drive）：
   - **直接点右上角 `▷` 运行 `train.py`（或按 `F5` 使用 [.vscode/launch.json](.vscode/launch.json) 断点调试）**：交互选任务/实验名，检测到已有存档自动提示续训，且检测到 `/content/drive/MyDrive` 已挂载会自动同步到云盘！
   - **短脚本命令（支持 `--tmux` 挂后台防断线）**：
     ```bash
     bash scripts/remote_train.sh --task classification --run-id cls_ssh_001 --tmux
     bash scripts/remote_train.sh --task classification --run-id classification_demo_001 -- --resume auto --epochs 65
     ```
   - **单行 Python 命令（不要加反斜杠 `\` 换行，防复制多出空格切断）**：
     ```bash
     python3 -u -m colab_training_demo.train --config configs/classification.json --run-id classification_demo_001 --local-root /content/runs --persistent-root /content/drive/MyDrive/Colab_Training_Demo/runs --device cuda --resume auto --epochs 65
     ```
5. **用完立即关机省计算单元**：
   ```bash
   colab stop -s colab-a100
   colab usage   # 核对变为 Usage rate: 0.00/hr、Active assignments: 0
   ```

---

## 第三部分：Remote-SSH 稳定性与防踩坑 6 条守则

1. **WSL 黑框可以关，但绝对不要执行 `wsl --shutdown`**：
   VS Code Remote-SSH 自己会在后台托管一条独立的 `wsl.exe ... ProxyCommand` 隧道。连上 VS Code 后可以关掉手动打开的 WSL 窗口不影响连接；但执行 `wsl --shutdown` 会把整个 WSL2 关机并直接掐断 VS Code 连接。
2. **重要长实验务必开 `--tmux`（或 `nohup`）放后台**：
   如果本地网络波动或电脑休眠导致 VS Code 重连，前台终端命令可能中断；放进 `tmux` 后云端进程继续跑并定时同步 Google Drive。重连后 `tmux attach -t train_<RUN_ID>` 即可切回现场。
3. **跑长训关闭 Windows 自动睡眠**：
   接通电源时“使设备进入睡眠状态”改为**从不**，防止本机断网太久被 Colab 判定失联回收实例。
4. **“远程改文件” vs “本地改文件”分清楚**：
   在 `SSH: colab-a100` 里改 `/content/github_repo/` 的代码会立即生效（且训练时打包进云盘 `source.zip`），但机器销毁后临时盘会清空。主力开发建议本地改 → GitHub `Commit & Sync Changes` → 远程 `git pull`；远程临时调好的改动记得推回 GitHub 或拷贝回本地。
5. **防抢不到卡 / 隐形扣费排查**：
   如果申请第二台 A100 一直卡住，跑 `colab sessions` 和 `colab usage`——看到带 `[?]` 的外部会话（如 `.ipynb` 开过忘记删）说明账号下已占着一台 A100 正在每小时扣费，先去 Colab 网页点垃圾桶 🗑️ 删掉。选卡统一选 **`Standard`**，别点 `High-RAM`。
6. **避免多行复制出错**：
   远程终端执行带参数的命令时尽量使用**单行命令**或 `scripts/remote_train.sh`，不要复制带 `\` 换行符的块（尾随空格会让命令断行，导致漏传 `--persistent-root`）。

---

## 第四部分：给 AI 看的工程改造规范（含强化学习 RL 迁移清单）

> 当我在本地把一个新科研项目（例如强化学习 PPO / SAC / TD3 或视觉/大模型微调项目）的核心算法调试通了，准备迁移到 Colab 上云训练时，你可以直接对 AI 说：**“请按 `Colab远程科研训练_SKILL指南.md` 第四部分（或 `.agents/skills/colab-remote-training/SKILL.md`）的标准，为我这个新项目接入 Colab Remote-SSH + GitHub + Google Drive 持久化与 Step/Episode 断点续训系统。”**

### 新项目（含强化学习）接入的 8 条标准

1. **多目录工程与“直接运行 / `-m` 双模式”入口**
   - 保持清晰子包结构（深度学习用 `models/`、`datasets/`、`utils/`；**强化学习建议按 `envs/`、`agents/`、`models/`、`buffers/`、`utils/` 划分**），主程序 `train.py` 顶部加 `__package__` 兜底，保证 `python -m <pkg>.train` 和在 VS Code 里直接点击 `train.py` 的 `▷` / `F5` 都能正常解析相对导入。
   - 配套 `.gitignore`（屏蔽 `__pycache__/`、`*.py[cod]`、`runs/`、`wandb/`、`logs/`、`_verification/`、`dist/`、`*.pt`、`*.pth`、`*.mp4`），确保 GitHub 只同步轻量源码与配置；同时生成 [.vscode/launch.json](.vscode/launch.json) 支持 `F5` 断点调试。

2. **自动绑定 Google Drive 与防伪云盘校验**
   - `train.py` 实现 `_resolve_persistent_root`：当未显式指定 `--persistent-root`（且未传 `--no-persistent`）时，自动检查 `os.path.ismount("/content/drive") and Path("/content/drive/MyDrive").is_dir()`，若已挂载则自动绑定至 `/content/drive/MyDrive/<Project>/runs/<RUN_ID>`；在 Colab 容器但未挂载时发出显式警告；本地运行自动跳过。
   - 禁止 `local_root` 与 `persistent_root` 重合或互相嵌套；每次写入 Drive 前调用 `ensure_persistent_available` 防止掉挂载后写出“假备份”。

3. **多入口配套齐全（兼容 Remote-SSH、笔记本与 CLI）**
   - 提供 `启动Colab.ipynb`（备选/画图遥控器）、`scripts/remote_train.sh`（Remote-SSH 短命令与 `--tmux` 启动）、`scripts/colab_cli_train.sh`（WSL2 一键建机/自动停机）及 `scripts/colab_ssh_up.sh`。

4. **白名单代码同步与版本溯源**
   - 启动时通过 `iter_project_files` 仅同步核心 `.py` 与配置 `.json` 到 Drive `project_workspace`，自动过滤 `.git/` 与缓存目录。
   - `train.py` 递归计算多目录源码 SHA-256 并自动读取 `git rev-parse HEAD`，写入 `code_version.json` 与 `source.zip`。

5. **原子检查点、SHA-256 完成标记与损坏回退**
   - 目录命名：`checkpoints/epoch_{epoch:08d}/` 与 `checkpoints/epoch_{completed:08d}_step_{global_step:08d}/`（RL 可对应 `update` / `episode` 与 `env_step`）。
   - 先写临时目录里的 `state.pt` 与 `metrics.csv`，写入哈希清单 `complete.json` 后 `os.replace` 发布；上传 Drive 先写 `.uploading` 并二次校验，最后才传 `complete.json`。
   - 恢复时按进度倒序加载首个通过 SHA-256 校验的快照，跳过损坏版本并重建 `metrics.csv`；Drive 备份成功后才执行 `prune(keep_last)`。

6. **Step / Update / Batch 级安全中断与中间诊断状态保存（RL 特别注意事项！）**
   - 捕获 `SIGINT`/`SIGTERM`，收到信号或命中 `--stop-after-step` / `checkpoint_every_steps` / `checkpoint_every_seconds` 时，在**当前 Batch / Rollout Update 完成后立即保存**并同步 Drive 后安全退出。
   - **常规项目 `state.pt` 必存项**：模型权重、优化器、LR 调度器、步数/轮数、`best_*`、四套 RNG（Python / NumPy / Torch / CUDA）+ 采样器 RNG、`in_epoch` 断点状态（若用 AMP 须加 `GradScaler.state_dict()`）。
   - **强化学习（RL）迁移额外必存项**：
     - Actor / Critic / Target 网络权重与对应多个优化器状态；
     - 环境归一化统计（如 `VecNormalize` 的 `obs_rms`、`ret_rms`）与环境随机数/课程学习阶段；
     - 探索调度参数（如 `epsilon`、熵系数 `alpha`）；
     - **Replay Buffer 注意事项（重要！）**：On-policy（PPO）的 Rollout Buffer 很小，可随 `state.pt` 保存或在每次 Update 边界保存；Off-policy（SAC/TD3/DQN）的 Replay Buffer（可能达数 GB）不要在每次高频步级存盘时全盘上传 Drive，建议先保存在临时盘 `/content/runs/<RUN_ID>/buffer.pt`，按较长周期（如每 15 分钟或 `SIGINT` 退出时）原子同步到 Drive，或确认新任务允许只恢复策略+统计量。
   - 同步输出诊断产物：`last_model.pt`、`best_model.pt`、`final_model.pt`、`intermediate_state.pt`（记录最新 loss/reward、梯度范数 `grad_norm`、学习率、评估样本和自定义中间字典）。

7. **灵活调试续训与防覆盖保护**
   - 默认 `--resume auto` 允许改 `.py` 源码及可调超参（`--lr`、`--epochs`、`--batch-size`、`--checkpoint-every-steps`），打印 `[resume-debug]` 变更并动态更新优化器 `param_groups` 与调度器 `base_lrs`；结构性字段变化或显式 `--strict-resume` 时拒绝续训。
   - 不带 `--resume auto` 且本地或云盘已有同名 `RUN_ID` 时，必须抛出 `FileExistsError` 拦截覆盖。

8. **进程锁与本地自动化测试**
   - 使用 SQLite 排他文件锁（`sqlite3.connect(..., timeout=0)` + `BEGIN EXCLUSIVE`）保护运行目录。
   - 提供 `unittest` 覆盖：连续 vs Epoch/Mid-Epoch 续训逐位一致、直接执行 `train.py` 脚本路径及自动绑定 Drive 逻辑、灵活调参续训与 `--strict-resume` 拦截、损坏快照回退、掉挂载检查、多目录同步恢复。
