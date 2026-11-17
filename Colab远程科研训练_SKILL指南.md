# Colab 远程多文件科研训练：小白操作手册 & AI 工程改造 Skill 指南

这份文档既是**你的日常使用速查手册**，也是**可以直接发给其他 AI 的标准改造规范（Skill）**。下次有新的科研项目需要搬到 Google Colab 上训练时，直接把这份文档（或仓库里的 [.agents/skills/colab-remote-training/SKILL.md](.agents/skills/colab-remote-training/SKILL.md)）交给 AI 照着搭建即可。

---

## 第一部分：核心原理一图流（30 秒看懂）

可以把整套系统理解成 **“前台遥控器 + 云端后台工程车”**：

```text
你的本地 VS Code 电脑
 └── 启动Colab.ipynb（前台遥控面板：只有 .ipynb 能连 Colab GPU 内核）
       ├── 第 1 步：确认连上云端 Linux GPU
       ├── 第 2 步：把 Google 云盘挂到 /content/drive
       ├── 第 3 步：定位 /content 代码 + 自动同步到云盘 project_workspace（新机器免重传拉取）
       └── 第 4～7 步：在远程 Linux 虚拟机里执行系统命令启动主程序
             └── python -u -m colab_training_demo.train ...
                   ├── import models/     （网络结构子包）
                   ├── import datasets/   （数据集与加载器子包）
                   ├── import utils/      （代码同步与中间状态诊断工具）
                   ├── 本地高速盘写日志   ──► /content/runs/<RUN_ID>/
                   └── 安全检查点自动同步 ──► /content/drive/MyDrive/Colab_Training_Demo/runs/<RUN_ID>/
```

### 几个最容易搞混的小概念
1. **为什么不用普通 `.py` 右上角直接连 Colab？**  
   VS Code 的 Colab 插件规定只有 `.ipynb` 笔记本能连接云端内核。所以固定用 [启动Colab.ipynb](启动Colab.ipynb) 当启动器，通过 `subprocess.Popen` 启动独立云端进程去跑 [colab_training_demo/train.py](colab_training_demo/train.py)。
2. **多个 `.py` 文件怎么协作？**  
   它们共用同一个 Colab 云端 Python 环境（预装好 CUDA/PyTorch），通过 `import` 在 `train.py` 里拼装执行。每次点击 `launch_training(...)` 都是**全新启动一个 Linux 子进程**，改完 `.py` 重新上传后无需重启笔记本内核，再次运行就会加载最新代码。
3. **为什么要区分 `/content/runs` 和 `/content/drive/MyDrive/...`？**  
   `/content/runs/` 是云端虚拟机的本地 SSD 临时盘（读写极快，适合放数据缓存和每轮日志，但机器回收后会清空）；`/content/drive/` 是你的 Google 云盘（长期持久化，但频繁写小文件慢且可能因网络波动写半截）。因此训练时**先写临时盘、通过 SHA-256 校验后再原子同步到云盘**。

---

## 第二部分：日常使用速查表（1～9 步分别干什么）

| 步骤 | 作用（大白话） | 首次运行 | 断线换新机器恢复 | 平时要改什么 |
| :--- | :--- | :--- | :--- | :--- |
| **第 1 步** | 检查连上的是否是云端 Linux 和 GPU | 必须运行 | 必须运行 | 一般不改；仅用 CPU 测试可改 `REQUIRE_GPU = False` |
| **第 2 步** | 挂载 Google 云盘并测试读写权限 | 必须运行 | 必须运行 | 不用改 |
| **第 3 步** | 找到代码并备份到云盘 `project_workspace` | **先右键上传**，再运行 | **不用右键上传**，直接运行自动从云盘拉回代码 | 不用改（新机器会自动恢复到 `/content/colab_training_project`） |
| **第 4 步** | 选定任务配置 `TASK`、存档名 `RUN_ID`，定义 `launch_training()` | 必须运行 | 必须运行（**不要改 `RUN_ID`**） | **开新实验才改 `RUN_ID`**；同实验续训绝不改名 |
| **第 5 步** | **按下启动按钮**（首次默认 `--stop-after-epoch 3` 演示停在第 3 轮） | 运行一次 | **跳过！**（不要用它） | 正式从头一口气跑完时改为 `launch_training()` |
| **第 6 步** | “验货器”：查看有哪些完好快照、当前到第几轮、中间状态数值 | 可选运行 | 可运行查看当前到了第几轮 | 不用改 |
| **第 7 步** | **断点续训按钮**（`--resume auto` 自动找最新完好存档接着跑） | 运行完成后续轮次 | **跳过第 5 步，直接运行这一步** | 调参续训可加参数，如 `"--lr", "0.001", "--epochs", "20"` |
| **第 8 步** | 画出完整的 Train/Val Loss 曲线并把图片保存到 Google 云盘 | 跑完后运行 | 跑完后运行 | 不用改 |
| **第 9 步** | 云端“任务管理器”：检查后台是否还有正在跑的 `train.py` 进程 | 不用运行 | 仅当网络卡住不确定进程是否还在时运行 | 不用改 |

