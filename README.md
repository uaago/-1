# 本地开发 → GitHub 秒级拉取 → Colab Remote-SSH / 笔记本训练 → Drive 自动同步 → 断点续训

这是一个面向科研多文件工程（深度学习、强化学习等）的 Colab 远程训练模板项目。提供 **VS Code Remote-SSH 直连**、**`启动Colab.ipynb` 遥控** 与 **WSL2 `google-colab-cli` 脚本** 三种互补入口，全部共用同一套多目录 `.py` 引擎与 Google Drive 持久化存档：

- **标准多目录科研工程结构**：支持 `models/`、`datasets/`、`utils/` 等多层子包导入 `train.py`，同时支持 `-m colab_training_demo.train` 模块启动与直接点击 `train.py` 的 **`▷` / `F5`** 运行调试。
- **Colab 环境自动绑定 Google Drive**：在 Colab 中挂载 `/content/drive` 后，即使直接运行 `python3 colab_training_demo/train.py`（未手动传 `--persistent-root`），程序也会自动绑定 `/content/drive/MyDrive/Colab_Training_Demo/runs/<RUN_ID>`，把权重、检查点、`intermediate_state.pt` 与 `metrics.csv` 全部持久化到云盘；本地调试自动跳过 Drive。
- **GitHub 高速同步 + Google Drive 白名单持久化**：本地通过 `.gitignore` 屏蔽缓存与结果，VS Code `Commit & Sync Changes` 秒推 GitHub；云端通过 `git clone --depth 1` / `git pull` 1 秒拉取，再由 `sync_workspace_to_drive` 按 SHA-256 增量过滤同步核心源码到 Drive `project_workspace/`（自动忽略 `.git/`、`tests/`、`_verification/`）。`train.py` 自动记录 `git_commit` 到 `code_version.json`。
- **Step/Batch 级安全中断与灵活调试续训**：支持 `--stop-after-step`、`checkpoint_every_steps`、`checkpoint_every_seconds` 及 `Ctrl + C` / `SIGINT`——在**当前 Batch 完成后立即保存**完整断点（含 `in_epoch` 采样位置与 RNG）、`intermediate_state.pt` 与 `last_model.pt` 并同步 Drive。默认 `--resume auto` 允许修改 `.py` 代码或调整 `--lr`、`--epochs`、`--batch-size` 后继续训练；开启 `--strict-resume` 可锁定对照实验。

---

## 三种启动方式怎么选？（推荐方式一）

### 方式一：VS Code Remote-SSH 当实验室服务器直连（最直观、支持直接点 `train.py` 的 `▷` / `F5`）

> **跨窗口永久生效**：`colab-active`、`colab-a100`、`colab-l4`、`colab-t4`、`colab-s-*` 已配在 Windows 全局 `C:\Users\<用户>\.ssh\config` 中。**以后你新开任何 VS Code 窗口、做任何新科研项目（如强化学习），左侧 Remote Explorer → SSH 里都会一直有这些选项。**

1. **在本地 WSL 终端（推荐用 `Windows Terminal` 或 VS Code 下方 WSL 标签）开卡并挂载云盘**：
   ```bash
   colab sessions                         # 先确认没有残留的 [?] 或旧实例占配额
   colab new -s colab-a100 --gpu A100     # 优先抢 A100 Standard；缺货可换 colab new -s colab-l4 --gpu L4
   colab drivemount -s colab-a100         # 弹浏览器点同意，看到 Please close this tab 后回终端按 Enter
   ```
2. **用 VS Code Remote-SSH 连上服务器**：
   - 在左侧 **Remote Explorer (`SSH`)** 点刷新 `↻`，点击 **`colab-a100`**（或 `colab-l4`、`colab-active`）右侧连接箭头（选 `Linux`）。
   - 首次连接该远程机器时，按右下角弹窗点 **`Show Recommendations`** 只安装 **`Python` (`ms-python.python`)** 扩展即可。
   - **稳定性说明**：VS Code 连接成功后会自己在后台托管 `wsl.exe` 隧道进程，**此时可以安全关掉你手工打开的 WSL 黑框窗口**，不会影响 VS Code；但**千万不要执行 `wsl --shutdown`**，否则会掐断后台隧道！
