#!/usr/bin/env bash
# 在已通过 VS Code Remote-SSH / colab ssh 连上的 Colab 云端终端内直接启动或续训项目：
# 自动核对 Drive 挂载 -> 增量同步当前修改到 Drive project_workspace -> 调用 colab_training_demo.train

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT=$(cd "${SCRIPT_DIR}/.." && pwd)

TASK="regression"
CONFIG=""
RUN_ID=""
DEVICE="auto"
LOCAL_ROOT="/content/runs"
PERSISTENT_ROOT="/content/drive/MyDrive/Colab_Training_Demo/runs"
DRIVE_WORKSPACE="/content/drive/MyDrive/Colab_Training_Demo/project_workspace"
DO_PULL=0
DO_SYNC=1
USE_TMUX=0
NO_DRIVE=0
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
用法（在云端 Colab 终端 / VS Code Remote-SSH 终端内运行）:
  bash scripts/remote_train.sh [选项] [-- 额外传给 train.py 的参数]

选项:
  --task TASK            任务名: regression | classification（默认: regression）
  --config PATH          自定义配置文件路径（默认: <PROJECT>/configs/<TASK>.json）
  --run-id ID            实验存档名（默认: <TASK>_ssh_001；续训已有实验时填原名）
  --device DEV           auto | cuda | cpu（默认: auto）
  --pull                 启动前先在当前仓库执行 git pull --ff-only
  --no-sync              启动前跳过向 Drive project_workspace 同步本地代码修改
  --no-drive             仅本地容器临时测试，不校验也不写入 Google Drive
  --tmux                 使用后台会话（优先 tmux，若无 tmux 则 nohup）运行，关闭 SSH 窗口不停训
  -h, --help             显示本帮助

常用示例:
  # 新建实验
  bash scripts/remote_train.sh --task classification --run-id cls_ssh_001

  # 续训已有实验并动态调参（可把 --resume 等直接放在 -- 后面或直接追加）
  bash scripts/remote_train.sh --task classification --run-id classification_demo_001 -- --resume auto --epochs 70 --lr 0.0005

  # 后台运行，断开 VS Code 窗口也不影响训练
  bash scripts/remote_train.sh --task classification --run-id cls_ssh_001 --tmux
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --device) DEVICE="$2"; shift 2 ;;
    --local-root) LOCAL_ROOT="$2"; shift 2 ;;
    --persistent-root) PERSISTENT_ROOT="$2"; shift 2 ;;
    --pull) DO_PULL=1; shift ;;
    --no-sync) DO_SYNC=0; shift ;;
    --no-drive) NO_DRIVE=1; shift ;;
    --tmux) USE_TMUX=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; EXTRA_ARGS+=("$@"); break ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

if [[ -z "$CONFIG" ]]; then
  CONFIG="${PROJECT}/configs/${TASK}.json"
fi
if [[ -z "$RUN_ID" ]]; then
  RUN_ID="${TASK}_ssh_001"
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "[错误] 未找到配置文件: $CONFIG" >&2
  exit 1
fi

if [[ "$DO_PULL" -eq 1 && -d "${PROJECT}/.git" ]]; then
  git -C "$PROJECT" pull --ff-only
fi

if [[ "$NO_DRIVE" -eq 0 ]]; then
  if [[ ! -d /content/drive/MyDrive ]]; then
    echo "[错误] 当前机器尚未挂载 Google Drive (/content/drive/MyDrive 不存在)！" >&2
    echo "请在本机 WSL2 终端执行一次: colab drivemount -s <你的会话名>" >&2
    exit 1
  fi
  mkdir -p "$PERSISTENT_ROOT" "$DRIVE_WORKSPACE"
  if [[ "$DO_SYNC" -eq 1 ]]; then
    python3 - "$PROJECT" "$DRIVE_WORKSPACE" <<'PY_SYNC'
import sys
from pathlib import Path
proj, ws = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(proj))
from colab_training_demo.utils.code_sync import sync_workspace_to_drive
rep = sync_workspace_to_drive(proj, ws)
print(f"[同步 Drive 工作区] 更新 {len(rep['copied'])} 个文件, 未变化 {len(rep['unchanged'])} 个文件")
PY_SYNC
  fi
fi

CMD=(python3 -u -m colab_training_demo.train
  --config "$CONFIG"
  --run-id "$RUN_ID"
  --local-root "$LOCAL_ROOT"
  --device "$DEVICE")

if [[ "$NO_DRIVE" -eq 0 ]]; then
  CMD+=(--persistent-root "$PERSISTENT_ROOT")
fi
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  CMD+=("${EXTRA_ARGS[@]}")
fi

cd "$PROJECT"
mkdir -p "${LOCAL_ROOT}/${RUN_ID}"

echo "[启动训练] PROJECT=$PROJECT | RUN_ID=$RUN_ID | CONFIG=$CONFIG"

if [[ "$USE_TMUX" -eq 1 ]]; then
  printf -v CMD_STR '%q ' "${CMD[@]}"
  if command -v tmux >/dev/null 2>&1; then
    TMUX_NAME="train_${RUN_ID}"
    tmux new-session -d -s "$TMUX_NAME" "cd $(printf '%q' "$PROJECT") && ${CMD_STR}"
    echo "[后台 tmux 已启动] 会话名: $TMUX_NAME"
    echo "查看训练实时界面: tmux attach -t $TMUX_NAME （退出查看请按 Ctrl+B 再按 D）"
  else
    LOG_FILE="${LOCAL_ROOT}/${RUN_ID}/train.log"
    nohup "${CMD[@]}" >"$LOG_FILE" 2>&1 < /dev/null &
    echo "[后台 nohup 已启动] PID=$! | 日志: $LOG_FILE"
    echo "查看实时日志: tail -f $LOG_FILE"
  fi
else
  exec "${CMD[@]}"
fi
