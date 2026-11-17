#!/usr/bin/env bash
# 通过官方 google-colab-cli 在 WSL2 / Linux / macOS 终端一键完成：
# 分配 GPU -> 挂载 Google Drive -> GitHub 拉取与白名单同步 -> 启动/续训 train.py -> 可选自动释放实例

set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

SESSION="ml-train"
GPU="L4"
HIGH_MEM=0
REPO_URL="https://github.com/uaago/-1.git"
TASK="regression"
RUN_ID=""
AUTO_STOP=0
DETACH=0
ACTION="train"
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
用法:
  bash scripts/colab_cli_train.sh [选项] [-- 传给 train.py 的额外参数]

常用选项:
  -s, --session NAME     Colab CLI 会话名称（默认: ml-train）
  --gpu TYPE             GPU 型号: T4 | L4 | A100 | H100 | none（默认: L4）
  --high-mem             申请高主机内存实例（仅 CPU/T4/A100 支持，L4 自动忽略）
  --repo URL             GitHub 仓库地址（设为 "" 则直接从 Drive project_workspace 恢复）
  --task TASK            任务名: regression | classification（默认: regression）
  --run-id ID            实验存档名（默认: <TASK>_cli_001；续训已有实验时填原名）
  --auto-stop            训练正常完成后自动执行 colab stop 释放虚拟机，省计算单元
  --detach               让 train.py 在云端后台运行（输出写至 /content/runs/<RUN_ID>/train.log）
  --stop-remote          向云端正在运行的 train.py 发送 SIGINT（当前 Batch 完成后立即存盘退出）
  --status               查看当前会话状态、计算单元余额及云端 GPU/训练进程
  -h, --help             显示本帮助

示例:
  # 1. 开新实验（L4 跑完自动停机省额度）
  bash scripts/colab_cli_train.sh --gpu L4 --task classification --run-id cls_cli_001 --auto-stop

  # 2. 续训之前在启动笔记本里跑过的 classification_demo_001 到 70 轮并调小学习率
  bash scripts/colab_cli_train.sh --gpu A100 --task classification --run-id classification_demo_001 -- --resume auto --epochs 70 --lr 0.0005

  # 3. 优雅停止云端后台训练（保存当前 Batch 检查点并同步 Drive）
  bash scripts/colab_cli_train.sh --stop-remote
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--session) SESSION="$2"; shift 2 ;;
    --gpu) GPU="$2"; shift 2 ;;
    --high-mem) HIGH_MEM=1; shift ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --task) TASK="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --auto-stop) AUTO_STOP=1; shift ;;
    --detach) DETACH=1; shift ;;
    --stop-remote) ACTION="stop_remote"; shift ;;
    --status) ACTION="status"; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; EXTRA_ARGS+=("$@"); break ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

if [[ -z "$RUN_ID" ]]; then
  RUN_ID="${TASK}_cli_001"
fi

if ! command -v colab >/dev/null 2>&1; then
  echo "[错误] 未找到 colab 命令。请在 WSL2 中使用 uv 安装（Ubuntu 20.04 需指定 Python 3.12）：" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "  uv tool install --python 3.12 google-colab-cli" >&2
  exit 1
fi

TMP_REMOTE_SH=""
cleanup() {
  if [[ -n "$TMP_REMOTE_SH" && -f "$TMP_REMOTE_SH" ]]; then
    rm -f "$TMP_REMOTE_SH"
  fi
}
trap cleanup EXIT

run_remote_script() {
  local body="$1"
  TMP_REMOTE_SH=$(mktemp /tmp/colab_cli_job.XXXXXX.sh)
  printf '%s\n' "$body" > "$TMP_REMOTE_SH"
  colab upload -s "$SESSION" "$TMP_REMOTE_SH" /tmp/colab_cli_job.sh >/dev/null
  colab ssh -s "$SESSION" -- bash /tmp/colab_cli_job.sh
}