3. **拉代码并开始训练（3 种启动方式任选）**：
   在远程终端（`Ctrl + ~`）首次执行：
   ```bash
   git clone --depth 1 https://github.com/uaago/-1.git /content/github_repo
   ```
   然后用 VS Code **Open Folder** 打开 `/content/github_repo`（以后本地改完推 GitHub 后，远程只需 `git pull`）。之后你可以：
   - **直接点 `colab_training_demo/train.py` 右上角 `▷`（或按 `F5` 走 [.vscode/launch.json](.vscode/launch.json) 断点调试）**：终端会交互引导选任务、输入/自动生成 `RUN_ID`（检测到已有存档默认续训）、可选覆盖 `epochs`/`lr`，且自动绑定 Google Drive 保存全部成果！
   - **使用短命令脚本**：
     ```bash
     bash scripts/remote_train.sh --task classification --run-id classification_demo_001 -- --resume auto --epochs 65
     bash scripts/remote_train.sh --task regression --run-id reg_ssh_001 --tmux   # 长实验推荐 --tmux 挂后台防断线
     ```
   - **使用完整 Python 命令（单行无反斜杠）**：
     ```bash
     python3 -u -m colab_training_demo.train --config configs/classification.json --run-id classification_demo_001 --local-root /content/runs --persistent-root /content/drive/MyDrive/Colab_Training_Demo/runs --device cuda --resume auto --epochs 65
     ```
4. **实验结束及时关机省计算单元**：
   在本地 WSL 终端运行：
   ```bash
   colab stop -s colab-a100
   colab usage    # 确认显示 Usage rate: 0.00/hr 且 Active assignments: 0
   ```

---

### 方式二：VS Code + `启动Colab.ipynb` 笔记本遥控（无需配 WSL2，方便随时画曲线图）

1. 打开根目录 **[启动Colab.ipynb](启动Colab.ipynb)**，右上角选择 `Select Kernel → Colab → New Colab Server → 可用 GPU → Standard → Python 内核`。
   - **选卡建议**：A100 与 L4 均选 **`Standard`**（A100 `Standard` 已包含满血 40GB 显存和约 83.5GB 主机内存；`High-RAM` 极易因特殊池配额失败）。
2. 依次运行 **第 1 步（环境自检）→ 第 2 步（Drive 挂载）→ Git 拉取格（`git clone` / `git pull`）→ 第 3 步（白名单增量同步 Drive）→ 第 4 步（设置 `TASK` 与 `RUN_ID`）**。
   - **防覆盖保护**：若云盘 `runs/` 下已存在同名 `RUN_ID`，不带 `--resume auto` 的第 5 步会抛出 `FileExistsError` 拦截覆盖。接续旧实验请**跳过第 5 步直接运行第 7 步**；开新实验请在第 4 步修改 `TASK` 或 `RUN_ID`。
3. 运行 **第 5 步**（首次演示 `--stop-after-epoch 3`）、**第 6 步**（核对检查点与 `intermediate_state.pt`）、**第 7 步**（`--resume auto` 续训，可追加 `--epochs` / `--lr` / `--batch-size`）、**第 8 步**（画曲线图并存云盘）。
4. 训练结束不再使用时，前往 Colab 网页“正在进行的会话”找到对应 `未知笔记本 | GPU` 点击垃圾桶图标终止，避免待机扣计算单元。

---

### 方式三：WSL2 纯终端自动化批处理（`scripts/colab_cli_train.sh`）

适合完全熟手后在 WSL2 终端一条命令“申请显卡 → 挂载 Drive → 拉 GitHub → 训练 → 跑完自动停机省额度”：
```bash
cd /mnt/d/DesktopFILES/云端colab远程项目
bash scripts/colab_cli_train.sh --gpu L4 --task classification --run-id cls_cli_001 --auto-stop
bash scripts/colab_cli_train.sh --gpu A100 --task classification --run-id classification_demo_001 -- --resume auto --epochs 70 --lr 0.0005
bash scripts/colab_cli_train.sh --status        # 查看余额、nvidia-smi 与进程
bash scripts/colab_cli_train.sh --stop-remote   # 向后台 train.py 发送 SIGINT 存盘退出
```

