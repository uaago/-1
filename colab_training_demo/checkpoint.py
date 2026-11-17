"""版本目录 + SHA-256 完成标记；只恢复验证通过的快照。"""

import hashlib
import json
import os
from pathlib import Path
import pickle
import re
import shutil
import time
import uuid

import torch


_SNAPSHOT_RE = re.compile(r"^epoch_(\d+)(?:_step_(\d+))?$")


def _snapshot_sort_key(path: Path):
    match = _SNAPSHOT_RE.match(path.name)
    if not match:
        return (-1, -1, path.name)
    epoch_num = int(match.group(1))
    step_num = int(match.group(2)) if match.group(2) is not None else 0
    return (epoch_num, step_num, path.name)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def valid_snapshot(path):
    path = Path(path)
    try:
        marker = json.loads((path / "complete.json").read_text(encoding="utf-8"))
        if not isinstance(marker, dict) or not isinstance(marker.get("files"), dict):
            return False
        if set(marker["files"]) != {"state.pt", "metrics.csv"}:
            return False
        return all(sha256(path / name) == digest for name, digest in marker["files"].items())
    except (OSError, ValueError, KeyError, TypeError):
        return False


def snapshots(run_dir):
    directory = Path(run_dir) / "checkpoints"
    return sorted(
        (p for p in directory.glob("epoch_*") if p.is_dir()),
        key=_snapshot_sort_key,
        reverse=True,
    )


def write_snapshot(run_dir, state):
    root = Path(run_dir) / "checkpoints"
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / (".writing_" + uuid.uuid4().hex)
    temporary.mkdir()
    torch.save(state, temporary / "state.pt")
    shutil.copy2(Path(run_dir) / "metrics.csv", temporary / "metrics.csv")
    is_mid_epoch = bool(state.get("in_epoch"))
    marker = {
        "epoch": state["epoch"],
        "global_step": state.get("global_step", 0),
        "mid_epoch": is_mid_epoch,
        "files": {
            name: sha256(temporary / name) for name in ("state.pt", "metrics.csv")
        },
    }
    atomic_json(temporary / "complete.json", marker)
    name = (
        f"epoch_{state['epoch']:08d}_step_{state['global_step']:08d}"
        if is_mid_epoch
        else f"epoch_{state['epoch']:08d}"
    )
    target = root / name
    # 已恢复到较旧轮次时，可能覆盖同轮次的损坏快照。先撤下完成标记。
    if target.exists():
        (target / "complete.json").unlink(missing_ok=True)
        for item in ("state.pt", "metrics.csv", "complete.json"):
            os.replace(temporary / item, target / item)
        temporary.rmdir()
    else:
        os.replace(temporary, target)
    return target


def copy_verified(source, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = sha256(source)
    # 源码归档等固定文件不重复上传，减少 Drive I/O 和文件占用冲突。
    if target.is_file() and sha256(target) == expected:
        return
    temporary = target.with_name(target.name + ".uploading")
    shutil.copyfile(source, temporary)
    if sha256(temporary) != expected:
        raise OSError(f"复制校验失败: {target}")
    os.replace(temporary, target)
    if sha256(target) != expected:
        raise OSError(f"写入后校验失败: {target}")


def ensure_persistent_available(persistent_run):
    """避免 Drive 掉挂载后把普通临时目录误当云盘。"""
    mount = Path("/content/drive")
    if Path(persistent_run).is_relative_to(mount):
        if not os.path.ismount(mount) or not (mount / "MyDrive").is_dir():
            raise OSError("Drive 挂载已不可用，请恢复挂载；不会把结果写入伪云盘目录")


def publish_snapshot(snapshot, persistent_run, retries=3):
    """失败返回 False，训练保留本地副本，下次保存再次尝试。"""
    snapshot, persistent_run = Path(snapshot), Path(persistent_run)
    for attempt in range(retries):
        try:
            ensure_persistent_available(persistent_run)
            target = persistent_run / "checkpoints" / snapshot.name
            target.mkdir(parents=True, exist_ok=True)
            (target / "complete.json").unlink(missing_ok=True)
            for name in ("config.json", "environment.json", "source.zip", "code_version.json"):
                source = snapshot.parent.parent / name
                copy_verified(source, persistent_run / name)
            for name in ("state.pt", "metrics.csv"):
                copy_verified(snapshot / name, target / name)
            # 最后复制完成标记；不会把半截上传当成可恢复版本。
            copy_verified(snapshot / "complete.json", target / "complete.json")
            if not valid_snapshot(target):
                raise OSError(f"检查点完整性验证失败: {target}")
            copy_verified(snapshot / "metrics.csv", persistent_run / "metrics.csv")
            for name in (
                "best_model.pt",
                "last_model.pt",
                "final_model.pt",
                "intermediate_state.pt",
                "evaluation.json",
                "status.json",
            ):
                source = snapshot.parent.parent / name
                if source.exists():
                    copy_verified(source, persistent_run / name)
            print(f"[backup OK] epoch={snapshot.name} -> {persistent_run}", flush=True)
            return True
        except OSError as error:
            print(f"[backup FAILED {attempt + 1}/{retries}] {error}; 本地快照仍保留", flush=True)
            if attempt + 1 < retries:
                time.sleep(1)
    return False


def prune(run_dir, keep):
    complete = [p for p in snapshots(run_dir) if valid_snapshot(p)]
    for old in complete[keep:]:
        # 仅删除本实验 checkpoints 内、由本程序生成的已验证版本目录。
        expected_parent = (Path(run_dir) / "checkpoints").resolve()
        if old.resolve().parent != expected_parent:
            raise ValueError("检查点保留策略拒绝越界路径")
        shutil.rmtree(old)


def load_latest(run_dirs):
    candidates = [p for run in run_dirs for p in snapshots(run)]
    candidates.sort(key=_snapshot_sort_key, reverse=True)
    for path in candidates:
        if not valid_snapshot(path):
            print(f"[skip] 忽略不完整或损坏快照: {path}", flush=True)
            continue
        try:
            # 只使用 Tensor 与内置基本类型，无需 weights_only=False。
            state = torch.load(path / "state.pt", map_location="cpu", weights_only=True)
            print(f"[resume] 从完整快照恢复: {path}", flush=True)
            return state, path
        except (OSError, RuntimeError, EOFError, ValueError, pickle.UnpicklingError) as error:
            print(f"[skip] 无法加载 {path}: {error}", flush=True)
    raise FileNotFoundError("没有可用的完整检查点；请核对 RUN_ID 和 Drive 挂载，不要自动新建实验")
