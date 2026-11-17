"""端到端验证真实训练和恢复路径，不需要 Colab 或互联网。"""

import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import torch

from colab_training_demo import checkpoint
from colab_training_demo.train import DEFAULT_DRIVE_PERSISTENT, _resolve_persistent_root, training_lock
from colab_training_demo.utils.code_sync import (
    restore_workspace_from_drive,
    sync_workspace_to_drive,
)

ROOT = Path(__file__).resolve().parents[1]


class TrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="colab-demo-tests-")
        cls.work = Path(cls.temporary.name)
        config = json.loads((ROOT / "configs" / "regression.json").read_text(encoding="utf-8"))
        config.update(epochs=6, train_samples=256, val_samples=128, hidden_size=16, batch_size=64)
        cls.config = cls.work / "regression.json"
        cls.config.write_text(json.dumps(config), encoding="utf-8")
        cls.invoke("full")
        cls.invoke("split", "--stop-after-epoch", "3")
        cls.invoke("split", "--resume", "auto")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @classmethod
    def invoke(cls, run_id, *extra, local="local", persistent="drive", config=None, success=True):
        command = [
            sys.executable,
            "-u",
            "-m",
            "colab_training_demo.train",
            "--config",
            str(config or cls.config),
            "--run-id",
            run_id,
            "--local-root",
            str(cls.work / local),
            "--device",
            "cpu",
        ]
        if persistent:
            command += ["--persistent-root", str(cls.work / persistent)]
        else:
            command += ["--no-persistent"]
        result = subprocess.run(
            command + list(extra),
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        if success and result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        if not success and result.returncode == 0:
            raise AssertionError("预期拒绝运行，但进程成功退出")
        return result

    def latest(self, run_id, directory="local"):
        state, _ = checkpoint.load_latest([self.work / directory / run_id])
        return state

    def assert_nested_equal(self, first, second):
        if isinstance(first, torch.Tensor):
            self.assertTrue(torch.equal(first, second))
        elif isinstance(first, dict):
            self.assertEqual(first.keys(), second.keys())
            for key in first:
                self.assert_nested_equal(first[key], second[key])
        elif isinstance(first, (list, tuple)):
            self.assertEqual(len(first), len(second))
            for a, b in zip(first, second):
                self.assert_nested_equal(a, b)
        else:
            self.assertEqual(first, second)

    def test_resume_matches_continuous_training(self):
        full, resumed = self.latest("full"), self.latest("split")
        for key in ("model", "optimizer", "scheduler", "rng", "best_model", "best_loss", "epoch", "global_step"):
            self.assert_nested_equal(full[key], resumed[key])
        self.assertEqual(full["epoch"], 6)
        self.assertEqual(full["global_step"], 24)
        self.assertLess(full["best_loss"], 0.8)
        self.assertEqual(
            (self.work / "local/full/metrics.csv").read_bytes(),
            (self.work / "local/split/metrics.csv").read_bytes(),
        )

    def test_mid_epoch_step_resume_matches_continuous_training(self):
        # 256 样本 / batch 64 = 每轮 4 步；step=6 对应第 2 轮第 2 个 batch 边界。
        stop_result = self.invoke(
            "mid_step",
            "--stop-after-step",
            "6",
            "--checkpoint-every-steps",
            "3",
        )
        self.assertIn("[checkpoint-step]", stop_result.stdout)
        local_mid = self.work / "local/mid_step/checkpoints/epoch_00000001_step_00000006"
        drive_mid = self.work / "drive/mid_step/checkpoints/epoch_00000001_step_00000006"
        self.assertTrue(checkpoint.valid_snapshot(local_mid))
        self.assertTrue(checkpoint.valid_snapshot(drive_mid))
        self.assertTrue((self.work / "drive/mid_step/last_model.pt").is_file())
        inter_path = self.work / "drive/mid_step/intermediate_state.pt"
        self.assertTrue(inter_path.is_file())
        inter = torch.load(inter_path, map_location="cpu", weights_only=True)
        self.assertEqual(inter["completed_epoch"], 1)
        self.assertEqual(inter["current_epoch"], 2)
        self.assertEqual(inter["batch_idx"], 2)
        self.assertEqual(inter["total_batches"], 4)
        self.assertEqual(inter["global_step"], 6)
        self.assertGreaterEqual(inter["grad_norm"], 0.0)

        # 从全新本地临时目录仅依靠 Drive 中断快照继续训练，验证与连续训练逐位一致。
        resumed_out = self.invoke("mid_step", "--resume", "auto", local="mid_fresh_vm")
        self.assertIn("resuming_epoch=2 batch=3/4", resumed_out.stdout)
        full, resumed = self.latest("full"), self.latest("mid_step", "mid_fresh_vm")
        for key in ("model", "optimizer", "scheduler", "rng", "best_model", "best_loss", "epoch", "global_step"):
            self.assert_nested_equal(full[key], resumed[key])
        self.assertEqual(
            (self.work / "local/full/metrics.csv").read_bytes(),
            (self.work / "mid_fresh_vm/mid_step/metrics.csv").read_bytes(),
        )

    def test_flexible_debug_resume_allows_code_and_param_changes(self):
        self.invoke("debug_run", "--stop-after-epoch", "2", local="debug_local", persistent=None)
        run_dir = self.work / "debug_local/debug_run"
        state, _ = checkpoint.load_latest([run_dir])
        state["source_sha256"] = "edited-code-sha256"
        checkpoint.write_snapshot(run_dir, state)

        # 开启 --strict-resume 时应拒绝
        strict = self.invoke(
            "debug_run",
            "--resume",
            "auto",
            "--strict-resume",
            local="debug_local",
            persistent=None,
            success=False,
        )
        self.assertIn("ValueError", strict.stderr)
        self.assertIn("source.zip", strict.stderr)

        # 默认灵活调试模式下，同时修改源码哈希、学习率和总轮数可以直接续训
        resumed = self.invoke(
            "debug_run",
            "--resume",
            "auto",
            "--lr",
            "0.0005",
            "--epochs",
            "8",
            local="debug_local",
            persistent=None,
        )
        self.assertIn("[resume-debug]", resumed.stdout)
        final_state = self.latest("debug_run", "debug_local")
        self.assertEqual(final_state["epoch"], 8)
        with (run_dir / "metrics.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 8)
        self.assertAlmostEqual(float(rows[2]["learning_rate"]), 0.0005, places=7)
        code_meta = json.loads((run_dir / "code_version.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(code_meta["history"]), 2)

    def test_workspace_sync_and_restore(self):
        drive_ws = self.work / "drive_workspace"
        first = sync_workspace_to_drive(ROOT, drive_ws)
        self.assertIn("colab_training_demo/models/mlp.py", first["copied"])
        self.assertIn("colab_training_demo/datasets/synthetic.py", first["copied"])
        self.assertIn("colab_training_demo/utils/code_sync.py", first["copied"])
        self.assertIn("colab_training_demo/utils/state_bag.py", first["copied"])
        self.assertIn("configs/regression.json", first["copied"])

        second = sync_workspace_to_drive(ROOT, drive_ws)
        self.assertEqual(second["copied"], [])

        restored_dir = self.work / "restored_workspace"
        restored = restore_workspace_from_drive(drive_ws, restored_dir)
        self.assertTrue((restored / "colab_training_demo/train.py").is_file())
        self.assertTrue((restored / "colab_training_demo/models/mlp.py").is_file())
        self.assertTrue((restored / "colab_training_demo/datasets/synthetic.py").is_file())
        self.assertTrue((restored / "colab_training_demo/utils/state_bag.py").is_file())

    def test_restore_on_fresh_local_disk_from_persistent_only(self):
        self.invoke("fresh", "--stop-after-epoch", "3")
        result = self.invoke("fresh", "--resume", "auto", local="fresh_vm")
        self.assertIn("completed_epoch=3", result.stdout)
        restored = self.latest("fresh", "fresh_vm")
        self.assert_nested_equal(self.latest("full")["model"], restored["model"])
        self.assertTrue((self.work / "fresh_vm/fresh/final_model.pt").is_file())

    def test_corrupt_latest_falls_back_and_rebuilds_metrics(self):
        drive_run = self.work / "broken_drive" / "recovery"
        shutil.copytree(self.work / "drive/full", drive_run)
        newest = drive_run / "checkpoints/epoch_00000006"
        (newest / "state.pt").write_bytes(b"interrupted copy")
        partial = drive_run / "checkpoints/epoch_00000007"
        partial.mkdir()
        (partial / "state.pt.uploading").write_bytes(b"partial")
        result = self.invoke("recovery", "--resume", "auto", local="recovered_vm", persistent="broken_drive")
        self.assertIn("completed_epoch=5", result.stdout)
        self.assertIn("[skip]", result.stdout)
        self.assert_nested_equal(self.latest("full")["model"], self.latest("recovery", "recovered_vm")["model"])
        with (self.work / "recovered_vm/recovery/metrics.csv").open(encoding="utf-8", newline="") as stream:
            self.assertEqual([int(row["epoch"]) for row in csv.DictReader(stream)], list(range(1, 7)))

    def test_failed_backup_preserves_local_snapshot_and_can_retry(self):
        source = self.work / "local/full/checkpoints/epoch_00000006"
        destination = self.work / "retry_drive" / "full"
        with mock.patch.object(checkpoint, "copy_verified", side_effect=OSError("simulated Drive offline")):
            self.assertFalse(checkpoint.publish_snapshot(source, destination, retries=1))
        self.assertTrue(checkpoint.valid_snapshot(source))
        self.assertFalse(checkpoint.valid_snapshot(destination / "checkpoints" / source.name))
        self.assertTrue(checkpoint.publish_snapshot(source, destination, retries=1))
        self.assertTrue(checkpoint.valid_snapshot(destination / "checkpoints" / source.name))

    def test_refuse_missing_checkpoint_existing_run_and_strict_or_structural_mismatch(self):
        missing = self.invoke("missing", "--resume", "auto", success=False)
        self.assertIn("FileNotFoundError", missing.stderr)
        duplicate = self.invoke("full", success=False)
        self.assertIn("FileExistsError", duplicate.stderr)

        # 严格模式拒绝学习率变更
        modified = json.loads(self.config.read_text(encoding="utf-8"))
        modified["learning_rate"] *= 2
        changed = self.work / "changed.json"
        changed.write_text(json.dumps(modified), encoding="utf-8")
        before = (self.work / "local/full/metrics.csv").read_bytes()
        mismatch = self.invoke("full", "--resume", "auto", "--strict-resume", config=changed, success=False)
        self.assertIn("ValueError", mismatch.stderr)
        self.assertEqual(before, (self.work / "local/full/metrics.csv").read_bytes())

        # 结构性配置变更（hidden_size）始终拒绝续训
        structural = json.loads(self.config.read_text(encoding="utf-8"))
        structural["hidden_size"] *= 2
        structural_path = self.work / "structural.json"
        structural_path.write_text(json.dumps(structural), encoding="utf-8")
        structural_err = self.invoke("full", "--resume", "auto", config=structural_path, success=False)
        self.assertIn("ValueError", structural_err.stderr)

    def test_strict_refuse_changed_source(self):
        run = self.work / "tampered_local" / "source_mismatch"
        shutil.copytree(self.work / "local/full", run)
        state, _ = checkpoint.load_latest([run])
        state["source_sha256"] = "wrong-code-version"
        checkpoint.write_snapshot(run, state)
        result = self.invoke(
            "source_mismatch",
            "--resume",
            "auto",
            "--strict-resume",
            local="tampered_local",
            persistent=None,
            success=False,
        )
        self.assertIn("ValueError", result.stderr)
        self.assertIn("source.zip", result.stderr)

    def test_exclusive_training_lock(self):
        run = self.work / "local/locked"
        run.mkdir(parents=True)
        with training_lock(run):
            result = self.invoke("locked", success=False)
        self.assertIn("RuntimeError", result.stderr)
        self.assertFalse((run / "metrics.csv").exists())

    def test_missing_drive_mount_is_not_treated_as_persistent_disk(self):
        with mock.patch.object(checkpoint.os.path, "ismount", return_value=False):
            with self.assertRaises(OSError):
                checkpoint.ensure_persistent_available(Path("/content/drive/MyDrive/example"))

    def test_invalid_completion_marker_is_rejected(self):
        folder = self.work / "invalid_marker"
        folder.mkdir()
        (folder / "complete.json").write_text(
            json.dumps({"files": ["state.pt", "metrics.csv"]}),
            encoding="utf-8",
        )
        self.assertFalse(checkpoint.valid_snapshot(folder))

    def test_classification_task_trains(self):
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config.update(task="classification", epochs=12, train_samples=2048, val_samples=512, hidden_size=32)
        path = self.work / "classification.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        self.invoke("classification", config=path)
        metrics = json.loads((self.work / "local/classification/evaluation.json").read_text(encoding="utf-8"))
        self.assertGreater(metrics["val_accuracy"], 0.9)
        state = self.latest("classification")
        self.assertEqual(state["epoch"], 12)
        complete = [p for p in checkpoint.snapshots(self.work / "drive/classification") if checkpoint.valid_snapshot(p)]
        self.assertEqual(len(complete), 3)

    def test_direct_script_execution_and_auto_drive(self):
        direct_cmd = [
            sys.executable,
            "-u",
            str(ROOT / "colab_training_demo" / "train.py"),
            "--config",
            str(self.config),
            "--run-id",
            "direct_script_run",
            "--local-root",
            str(self.work / "direct_local"),
            "--persistent-root",
            str(self.work / "direct_drive"),
            "--device",
            "cpu",
            "--epochs",
            "2",
        ]
        result = subprocess.run(
            direct_cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        drive_out = self.work / "direct_drive/direct_script_run"
        self.assertTrue((drive_out / "final_model.pt").is_file())
        self.assertTrue((drive_out / "best_model.pt").is_file())
        self.assertTrue((drive_out / "intermediate_state.pt").is_file())
        self.assertTrue(checkpoint.valid_snapshot(drive_out / "checkpoints/epoch_00000002"))

        non_tty = subprocess.run(
            [sys.executable, "-u", str(ROOT / "colab_training_demo" / "train.py")],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertNotEqual(non_tty.returncode, 0)
        self.assertIn("run-id", non_tty.stderr)

        ns = type("Args", (), {"persistent_root": None, "no_persistent": False})()
        with mock.patch("colab_training_demo.train.os.path.ismount", return_value=True), mock.patch.object(
            Path, "is_dir", return_value=True
        ):
            self.assertEqual(_resolve_persistent_root(ns), str(DEFAULT_DRIVE_PERSISTENT))
        ns_off = type("Args", (), {"persistent_root": None, "no_persistent": True})()
        self.assertIsNone(_resolve_persistent_root(ns_off))


if __name__ == "__main__":
    unittest.main()
