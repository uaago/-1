"""训练主入口：支持 python -u -m colab_training_demo.train ... 及直接运行 python colab_training_demo/train.py。"""

if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path

    _root = str(_Path(__file__).resolve().parents[1])
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    __package__ = "colab_training_demo"

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import signal
import sqlite3
import subprocess
import sys
import time
import zipfile

import numpy as np
import torch
from torch import nn

from .checkpoint import (
    atomic_json,
    ensure_persistent_available,
    load_latest,
    prune,
    publish_snapshot,
    write_snapshot,
)
from .datasets import make_data
from .models import make_model
from .utils import (
    compute_grad_norm,
    iter_config_files,
    iter_source_files,
    save_intermediate_state,
)

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("epoch", "global_step", "train_loss", "val_loss", "val_accuracy", "learning_rate")
STRUCTURAL_KEYS = ("task", "seed", "train_samples", "val_samples", "hidden_size")
STRICT_TRAINING_KEYS = STRUCTURAL_KEYS + ("batch_size", "learning_rate")
TUNABLE_KEYS = (
    "learning_rate",
    "batch_size",
    "epochs",
    "checkpoint_every_epochs",
    "checkpoint_every_seconds",
    "checkpoint_every_steps",
    "keep_last",
)


def read_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    config.setdefault("checkpoint_every_steps", 0)
    validate_config(config)
    return config


def validate_config(config):
    if config["task"] not in ("regression", "classification"):
        raise ValueError("task 必须是 regression 或 classification")
    for key in (
        "epochs",
        "train_samples",
        "val_samples",
        "batch_size",
        "hidden_size",
        "checkpoint_every_epochs",
        "checkpoint_every_seconds",
        "keep_last",
    ):
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError(f"{key} 必须是正整数")
    if type(config["checkpoint_every_steps"]) is not int or config["checkpoint_every_steps"] < 0:
        raise ValueError("checkpoint_every_steps 必须是非负整数")
    if type(config["seed"]) is not int or not 0 <= config["seed"] < 2**32:
        raise ValueError("seed 必须是 [0, 2**32) 内的整数")
    if (
        not isinstance(config["learning_rate"], (int, float))
        or isinstance(config["learning_rate"], bool)
        or not math.isfinite(config["learning_rate"])
        or config["learning_rate"] <= 0
    ):
        raise ValueError("learning_rate 必须是有限正数")


def apply_cli_overrides(config, args):
    updated = dict(config)
    if getattr(args, "lr", None) is not None:
        updated["learning_rate"] = float(args.lr)
    if getattr(args, "epochs", None) is not None:
        updated["epochs"] = int(args.epochs)
    if getattr(args, "batch_size", None) is not None:
        updated["batch_size"] = int(args.batch_size)
    if getattr(args, "checkpoint_every_steps", None) is not None:
        updated["checkpoint_every_steps"] = int(args.checkpoint_every_steps)
    validate_config(updated)
    return updated


def source_files():
    return iter_source_files(ROOT)


