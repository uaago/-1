"""科研工程通用工具包：代码递归扫描/云盘同步与中间状态保存。"""

from .code_sync import (
    iter_config_files,
    iter_project_files,
    iter_source_files,
    restore_workspace_from_drive,
    sync_workspace_to_drive,
)
from .state_bag import compute_grad_norm, save_intermediate_state

__all__ = [
    "compute_grad_norm",
    "iter_config_files",
    "iter_project_files",
    "iter_source_files",
    "restore_workspace_from_drive",
    "save_intermediate_state",
    "sync_workspace_to_drive",
]