if [[ "$ACTION" == "status" ]]; then
  echo "=== Colab 会话与余额 ==="
  colab sessions || true
  colab usage || true
  echo "=== 云端 GPU 与训练进程 ($SESSION) ==="
  run_remote_script 'nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader 2>/dev/null || echo "无 GPU"; ps -eo pid,etime,args | grep "[c]olab_training_demo.train" || echo "当前无运行中的训练进程"'
  exit 0
fi

if [[ "$ACTION" == "stop_remote" ]]; then
  echo "[停止] 正在向会话 $SESSION 中的 train.py 发送 SIGINT（等待当前 Batch 存盘并同步 Drive）..."
  run_remote_script 'pkill -INT -f colab_training_demo.train && echo "已发送中断信号，请稍候查看 Drive status.json" || echo "未发现运行中的训练进程"'
  exit 0
fi

# 1. 确保会话存在（若不存在则按需申请 GPU 实例）
if colab status -s "$SESSION" >/dev/null 2>&1; then
  echo "[会话] 复用已有 Colab 会话: $SESSION"
else
  echo "[会话] 正在创建 Colab 会话: $SESSION (GPU=$GPU, HIGH_MEM=$HIGH_MEM)"
  NEW_CMD=(colab new -s "$SESSION")
  if [[ "$GPU" != "none" && -n "$GPU" ]]; then
    NEW_CMD+=(--gpu "$GPU")
  fi
  if [[ "$HIGH_MEM" -eq 1 && "$GPU" != "L4" ]]; then
    NEW_CMD+=(--high-mem)
  fi
  "${NEW_CMD[@]}"
fi

# 2. 确保 Google Drive 已挂载（首次可能需要按终端提示的链接完成浏览器授权）
if colab ssh -s "$SESSION" -- test -d /content/drive/MyDrive >/dev/null 2>&1; then
  echo "[Drive] /content/drive/MyDrive 已挂载"
else
  echo "[Drive] 正在挂载 Google Drive（如未自动打开浏览器，请复制终端链接完成授权）..."
  colab drivemount -s "$SESSION"
fi

# 3. 生成无引号转义风险的云端执行脚本，上传并通过 colab ssh 执行
DEVICE="cuda"
if [[ "$GPU" == "none" ]]; then
  DEVICE="cpu"
fi

EXTRA_ARR_DECL="EXTRA_ARGS=()"
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  printf -v QUOTED_EXTRA '%q ' "${EXTRA_ARGS[@]}"
  EXTRA_ARR_DECL="EXTRA_ARGS=(${QUOTED_EXTRA})"
fi