def source_digest():
    digest = hashlib.sha256()
    for path in source_files():
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def metadata(run_dir, config, digest, code_history):
    atomic_json(run_dir / "config.json", config)
    atomic_json(
        run_dir / "environment.json",
        {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "torch": str(torch.__version__),
            "numpy": np.__version__,
            "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
    )
    result = (
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        if (ROOT / ".git").exists()
        else None
    )
    atomic_json(
        run_dir / "code_version.json",
        {
            "source_sha256": digest,
            "git_commit": result.stdout.strip() if result and result.returncode == 0 else None,
            "history": code_history,
            "note": "SHA-256 递归计算多目录 Python 源码与依赖声明，source.zip 保存该源码副本",
        },
    )
    with zipfile.ZipFile(run_dir / "source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files() + iter_config_files(ROOT):
            archive.write(path, path.relative_to(ROOT))


@contextmanager
def training_lock(run_dir):
    # SQLite 持有文件锁，进程崩溃后操作系统自动释放，无需删除残留 PID 锁。
    connection = sqlite3.connect(run_dir / ".training.lock.sqlite", timeout=0)
    try:
        try:
            connection.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as error:
            raise RuntimeError("这个本地实验目录已有训练进程，请先确认旧进程状态") from error
        yield
    finally:
        connection.rollback()
        connection.close()


def rng_state(shuffle_generator):
    numpy_rng = np.random.get_state()
    return {
        "python": random.getstate(),
        "numpy": [
            numpy_rng[0],
            numpy_rng[1].tolist(),
            int(numpy_rng[2]),
            int(numpy_rng[3]),
            float(numpy_rng[4]),
        ],
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        "shuffle": shuffle_generator.get_state(),
    }


def restore_rng(state, shuffle_generator):
    random.setstate(state["python"])
    n = state["numpy"]
    np.random.set_state((n[0], np.asarray(n[1], dtype=np.uint32), n[2], n[3], n[4]))
    torch.set_rng_state(state["torch"])
    cuda_states = state["cuda"]
    if cuda_states and torch.cuda.is_available():
        if len(cuda_states) == torch.cuda.device_count():
            torch.cuda.set_rng_state_all(cuda_states)
        else:
            print("[warning] GPU 数量改变，不能精确恢复全部 CUDA 随机状态", flush=True)
    shuffle_generator.set_state(state["shuffle"])


def cpu_weights(model):
    return {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}


def export_weights(path, weights, config, epoch, score):
    temporary = path.with_suffix(".tmp")
    torch.save(
        {
            "model": weights,
            "task": config["task"],
            "hidden_size": config["hidden_size"],
            "epoch": epoch,
            "val_loss": score,
        },
        temporary,
    )
    os.replace(temporary, path)


def evaluate_validation(model, loss_fn, vx, vy, task):
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            prediction = model(vx)
            val_loss = float(loss_fn(prediction, vy))
            accuracy = (
                float((prediction.argmax(1) == vy).float().mean())
                if task == "classification"
                else None
            )
            pred_sample = prediction[:64].detach().cpu()
    finally:
        model.train(was_training)
    if not math.isfinite(val_loss):
        raise RuntimeError("验证损失为 NaN/Inf；请从上次有效检查点排查")
    return val_loss, accuracy, pred_sample


def _sync_and_prune(snapshot, run_dir, persistent, keep_last):
    synced = publish_snapshot(snapshot, persistent) if persistent else True
    # 失败期间不清理本地版本；Drive 只在成功备份后清理完整旧版本。
    if synced:
        prune(run_dir, keep_last)
        if persistent:
            prune(persistent, keep_last)
    return synced


DEFAULT_DRIVE_PERSISTENT = Path("/content/drive/MyDrive/Colab_Training_Demo/runs")


def _resolve_persistent_root(args):
    if getattr(args, "no_persistent", False):
        return None
    if args.persistent_root:
        return args.persistent_root
    drive_mount = Path("/content/drive")
    if os.path.ismount(drive_mount) and (drive_mount / "MyDrive").is_dir():
        print(f"[auto-drive] 已自动绑定 Google Drive 持久目录: {DEFAULT_DRIVE_PERSISTENT}", flush=True)
        return str(DEFAULT_DRIVE_PERSISTENT)
    if Path("/content").is_dir():
        print(
            "[warning] 当前处于 Colab 容器但未检测到 Google Drive 挂载；"
            "模型与检查点将仅保存在临时盘。请先执行 colab drivemount 或传入 --persistent-root。",
            flush=True,
        )
    return None


def train(args):
    config = apply_cli_overrides(read_config(args.config), args)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", args.run_id):
        raise ValueError("run-id 使用 1～80 位英文字母、数字、下划线、点和短横线")
    device = torch.device(
        "cuda"
        if args.device == "auto" and torch.cuda.is_available()
        else "cpu" if args.device == "auto" else args.device
    )
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("请求了 GPU，但 CUDA 不可用；请在启动笔记本选择 GPU 服务器")
    # 小任务限制 CPU 线程，避免线程调度开销大于计算开销。
    torch.set_num_threads(2)
    random.seed(config["seed"])
    np.random.seed(config["seed"])
    torch.manual_seed(config["seed"])
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config["seed"])
    torch.backends.cudnn.benchmark = False
    if device.type == "cpu":
        torch.use_deterministic_algorithms(True)
    run_dir = Path(args.local_root).resolve() / args.run_id
    resolved_persistent = _resolve_persistent_root(args)
    persistent = Path(resolved_persistent).resolve() / args.run_id if resolved_persistent else None
    if persistent == run_dir:
        raise ValueError("临时训练目录与持久目录必须分开")
    if persistent and (persistent in run_dir.parents or run_dir in persistent.parents):
        raise ValueError("临时目录和持久目录不能互相嵌套")
    if persistent:
        ensure_persistent_available(persistent)
    run_dir.mkdir(parents=True, exist_ok=True)
    with training_lock(run_dir):
        return run_locked(args, config, device, run_dir, persistent)


def run_locked(args, config, device, run_dir, persistent):
    digest = source_digest()
    state, resumed_from = None, None
    now_iso = datetime.now(timezone.utc).isoformat()
    strict_resume = bool(getattr(args, "strict_resume", False))

    if args.resume == "auto":
        state, resumed_from = load_latest([run_dir] + ([persistent] if persistent else []))
        prev_config = state["config"]
        prev_config.setdefault("checkpoint_every_steps", 0)

        if any(prev_config[key] != config[key] for key in STRUCTURAL_KEYS):
            raise ValueError("模型结构或数据生成配置（task/seed/samples/hidden_size）已改变；请更换 RUN_ID 新建实验")

        if strict_resume:
            if any(prev_config[key] != config[key] for key in STRICT_TRAINING_KEYS):
                raise ValueError("训练配置与检查点不同；续训应使用原配置，新任务请换 RUN_ID")
            if state["source_sha256"] != digest:
                raise ValueError("源码与检查点不同；请使用原实验 source.zip，或为修改后的代码新建 RUN_ID")

        if state["environment"] != {"torch": str(torch.__version__), "device": str(device)}:
            print("[warning] 硬件或 PyTorch 环境改变，可恢复训练但不保证逐位一致", flush=True)
        if config["epochs"] < state["epoch"]:
            raise ValueError("目标 epochs 小于已经完成的轮数")

        changed_params = {
            key: (prev_config.get(key), config.get(key))
            for key in TUNABLE_KEYS
            if prev_config.get(key) != config.get(key)
        }
        code_changed = state["source_sha256"] != digest
        if code_changed:
            print(
                f"[resume-debug] 检测到源码修改 ({state['source_sha256'][:12]} -> {digest[:12]})，已更新源码快照并继续训练",
                flush=True,
            )
        if changed_params:
            summary = ", ".join(f"{k}: {old} -> {new}" for k, (old, new) in changed_params.items())
            print(f"[resume-debug] 检测到训练参数变更 ({summary})，将应用新参数继续训练", flush=True)

        code_history = list(
            state.get("code_history")
            or [{"source_sha256": state["source_sha256"], "event": "initial"}]
        )
        if code_changed or changed_params:
            code_history.append(
                {
                    "source_sha256": digest,
                    "updated_utc": now_iso,
                    "event": "resume_debug",
                    "changes": {k: {"old": o, "new": n} for k, (o, n) in changed_params.items()},
                }
            )
    elif (run_dir / "config.json").exists() or (persistent and persistent.exists()):
        raise FileExistsError("RUN_ID 已存在。续训使用 --resume auto；新实验请换 RUN_ID，避免覆盖")
    else:
        code_history = [
            {
                "source_sha256": digest,
                "updated_utc": now_iso,
                "event": "initial",
                "learning_rate": config["learning_rate"],
                "batch_size": config["batch_size"],
                "epochs": config["epochs"],
            }
        ]

    model = make_model(config["task"], config["hidden_size"]).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"])
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.8)
    shuffle = torch.Generator().manual_seed(config["seed"] + 1)
    loss_fn = nn.MSELoss() if config["task"] == "regression" else nn.CrossEntropyLoss()
    tx, ty, vx, vy = [value.to(device) for value in make_data(config, run_dir / "cache")]
    start, steps, best_loss, best_epoch, best_weights = 0, 0, float("inf"), 0, None
    in_epoch_state = None

    if state:
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        if float(config["learning_rate"]) != float(state["config"]["learning_rate"]):
            new_lr = float(config["learning_rate"])
            for group in optimizer.param_groups:
                group["lr"] = new_lr
            if hasattr(scheduler, "base_lrs"):
                gamma_power = scheduler.gamma ** (scheduler.last_epoch // scheduler.step_size)
                scheduler.base_lrs = [new_lr / gamma_power for _ in scheduler.base_lrs]
            if hasattr(scheduler, "_last_lr"):
                scheduler._last_lr = [group["lr"] for group in optimizer.param_groups]
        start, steps = state["epoch"], state["global_step"]
        best_loss, best_epoch, best_weights = state["best_loss"], state["best_epoch"], state["best_model"]
        in_epoch_state = state.get("in_epoch")
        # 用检查点绑定的指标快照重建日志，丢弃中断后尚未提交的轮次。
        metrics_bytes = (resumed_from / "metrics.csv").read_bytes()
        (run_dir / "metrics.csv").write_bytes(metrics_bytes)
        restore_rng(state["rng"], shuffle)
        if in_epoch_state:
            print(
                f"[resume] completed_epoch={start}, global_step={steps}, "
                f"resuming_epoch={in_epoch_state['current_epoch']} "
                f"batch={in_epoch_state['completed_batches'] + 1}/{in_epoch_state['total_batches']}",
                flush=True,
            )
        else:
            print(f"[resume] completed_epoch={start}, global_step={steps}, next_epoch={start + 1}", flush=True)
    else:
        with (run_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as stream:
            csv.DictWriter(stream, FIELDS).writeheader()

    metadata(run_dir, config, digest, code_history)
    print(f"[environment] Python={sys.executable}, device={device}, task={config['task']}", flush=True)
    print(f"[paths] local={run_dir}\n[paths] persistent={persistent}", flush=True)
    stop_requested = False

    def request_stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
        print("[stop] 收到停止请求，当前 Batch 完成后立即保存并退出", flush=True)

    previous_handlers = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    last_save = time.monotonic()
    target = min(config["epochs"], args.stop_after_epoch or config["epochs"])
    stop_after_step = getattr(args, "stop_after_step", None)
    step_every = config["checkpoint_every_steps"]

    if target <= start or (stop_after_step is not None and steps >= stop_after_step):
        print("[done] 目标轮次或步数已完成；无需再次训练", flush=True)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        return

    last_completed_epoch = start
    mid_epoch_stopped = False
    stopped_batch_info = None

    try:
        for epoch in range(start + 1, target + 1):
            model.train()
            if in_epoch_state is not None and in_epoch_state.get("current_epoch") == epoch:
                order = in_epoch_state["order"]
                total_loss = float(in_epoch_state["total_loss"])
                seen_samples = int(in_epoch_state["seen_samples"])
                start_batch = int(in_epoch_state["completed_batches"])
                in_epoch_state = None
            else:
                order = torch.randperm(len(tx), generator=shuffle)
                total_loss = 0.0
                seen_samples = 0
                start_batch = 0

            remaining_batches = list(order[seen_samples:].split(config["batch_size"]))
            total_batches = start_batch + len(remaining_batches)
            epoch_aborted_midway = False
            grad_norm = 0.0
            batch_loss = 0.0

            for offset, indices in enumerate(remaining_batches, start=1):
                batch_idx = start_batch + offset
                indices = indices.to(device)
                optimizer.zero_grad(set_to_none=True)
                loss = loss_fn(model(tx[indices]), ty[indices])
                loss.backward()
                grad_norm = compute_grad_norm(model.parameters())
                optimizer.step()
                steps += 1
                batch_loss = float(loss.detach())
                seen_samples += len(indices)
                total_loss += batch_loss * len(indices)

                step_stop_hit = stop_after_step is not None and steps >= stop_after_step
                need_mid_save = (
                    batch_idx < total_batches
                    and (
                        stop_requested
                        or step_stop_hit
                        or (step_every > 0 and steps % step_every == 0)
                        or (time.monotonic() - last_save >= config["checkpoint_every_seconds"])
                    )
                )

                if need_mid_save:
                    val_loss_snap, val_acc_snap, val_pred_sample = evaluate_validation(
                        model, loss_fn, vx, vy, config["task"]
                    )
                    in_epoch_payload = {
                        "current_epoch": epoch,
                        "completed_batches": batch_idx,
                        "total_batches": total_batches,
                        "order": order.cpu(),
                        "total_loss": total_loss,
                        "seen_samples": seen_samples,
                    }
                    updated_utc = datetime.now(timezone.utc).isoformat()
                    mid_status = "stopped_mid_epoch" if (stop_requested or step_stop_hit) else "running_mid_epoch"
                    atomic_json(
                        run_dir / "status.json",
                        {
                            "run_id": args.run_id,
                            "epoch": epoch - 1,
                            "current_epoch": epoch,
                            "batch_idx": batch_idx,
                            "total_batches": total_batches,
                            "global_step": steps,
                            "status": mid_status,
                            "pid": os.getpid(),
                            "updated_utc": updated_utc,
                        },
                    )
                    atomic_json(
                        run_dir / "evaluation.json",
                        {
                            "epoch": epoch - 1,
                            "current_epoch": epoch,
                            "batch_idx": batch_idx,
                            "total_batches": total_batches,
                            "global_step": steps,
                            "batch_loss": batch_loss,
                            "val_loss": val_loss_snap,
                            "val_accuracy": val_acc_snap,
                            "grad_norm": grad_norm,
                            "best_epoch": best_epoch,
                            "best_val_loss": best_loss,
                        },
                    )
                    export_weights(run_dir / "last_model.pt", cpu_weights(model), config, epoch - 1, val_loss_snap)
                    if best_weights is not None:
                        export_weights(run_dir / "best_model.pt", best_weights, config, best_epoch, best_loss)
                    save_intermediate_state(
                        run_dir,
                        {
                            "run_id": args.run_id,
                            "completed_epoch": epoch - 1,
                            "current_epoch": epoch,
                            "batch_idx": batch_idx,
                            "total_batches": total_batches,
                            "global_step": steps,
                            "batch_loss": batch_loss,
                            "epoch_avg_loss_so_far": total_loss / seen_samples,
                            "grad_norm": grad_norm,
                            "learning_rate": optimizer.param_groups[0]["lr"],
                            "val_loss": val_loss_snap,
                            "val_accuracy": val_acc_snap,
                            "val_predictions_sample": val_pred_sample,
                            "custom_state": {"seen_samples": seen_samples},
                            "updated_utc": updated_utc,
                        },
                    )
                    snapshot = write_snapshot(
                        run_dir,
                        {
                            "format_version": 2,
                            "epoch": epoch - 1,
                            "global_step": steps,
                            "model": model.state_dict(),
                            "optimizer": optimizer.state_dict(),
                            "scheduler": scheduler.state_dict(),
                            "rng": rng_state(shuffle),
                            "in_epoch": in_epoch_payload,
                            "config": config,
                            "source_sha256": digest,
                            "code_history": code_history,
                            "best_loss": best_loss,
                            "best_epoch": best_epoch,
                            "best_model": best_weights,
                            "environment": {"torch": str(torch.__version__), "device": str(device)},
                        },
                    )
                    print(
                        f"[checkpoint-step] epoch={epoch} batch={batch_idx}/{total_batches} "
                        f"step={steps} batch_loss={batch_loss:.5f} grad_norm={grad_norm:.4f} -> {snapshot}",
                        flush=True,
                    )
                    _sync_and_prune(snapshot, run_dir, persistent, config["keep_last"])
                    last_save = time.monotonic()
                    if stop_requested or step_stop_hit:
                        epoch_aborted_midway = True
                        mid_epoch_stopped = True
                        stopped_batch_info = (epoch, batch_idx, total_batches, steps)
                        break

            if epoch_aborted_midway:
                break

            val_loss, accuracy, val_pred_sample = evaluate_validation(
                model, loss_fn, vx, vy, config["task"]
            )
            if val_loss < best_loss:
                best_loss, best_epoch, best_weights = val_loss, epoch, cpu_weights(model)
            used_lr = optimizer.param_groups[0]["lr"]
            scheduler.step()
            last_completed_epoch = epoch

            row = dict(zip(FIELDS, (epoch, steps, total_loss / seen_samples, val_loss, accuracy, used_lr)))
            with (run_dir / "metrics.csv").open("a", newline="", encoding="utf-8") as stream:
                csv.DictWriter(stream, FIELDS).writerow(row)
                stream.flush()
            print(
                f"epoch={epoch:03d}/{config['epochs']} step={steps} train_loss={row['train_loss']:.5f} val_loss={val_loss:.5f}"
                + (f" accuracy={accuracy:.3%}" if accuracy is not None else ""),
                flush=True,
            )

            step_stop_hit = stop_after_step is not None and steps >= stop_after_step
            should_save = (
                epoch % config["checkpoint_every_epochs"] == 0
                or (step_every > 0 and steps % step_every == 0)
                or time.monotonic() - last_save >= config["checkpoint_every_seconds"]
                or epoch == target
                or stop_requested
                or step_stop_hit
            )
            if should_save:
                completed = epoch == config["epochs"]
                updated_utc = datetime.now(timezone.utc).isoformat()
                atomic_json(
                    run_dir / "status.json",
                    {
                        "run_id": args.run_id,
                        "epoch": epoch,
                        "global_step": steps,
                        "status": "completed"
                        if completed
                        else "stopped"
                        if (stop_requested or epoch == target or step_stop_hit)
                        else "running",
                        "pid": os.getpid(),
                        "updated_utc": updated_utc,
                    },
                )
                atomic_json(
                    run_dir / "evaluation.json",
                    {**row, "best_epoch": best_epoch, "best_val_loss": best_loss, "grad_norm": grad_norm},
                )
                latest_weights = cpu_weights(model)
                export_weights(run_dir / "last_model.pt", latest_weights, config, epoch, val_loss)
                export_weights(run_dir / "best_model.pt", best_weights, config, best_epoch, best_loss)
                if completed:
                    export_weights(run_dir / "final_model.pt", latest_weights, config, epoch, val_loss)
                save_intermediate_state(
                    run_dir,
                    {
                        "run_id": args.run_id,
                        "completed_epoch": epoch,
                        "current_epoch": epoch,
                        "batch_idx": total_batches,
                        "total_batches": total_batches,
                        "global_step": steps,
                        "batch_loss": batch_loss,
                        "epoch_avg_loss_so_far": row["train_loss"],
                        "grad_norm": grad_norm,
                        "learning_rate": used_lr,
                        "val_loss": val_loss,
                        "val_accuracy": accuracy,
                        "val_predictions_sample": val_pred_sample,
                        "custom_state": {"seen_samples": seen_samples},
                        "updated_utc": updated_utc,
                    },
                )
                snapshot = write_snapshot(
                    run_dir,
                    {
                        "format_version": 2,
                        "epoch": epoch,
                        "global_step": steps,
                        "model": model.state_dict(),
                        "optimizer": optimizer.state_dict(),
                        "scheduler": scheduler.state_dict(),
                        "rng": rng_state(shuffle),
                        "in_epoch": None,
                        "config": config,
                        "source_sha256": digest,
                        "code_history": code_history,
                        "best_loss": best_loss,
                        "best_epoch": best_epoch,
                        "best_model": best_weights,
                        "environment": {"torch": str(torch.__version__), "device": str(device)},
                    },
                )
                print(f"[checkpoint] epoch={epoch} -> {snapshot}", flush=True)
                _sync_and_prune(snapshot, run_dir, persistent, config["keep_last"])
                last_save = time.monotonic()
            if stop_requested or step_stop_hit:
                break
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)

    if mid_epoch_stopped and stopped_batch_info is not None:
        ep, b_idx, t_batches, st = stopped_batch_info
        print(
            f"[done] 已在 epoch={ep} 第 {b_idx}/{t_batches} 步 (global_step={st}) 保存中断点; 最佳验证损失={best_loss:.6f}",
            flush=True,
        )
    else:
        print(f"[done] 本次完成到 epoch={last_completed_epoch}; 最佳验证损失={best_loss:.6f}", flush=True)


def _resolve_interactive_args(args, parser, default_config):
    if args.run_id:
        return args
    if sys.stdin is None or not sys.stdin.isatty():
        parser.error("非交互模式下必须指定 --run-id")
    print("=== 直接运行模式（交互式配置）===", flush=True)
    try:
        if args.config == default_config:
            choice = input("选择任务 [1] regression  [2] classification (直接回车=1): ").strip()
            task = "classification" if choice == "2" else "regression"
            args.config = str(ROOT / "configs" / f"{task}.json")
        else:
            task = Path(args.config).stem
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_id = f"{task}_direct_{stamp}"
        entered_id = input(f"输入实验名 RUN_ID (回车默认 {default_id}；填已有实验名可续训): ").strip()
        args.run_id = entered_id or default_id

        resolved_persistent = _resolve_persistent_root(args)
        if resolved_persistent and not args.persistent_root:
            args.persistent_root = resolved_persistent
        exists_local = (Path(args.local_root).resolve() / args.run_id / "config.json").is_file()
        exists_drive = bool(resolved_persistent) and (Path(resolved_persistent).resolve() / args.run_id).exists()
        if (exists_local or exists_drive) and args.resume == "never":
            ans = input(f"检测到已有实验 '{args.run_id}'，是否从上次断点续训? [Y/n] (直接回车=是): ").strip().lower()
            if ans in ("", "y", "yes"):
                args.resume = "auto"

        if args.epochs is None:
            ep_raw = input("目标总轮数 epochs (直接回车保持配置默认值): ").strip()
            if ep_raw:
                args.epochs = int(ep_raw)
        if args.lr is None:
            lr_raw = input("学习率 lr (直接回车保持配置默认值): ").strip()
            if lr_raw:
                args.lr = float(lr_raw)
    except EOFError:
        parser.error("非交互模式下必须指定 --run-id")
    return args


def main():
    default_config = str(ROOT / "configs" / "regression.json")
    default_local = "/content/runs" if Path("/content").is_dir() else str(ROOT / "runs")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=default_config)
    parser.add_argument("--run-id", default=None, help="实验名；直接运行且未传入时将进入交互配置")
    parser.add_argument("--local-root", default=default_local)
    parser.add_argument("--persistent-root", default=None, help="Drive 结果根目录；在 Colab 挂载 Drive 后默认自动使用")
    parser.add_argument("--no-persistent", action="store_true", help="禁用自动绑定 Google Drive，仅写本地目录")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--resume", choices=("never", "auto"), default="never")
    parser.add_argument("--stop-after-epoch", type=int, default=None, help="完成指定轮次后退出，用于恢复演练")
    parser.add_argument("--stop-after-step", type=int, default=None, help="完成指定 global_step 后立即保存并退出")
    parser.add_argument("--checkpoint-every-steps", type=int, default=None, help="每 N 个 step 自动保存一次中间检查点")
    parser.add_argument("--lr", type=float, default=None, help="覆盖配置中的学习率（支持调试续训调参）")
    parser.add_argument("--epochs", type=int, default=None, help="覆盖配置中的总训练轮数")
    parser.add_argument("--batch-size", type=int, default=None, help="覆盖配置中的 batch_size")
    parser.add_argument("--strict-resume", action="store_true", help="开启严格模式：源码或超参变动时拒绝续训")
    args = parser.parse_args()
    args = _resolve_interactive_args(args, parser, default_config)
    if args.stop_after_epoch is not None and args.stop_after_epoch <= 0:
        parser.error("stop-after-epoch 必须大于 0")
    if args.stop_after_step is not None and args.stop_after_step <= 0:
        parser.error("stop-after-step 必须大于 0")
    if args.checkpoint_every_steps is not None and args.checkpoint_every_steps < 0:
        parser.error("checkpoint-every-steps 必须为非负整数")
    if args.lr is not None and (not math.isfinite(args.lr) or args.lr <= 0):
        parser.error("lr 必须为有限正数")
    if args.epochs is not None and args.epochs <= 0:
        parser.error("epochs 必须大于 0")
    if args.batch_size is not None and args.batch_size <= 0:
        parser.error("batch-size 必须大于 0")
    train(args)


if __name__ == "__main__":
    main()
