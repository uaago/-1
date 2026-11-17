#!/usr/bin/env bash
# 每日新开 Colab 服务器并在 VS Code Remote-SSH 中打开项目的一键前置准备脚本（运行在本地 WSL2）：
# 1. 创建/复用指定 GPU 会话（默认名与 ~/.ssh/config 中 colab-a100 / colab-l4 / colab-t4 对齐）
# 2. 挂载 Google Drive (/content/drive)
# 3. 从 GitHub 秒级拉取代码到 /content/github_repo，按白名单同步 Drive 工作区并准备依赖

set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

GPU="L4"
SESSION=""
HIGH_MEM=0
REPO_URL="https://github.com/uaago/-1.git"

usage() {
  cat <<'EOF'
用法:
  bash scripts/colab_ssh_up.sh [选项]

选项:
  --gpu TYPE           GPU 型号: A100 | L4 | T4 | none（默认: L4）
  -s, --session NAME   自定义会话名（默认随 GPU 自动匹配: colab-a100 / colab-l4 / colab-t4）
  --high-mem           申请高主机内存实例（仅 A100/T4/none 有效，L4 自动忽略）
  --repo URL           GitHub 仓库地址（设为空字符串 "" 则从 Drive 工作区恢复）
  -h, --help           显示本帮助

示例:
  bash scripts/colab_ssh_up.sh --gpu A100
  bash scripts/colab_ssh_up.sh --gpu L4
  bash scripts/colab_ssh_up.sh -s colab-s-exp1 --gpu A100
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu) GPU="$2"; shift 2 ;;
    -s|--session) SESSION="$2"; shift 2 ;;
    --high-mem) HIGH_MEM=1; shift ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$SESSION" ]]; then
  GPU_LOWER=$(printf '%s' "$GPU" | tr '[:upper:]' '[:lower:]')
  if [[ "$GPU_LOWER" == "none" ]]; then
    SESSION="colab-active"
  else
    SESSION="colab-${GPU_LOWER}"
  fi
fi

if ! command -v colab >/dev/null 2>&1; then
  echo "[错误] 未找到 colab 命令，请先安装: uv tool install --python 3.12 google-colab-cli --with keyrings.alt" >&2
  exit 1
fi

if colab status -s "$SESSION" >/dev/null 2>&1; then
  echo "[1/3] 复用已有 Colab 会话: $SESSION"
else
  echo "[1/3] 正在申请新 Colab 会话: $SESSION (GPU=$GPU)"
  NEW_CMD=(colab new -s "$SESSION")
  if [[ "$GPU" != "none" && -n "$GPU" ]]; then
    NEW_CMD+=(--gpu "$GPU")
  fi
  if [[ "$HIGH_MEM" -eq 1 && "$GPU" != "L4" ]]; then
    NEW_CMD+=(--high-mem)
  fi
  "${NEW_CMD[@]}"
fi

if colab ssh -s "$SESSION" -- test -d /content/drive/MyDrive >/dev/null 2>&1; then
  echo "[2/3] Google Drive 已挂载 (/content/drive/MyDrive)"
else
  echo "[2/3] 正在挂载 Google Drive（如弹出浏览器请点击授权，然后回终端按 Enter）..."
  colab drivemount -s "$SESSION"
fi

echo "[3/3] 正在拉取代码到 /content/github_repo 并同步 Drive 工作区..."
TMP_SH=$(mktemp /tmp/colab_ssh_up.XXXXXX.sh)
trap 'rm -f "$TMP_SH"' EXIT
{
  printf '#!/usr/bin/env bash\nset -euo pipefail\n'
  printf 'REPO_URL=%q\n' "$REPO_URL"
  cat <<'REMOTE_EOF'
DRIVE_BASE="/content/drive/MyDrive/Colab_Training_Demo"
DRIVE_WORKSPACE="${DRIVE_BASE}/project_workspace"
mkdir -p "${DRIVE_BASE}/runs" "$DRIVE_WORKSPACE"

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
REMOTE_EOF
} > "$TMP_SH"

colab upload -s "$SESSION" "$TMP_SH" /tmp/colab_ssh_up_job.sh >/dev/null
colab ssh -s "$SESSION" -- bash /tmp/colab_ssh_up_job.sh

echo ""
echo "========================================================================"
echo "云端服务器已完全就绪！会话名: $SESSION"
echo "1. 打开 VS Code 左侧 Remote Explorer -> SSH -> 刷新后连接: $SESSION（或 colab-active）"
echo "2. 打开远程目录: /content/github_repo"
echo "3. 在远程终端运行训练（示例）:"
echo "   bash scripts/remote_train.sh --task classification --run-id cls_ssh_001"
echo "   bash scripts/remote_train.sh --task classification --run-id classification_demo_001 -- --resume auto --epochs 70"
echo "4. 结束不用时在 WSL2 执行停机省额度: colab stop -s $SESSION"
echo "========================================================================"