TMP_REMOTE_SH=$(mktemp /tmp/colab_cli_job.XXXXXX.sh)
{
  printf '#!/usr/bin/env bash\nset -euo pipefail\n'
  printf 'SESSION=%q\n' "$SESSION"
  printf 'REPO_URL=%q\n' "$REPO_URL"
  printf 'TASK=%q\n' "$TASK"
  printf 'RUN_ID=%q\n' "$RUN_ID"
  printf 'DEVICE=%q\n' "$DEVICE"
  printf 'DETACH=%q\n' "$DETACH"
  printf '%s\n' "$EXTRA_ARR_DECL"
  cat <<'REMOTE_EOF'

if [[ ! -d /content/drive/MyDrive ]]; then
  echo "[错误] /content/drive/MyDrive 不可用，请先确认 Drive 挂载授权" >&2
  exit 1
fi

DRIVE_BASE="/content/drive/MyDrive/Colab_Training_Demo"
PERSISTENT_ROOT="${DRIVE_BASE}/runs"
DRIVE_WORKSPACE="${DRIVE_BASE}/project_workspace"
mkdir -p "$PERSISTENT_ROOT" "$DRIVE_WORKSPACE"

if [[ -n "$REPO_URL" ]]; then
  PROJECT="/content/github_repo"
  if [[ -d "${PROJECT}/.git" ]]; then
    git -C "$PROJECT" pull --ff-only
  else
    git clone --depth 1 "$REPO_URL" "$PROJECT"
  fi
else
  PROJECT="/content/colab_training_project"
  python3 - "$DRIVE_WORKSPACE" "$PROJECT" <<'PY_RESTORE'
import importlib.util, sys
from pathlib import Path
ws, dst = Path(sys.argv[1]), Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("_cs", ws / "colab_training_demo/utils/code_sync.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.restore_workspace_from_drive(ws, dst)
print("已从 Drive 工作区恢复代码到:", dst)
PY_RESTORE
fi

python3 - "$PROJECT" "$DRIVE_WORKSPACE" <<'PY_SYNC'
import importlib.util, sys
from pathlib import Path
proj, ws = Path(sys.argv[1]), Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("_cs", proj / "colab_training_demo/utils/code_sync.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
rep = mod.sync_workspace_to_drive(proj, ws)
print(f"Drive 白名单同步完成: 更新 {len(rep['copied'])} 个文件, 未变化 {len(rep['unchanged'])} 个文件")
PY_SYNC

python3 -m pip install -q -r "${PROJECT}/requirements-colab.txt"

cd "$PROJECT"
mkdir -p "/content/runs/${RUN_ID}"

if [[ "$DETACH" -eq 1 ]]; then
  LOG_FILE="/content/runs/${RUN_ID}/train.log"
  nohup python3 -u -m colab_training_demo.train \
    --config "${PROJECT}/configs/${TASK}.json" \
    --run-id "$RUN_ID" \
    --local-root /content/runs \
    --persistent-root "$PERSISTENT_ROOT" \
    --device "$DEVICE" \
    ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} >"$LOG_FILE" 2>&1 < /dev/null &
  PID=$!
  echo "[后台已启动] PID=$PID | 日志: $LOG_FILE"
  echo "查看实时日志: colab ssh -s ${SESSION} -- tail -f ${LOG_FILE}"
  echo "优雅存盘停止: bash scripts/colab_cli_train.sh -s ${SESSION} --stop-remote"
else
  python3 -u -m colab_training_demo.train \
    --config "${PROJECT}/configs/${TASK}.json" \
    --run-id "$RUN_ID" \
    --local-root /content/runs \
    --persistent-root "$PERSISTENT_ROOT" \
    --device "$DEVICE" \
    ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
fi
REMOTE_EOF
} > "$TMP_REMOTE_SH"

echo "[训练] 会话=$SESSION | 任务=$TASK | RUN_ID=$RUN_ID | 设备=$DEVICE | 后台模式=$DETACH"

handle_sigint() {
  if [[ "$DETACH" -eq 0 ]]; then
    echo ""
    echo "[中断] 收到 Ctrl+C，正在通知云端 train.py 在当前 Batch 完成后存盘退出..."
    colab ssh -s "$SESSION" -- pkill -INT -f colab_training_demo.train >/dev/null 2>&1 || true
  fi
}
trap handle_sigint INT

colab upload -s "$SESSION" "$TMP_REMOTE_SH" /tmp/colab_cli_job.sh >/dev/null

set +e
colab ssh -s "$SESSION" -- bash /tmp/colab_cli_job.sh
TRAIN_RC=$?
set -e
trap - INT

if [[ "$TRAIN_RC" -ne 0 ]]; then
  echo "[警告] 远程训练退出码为 $TRAIN_RC，保留会话 $SESSION 以便排查（可使用 colab ssh -s $SESSION 登录检查）。" >&2
  exit "$TRAIN_RC"
fi

if [[ "$AUTO_STOP" -eq 1 && "$DETACH" -eq 0 ]]; then
  echo "[收尾] 训练已顺利结束，正在自动释放会话 $SESSION 节省计算单元..."
  colab stop -s "$SESSION"
else
  echo "[完成] 如需省计算单元，记得运行: colab stop -s $SESSION"
fi
