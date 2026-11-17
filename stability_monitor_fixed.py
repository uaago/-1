print("[监控 cell] 已开始执行（限时监控 v2）", flush=True)

import csv
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import subprocess
import time

# ===== 可调参数 =====
INTERVAL_SECONDS = 60   # 每隔多少秒记录一次心跳（建议 30~60）
MAX_MINUTES = 10        # 监控总时长（分钟），必须大于 0；到时自动结束当前 cell
ENABLE_GPU_PULSE = False # 默认仅读取 GPU 状态；True 会额外初始化 CUDA 并执行矩阵计算
BJ_TZ = timezone(timedelta(hours=8))

if INTERVAL_SECONDS <= 0 or MAX_MINUTES <= 0:
    raise ValueError("INTERVAL_SECONDS 和 MAX_MINUTES 必须大于 0，避免无限监控。")


def wait_for_next_sample(deadline):
    # 不再整段等待 60 秒；每秒检查截止时间。
    next_sample = min(time.monotonic() + INTERVAL_SECONDS, deadline)
    while True:
        remaining = next_sample - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))

def get_vm_uptime_hours():
    try:
        seconds = float(Path("/proc/uptime").read_text().split()[0])
        return seconds / 3600.0
    except OSError:
        return 0.0

def get_ram_gb():
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, val = line.split(":", 1)
            info[key] = int(val.strip().split()[0])
        total = info["MemTotal"] / (1024 ** 2)
        avail = info.get("MemAvailable", info["MemFree"]) / (1024 ** 2)
        return total - avail, total
    except (OSError, KeyError, ValueError):
        return 0.0, 0.0

def get_gpu_info():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=5
        ).stdout.strip().splitlines()[0]
        name, util, mem_u, mem_t, temp = [x.strip() for x in out.split(",")]
        return name, f"{util}%", f"{mem_u}/{mem_t} MB", f"{temp}C"
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        # 查询失败时不再调用 CUDA，避免监控本身卡在 CUDA 初始化。
        return "GPU状态未知（查询失败）", "-", "-", "-"

def is_training_alive():
    try:
        out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, check=True, timeout=5).stdout
        return any("colab_training_demo.train" in line for line in out.splitlines())
    except Exception:
        return False

start_dt = datetime.now(BJ_TZ)
start_mono = time.monotonic()
deadline_mono = start_mono + MAX_MINUTES * 60
print("=" * 72, flush=True)
print(f"本次启动: {start_dt:%Y-%m-%d %H:%M:%S}（北京时间）", flush=True)
print(f"启动服务器稳定性监控 | 采样间隔: {INTERVAL_SECONDS}s | 时长限制: {MAX_MINUTES} 分钟", flush=True)
print("[初始化] 正在检查 Drive 并创建心跳日志……", flush=True)
log_file = None
drive_ok = os.path.ismount("/content/drive") and Path("/content/drive/MyDrive").is_dir()
if drive_ok:
    log_dir = Path("/content/drive/MyDrive/Colab_Training_Demo/stability_monitor")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"heartbeat_{start_dt.strftime('%Y%m%d_%H%M%S')}.csv"
    with log_file.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            "beijing_time", "elapsed_min", "vm_uptime_hr", "gpu", "gpu_util",
            "vram", "gpu_temp", "ram_used_gb", "ram_total_gb", "disk_free_gb",
            "drive_mounted", "training_running"
        ])

drive_status = str(log_file) if log_file else "未挂载 Drive（仅屏幕输出）"
print(f"Drive 心跳落盘: {drive_status}", flush=True)
pulse_a = pulse_b = None
if ENABLE_GPU_PULSE:
    print("[初始化] 正在导入 PyTorch 并初始化 CUDA……", flush=True)
    import torch
    if torch.cuda.is_available():
        pulse_a = torch.randn(1024, 1024, device="cuda")
        pulse_b = torch.randn(1024, 1024, device="cuda")
print(f"[初始化完成] 开始采样；之后每 {INTERVAL_SECONDS} 秒输出一次。", flush=True)
print("=" * 72, flush=True)

count = 0
try:
    while True:
        if time.monotonic() >= deadline_mono:
            print(f"\n已达到设定监控时长 {MAX_MINUTES} 分钟，自动结束。", flush=True)
            break
        count += 1
        now_str = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
        elapsed_min = (time.monotonic() - start_mono) / 60.0
        if pulse_a is not None:
            _ = torch.matmul(pulse_a, pulse_b)
            torch.cuda.synchronize()
        gpu_name, gpu_util, vram, temp = get_gpu_info()
        ram_u, ram_t = get_ram_gb()
        disk_free = shutil.disk_usage("/content").free / (1024 ** 3)
        drive_mounted = os.path.ismount("/content/drive") and Path("/content/drive/MyDrive").is_dir()
        train_alive = is_training_alive()
        vm_hr = get_vm_uptime_hours()

        print(
            f"[{now_str}] #{count:04d} | 已连 {elapsed_min:6.1f}m | VM运行 {vm_hr:.2f}h | "
            f"{gpu_name} 负载:{gpu_util} 显存:{vram} 温度:{temp} | "
            f"内存:{ram_u:.1f}/{ram_t:.1f}GB | 磁盘余:{disk_free:.1f}GB | "
            f"Drive:{'OK' if drive_mounted else 'LOST'} | 训练进程:{'运行中' if train_alive else '无'}",
            flush=True
        )

        if log_file is not None and drive_mounted:
            with log_file.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    now_str, f"{elapsed_min:.2f}", f"{vm_hr:.2f}", gpu_name, gpu_util,
                    vram, temp, f"{ram_u:.2f}", f"{ram_t:.2f}", f"{disk_free:.2f}",
                    drive_mounted, train_alive
                ])
                f.flush()

        wait_for_next_sample(deadline_mono)
except KeyboardInterrupt:
    total_min = (time.monotonic() - start_mono) / 60.0
    print(f"\n[已手动停止监控] 累计稳定在线 {total_min:.1f} 分钟（共 {count} 次心跳）")
    if log_file:
        print(f"完整心跳日志已保存在 Drive: {log_file}")