---

## 第三部分：小白常见 6 大疑问速答

1. **为什么云盘 `checkpoints/` 里永远只看到最近 3 个文件夹（比如 `10、11、12`）？之前的去哪了？**  
   因为配置里设置了 `"checkpoint_every_epochs": 1` 和 `"keep_last": 3`（像行车记录仪一样滚动保留最新的 3 个完整断点，防止撑爆云盘，同时避免最新一个刚传坏就没退路）。全程最好的模型 **`best_model.pt`**、最终模型 **`final_model.pt`** 和完整每轮日志 **`metrics.csv`** 都是单独永久保留的，一个都不会少。想留更多断点就把 [configs/regression.json](configs/regression.json) 的 `keep_last` 改大即可。
2. **断线后我怎么知道之前跑到第几轮了？需要手填轮数吗？**  
   **不需要手填！** `--resume auto` 会自动去本地和云盘里找编号最高且 SHA-256 校验通过的存档接着跑。如果想提前确认进度，点运行 **第 6 步** 或去云盘网页看 `checkpoints/` 里最大编号即可（`epoch_00000007` 表示已完成第 7 轮；`epoch_00000006_step_00000210` 表示第 7 轮中途第 210 步停下）。
3. **总轮数、学习率是在哪设置的？怎么临时修改？**  
   默认值写在 `configs/*.json` 里。启动或续训时也可以直接在 `launch_training(...)` 传参覆盖：
   - 接着上次继续多训几轮并降低学习率：`launch_training("--resume", "auto", "--epochs", "20", "--lr", "0.001")`
   - 按固定步数（例如每 20 个 Batch）自动存盘：`launch_training("--resume", "auto", "--checkpoint-every-steps", "20")`
4. **运行到一半想随时停下调试怎么办？会白跑吗？**  
   直接点单元格左侧的停止按钮（发送 `SIGINT`）。程序会在**当前这一个 Batch 跑完后立刻停止**，把模型、优化器、学习率调度器、随机数状态、Batch 采样位置 `in_epoch`、诊断快照 `intermediate_state.pt` 和最新权重 `last_model.pt` 全部写入并同步到云盘。下次点第 7 步会精确从下一个 Batch 继续。
5. **修改了 `.py` 代码后怎么继续训练？**  
   修改本地 `.py` → 上传（并运行第 3 步同步到云盘工作区）→ 直接运行第 7 步 `launch_training("--resume", "auto")`。默认开启“灵活调试模式”，会打印 `[resume-debug]` 变更提示并更新 `source.zip`，不会报错拦截。如果做正式对照实验想严防改代码/改参误续训，在参数里加上 `"--strict-resume"`。
6. **右键 `Upload to Colab` 上传整个文件夹太慢怎么办？**  
   因为插件是按每个零散小文件排队上传的。加速方法有两种：
   - **方法 A（单个 ZIP 上传）**：本地运行 `build_colab_zip.py` 生成几十 KB 的单文件 `dist/colab_training_demo.zip`，只右键上传这 1 个文件（1～2 秒完成），再在云端解压；
   - **方法 B（GitHub 同步，科研推荐）**：把项目推到 GitHub，在 Colab 单元格里用 `git clone` / `git pull` 秒级同步。

---

## 第四部分：给其他 AI 看的工程改造规范（可直接复制发给 AI）

> 下次你拿到一个新的多文件科研代码仓库，可以直接对 AI 说：**“请阅读 `Colab远程科研训练_SKILL指南.md`（或 `.agents/skills/colab-remote-training/SKILL.md`），帮我把这个新项目改造成同样的 Colab 远程训练 + Google Drive 同步 + Step/Epoch 断点续训架构。”**

### 新项目适配必须满足的 6 条架构要求

1. **多文件工程包结构与独立子进程入口**
   - 将项目组织为标准的 Python 包（如 `<pkg>/models/`、`<pkg>/datasets/`、`<pkg>/utils/`、`<pkg>/train.py`、`<pkg>/checkpoint.py`），在 `<pkg>/train.py` 中通过相对导入组合各模块。
   - 保留固定入口 `启动Colab.ipynb`，仅负责：检查 Linux/CUDA 环境 → 挂载 `/content/drive` 并读写探针验证 → 定位/恢复项目源码并增量同步至云盘 `project_workspace` → 使用 `subprocess.Popen([sys.executable, "-u", "-m", "<pkg>.train", ...])` 启动独立训练进程，并在 `KeyboardInterrupt` 时向子进程转发 `SIGINT` 后等待其存盘退出。