---

## 日常调试、SSH 稳定性与故障速查

| 场景 | 处理方式 |
|---|---|
| 抢不到第二台 A100 | 先运行 `colab sessions` 与 `colab usage`；若看到 `[?]` 残留会话（之前 `.ipynb` 留下的未关闭 A100），先去 Colab 网页点垃圾桶关掉释放配额再开 |
| 本地改代码后云端同步 | 本地 VS Code `Commit & Sync Changes` → 远程终端 `git pull`（1 秒同步），无需重传整套文件夹 |
| 随时停下调试 / 改参数 | 在远程终端按 `Ctrl + C`（或在笔记本点停止），当前 Batch 结束后立刻保存并同步 Drive；随后直接 `--resume auto` 接着跑 |
| 防止远程 SSH 断线丢进度 | 1) 长训练加 `--tmux`（或 `nohup`）放后台；2) Windows 接通电源睡眠设为“从不”；3) 切勿在 SSH 连接期间执行 `wsl --shutdown` |
| WSL 旧黑框点击就冻结或不能粘贴 | 不要用旧版 `conhost`（窗口顶部出现`选择`即冻结，右键也会被禁用）；改用 **`Windows Terminal`**（并设为系统默认终端）或 **VS Code 内置 WSL 终端** |
| WSL2 下 `colab-cli` 登录/弹网页异常 | 使用 `uv tool install --python 3.12 google-colab-cli --with keyrings.alt` + `PlaintextKeyring` 持久化登录态，并在 `~/.bashrc` 配 `export BROWSER=wslview` |

---

## 工程结构与 Drive 持久目录布局

```text
本地项目/
├── 启动Colab.ipynb                                 # 笔记本遥控启动入口
├── Colab远程科研训练_SKILL指南.md                   # 完整操作手册 + AI 工程改造规范
├── .agents/skills/colab-remote-training/SKILL.md   # Agent 自动发现 Skill
├── .vscode/
│   ├── extensions.json
│   ├── launch.json                                 # F5 一键运行与断点调试配置
│   └── settings.json
├── scripts/
│   ├── colab_cli_train.sh                          # WSL2 一键建机/训练/自动停机脚本
│   ├── colab_ssh_up.sh                             # 每日新开 GPU + 挂盘 + 拉代码前置脚本
│   └── remote_train.sh                             # Remote-SSH 远程终端快捷训练脚本
├── colab_training_demo/
│   ├── train.py                                    # 主程序（支持 -m 与直接运行、自动绑 Drive、Step/Epoch 恢复）
│   ├── checkpoint.py                               # 原子快照、SHA-256 校验、Drive 备份与滚动保留
│   ├── models/                                     # 模型子包（RL 可扩展 actor/critic 等）
│   ├── datasets/                                   # 数据子包（RL 可替换为 env/replay buffer 等）
│   └── utils/
│       ├── code_sync.py                            # 递归白名单代码同步与恢复
│       └── state_bag.py                            # 梯度范数与 intermediate_state.pt 原子保存
├── configs/
├── requirements-colab.txt
├── build_colab_zip.py
└── tests/test_training.py
```

Drive 持久目录（`/content/drive/MyDrive/Colab_Training_Demo/`）：
- `project_workspace/`：通过白名单增量同步的核心代码与配置副本（不含 `.git/`、测试与文档）。
- `runs/<RUN_ID>/`：保存 `config.json`、`code_version.json`（含 `git_commit` 与修改历史）、`source.zip`、`metrics.csv`（全轮次）、`intermediate_state.pt`、`last_model.pt`、`best_model.pt`、`final_model.pt`、`loss_curve.png` 与滚动保留最近 `keep_last` 份完整 `checkpoints/`。

## 本地验证命令

```powershell
& 'E:\Users\lenovo1\anaconda3\envs\Jupyter\python.exe' -m unittest discover -s tests -v
& 'E:\Users\lenovo1\anaconda3\envs\Jupyter\python.exe' build_colab_zip.py
```
