"""多目录源码扫描与 Google Drive 工作区同步/恢复工具（仅依赖标准库）。"""

import hashlib
import os
from pathlib import Path
import shutil


ROOT_EXTRA_FILES = (
    "requirements-colab.txt",
    "build_colab_zip.py",
    "README.md",
    "启动Colab.ipynb",
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_if_changed(source: Path, target: Path) -> bool:
    """SHA-256 不同或目标不存在时才复制，返回是否发生复制。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = _file_sha256(source)
    if target.is_file() and _file_sha256(target) == expected:
        return False
    temporary = target.with_name(target.name + ".syncing")
    shutil.copyfile(source, temporary)
    if _file_sha256(temporary) != expected:
        temporary.unlink(missing_ok=True)
        raise OSError(f"同步校验失败: {target}")
    os.replace(temporary, target)
    return True


def iter_source_files(root: Path) -> list[Path]:
    """递归扫描包内所有 .py 源码及依赖声明，按相对路径排序。"""
    root = Path(root)
    package_dir = root / "colab_training_demo"
    py_files = sorted(
        (p for p in package_dir.rglob("*.py") if "__pycache__" not in p.parts),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    req_file = root / "requirements-colab.txt"
    if req_file.is_file():
        py_files.append(req_file)
    return py_files


def iter_config_files(root: Path) -> list[Path]:
    """递归扫描 configs/ 下所有 JSON 配置文件。"""
    root = Path(root)
    configs_dir = root / "configs"
    if not configs_dir.is_dir():
        return []
    return sorted(
        (p for p in configs_dir.rglob("*.json") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix(),
    )


def iter_project_files(root: Path) -> list[Path]:
    """汇总打包或同步至云盘的全部工程文件（去重并排序）。"""
    root = Path(root)
    collected: dict[str, Path] = {}
    for path in iter_source_files(root) + iter_config_files(root):
        collected[path.relative_to(root).as_posix()] = path
    for name in ROOT_EXTRA_FILES:
        candidate = root / name
        if candidate.is_file():
            collected[candidate.relative_to(root).as_posix()] = candidate
    return [collected[key] for key in sorted(collected)]


def sync_workspace_to_drive(project_root: Path, drive_workspace_root: Path) -> dict[str, list[str]]:
    """将本地/Colab 临时盘多目录源码与配置增量同步到 Google Drive 持久化目录。"""
    project_root = Path(project_root).resolve()
    drive_workspace_root = Path(drive_workspace_root)
    drive_workspace_root.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    unchanged: list[str] = []
    for source in iter_project_files(project_root):
        rel = source.relative_to(project_root)
        target = drive_workspace_root / rel
        if _copy_if_changed(source, target):
            copied.append(rel.as_posix())
        else:
            unchanged.append(rel.as_posix())
    return {"copied": copied, "unchanged": unchanged}


def restore_workspace_from_drive(drive_workspace_root: Path, target_root: Path) -> Path:
    """新实例未上传代码时，从 Google Drive 备份工作区恢复完整多目录工程。"""
    drive_workspace_root = Path(drive_workspace_root)
    entry = drive_workspace_root / "colab_training_demo" / "train.py"
    if not entry.is_file():
        raise FileNotFoundError(f"Drive 工作区未找到可恢复项目: {drive_workspace_root}")
    target_root = Path(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    for source in drive_workspace_root.rglob("*"):
        if not source.is_file():
            continue
        if "__pycache__" in source.parts or source.suffix in (".pyc", ".syncing", ".tmp"):
            continue
        rel = source.relative_to(drive_workspace_root)
        _copy_if_changed(source, target_root / rel)
    return target_root.resolve()