2. **双盘目录隔离与防伪云盘校验**
   - 临时盘（`/content/runs/<RUN_ID>`）：存放数据缓存、逐轮 `metrics.csv` 和本地快照。
   - 持久盘（`/content/drive/MyDrive/<Project>/runs/<RUN_ID>`）：禁止本地目录与持久目录相同或互相嵌套；每次写入 `/content/drive` 前必须校验 `os.path.ismount("/content/drive")` 与 `MyDrive` 目录存在，防止 Drive 掉挂载后写入临时容器目录造成“假备份”。
   - 在启动器第 3 步实现 `sync_workspace_to_drive`（基于 SHA-256 增量同步多目录 `.py` 与配置）与 `restore_workspace_from_drive`（新实例自动从云盘拉取代码）。

3. **原子检查点、SHA-256 完成标记与损坏回退**
   - 快照目录结构：
     - 完整 Epoch 快照：`checkpoints/epoch_{epoch:08d}/`
     - Step/Batch 级中途快照：`checkpoints/epoch_{completed_epoch:08d}_step_{global_step:08d}/`
   - 写入顺序：先写入临时隐藏目录 `.writing_<uuid>` 里的 `state.pt` 与 `metrics.csv` 快照，计算二者的 SHA-256 后原子生成 `complete.json`，最后 `os.replace` 发布目录。
   - 上传至 Drive 时先写 `.uploading` 临时文件并做二次哈希校验，最后才复制 `complete.json`。
   - 恢复时按 `(epoch_num, step_num)` 倒序遍历本地与云盘所有快照，自动跳过没有 `complete.json` 或哈希校验失败的半截快照，并用所选快照绑定的 `metrics.csv` 重建运行日志。
   - 仅当云盘备份成功返回后才按 `keep_last` 清理旧快照（只允许删除 `checkpoints/` 下的子目录）。

4. **Step/Batch 级中断与完整算法状态保存**
   - 捕获 `SIGINT` 与 `SIGTERM`，收到信号或命中 `--stop-after-step` / `checkpoint_every_steps` / `checkpoint_every_seconds` 时，在**当前 Batch 完成后立即保存**并同步 Drive，随后安全退出。
   - 检查点 `state.pt` 必须保存：模型权重、优化器状态、学习率调度器状态、已完成 `epoch`、`global_step`、Python/NumPy/Torch/CUDA/采样器随机状态（`rng`）、当前 Epoch 未完成时的 `in_epoch` 状态（`current_epoch`、`completed_batches`、`total_batches`、`order`、`total_loss`、`seen_samples`）以及最佳模型追踪状态（如迁移到 AMP 需加 `GradScaler`，迁移到强化学习需加环境/ReplayBuffer 状态）。
   - 每次存盘同步导出 `last_model.pt`、`best_model.pt`（存在时）和 `intermediate_state.pt`（记录 `batch_loss`、`grad_norm`、当前 `learning_rate`、`val_loss`、验证集预测样本及 `custom_state`）。

5. **灵活调试续训 vs 严格模式**
   - 默认 `--resume auto` 仅在结构性键（任务类型、随机种子、样本规模、网络结构尺寸等）变化时阻断；对源码变化（`source_sha256`）和可调超参变化（`--lr`、`--epochs`、`--batch-size`、`--checkpoint-every-steps`）打印 `[resume-debug]` 变更日志、更新优化器 `param_groups` 与调度器 `base_lrs`、在 `code_version.json` 中记录变更 `history` 并更新 `source.zip` 后继续训练。
   - 提供 `--strict-resume` 参数，用于正式基准实验时强制校验源码哈希与训练参数完全一致。

6. **同机并发文件锁与自动化测试**
   - 本地运行目录使用 `sqlite3.connect(..., timeout=0)` + `BEGIN EXCLUSIVE` 作为进程锁（进程崩掉后 OS 自动释放，无需手删残留锁）。
   - 必须配备本地可运行的 `unittest` 测试集，验证：Epoch 边界续训逐位一致性、Mid-Epoch（Step 级）中断恢复逐位一致性、修改代码与学习率灵活续训、最新快照损坏回退、Drive 掉挂载拒绝假写入、备份失败本地保留与重试、以及多目录工作区同步与恢复。
