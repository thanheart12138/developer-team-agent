"""手动付费实验的持久目录与调用计数，不加载模型或正式数据库。"""

import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile


EXPERIMENTS_ROOT = Path(__file__).resolve().parents[1] / "workspace" / "experiments"
ROOT_README = """# 隔离实验留存

本目录保存付费实验，不属于正式任务；由 workspace/ Git 忽略规则排除。
每个子目录是一个独立实验，恢复使用原目录和计数，不因恢复获得新预算。
目录约定与运行范围见项目 docs/README.md；此目录不是异地备份。
"""
RUN_README = """# 实验工作目录

- test.db：隔离 SQLite 状态；workspace/：依据、生成产品、Trace 和检查点。
- call-count.json：调用前保存的原计数；恢复不重置。
- sent-requests/ 或 sent-*.json：仅保存脱敏模型正文，不保存认证头或环境正文。
- 控制脚本、运行日志、结果和截图应保存在本目录；已跟踪的 tests/ 入口可直接复用。
- 本目录保留完整断点，必要脱敏结论另存 docs/evidence/，不代表用户已验收。
"""


def experiment_path(path: str | Path) -> Path:
    """只接受持久实验目录内的独立子目录，拒绝临时路径及越界软链接。"""
    if EXPERIMENTS_ROOT.is_symlink():
        raise ValueError("experiment_storage_root_must_not_be_symlink")
    root = Path(path).resolve()
    base = EXPERIMENTS_ROOT.resolve()
    if root == base or base not in root.parents:
        raise ValueError("experiment_root_outside_persistent_directory")
    return root


def read_call_count(root: Path) -> int:
    """读取保存的合法计数，缺失或损坏时停止，不猜测历史次数。"""
    value = json.loads((experiment_path(root) / "call-count.json").read_text(encoding="utf-8"))
    if type(value) is not int or value < 0:
        raise ValueError("experiment_call_count_invalid")
    return value


def save_call_count(root: Path, count: int) -> None:
    """在调用前原子保存单进程计数，拒绝把已保存次数调低。"""
    root = experiment_path(root)
    if type(count) is not int or count < 0:
        raise ValueError("experiment_call_count_invalid")
    target = root / "call-count.json"
    if target.exists() and count < read_call_count(root):
        raise ValueError("experiment_call_count_cannot_decrease")
    # 先刷新临时文件再替换，进程中断时不留下截断的正式计数。
    temporary = target.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(count, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)


def prepare_experiment_root(prefix: str, path: str | Path | None = None,
                            *, resume: bool = False) -> Path:
    """新建独立持久实验，或只读核对原库、工作区与计数后恢复。"""
    if EXPERIMENTS_ROOT.is_symlink():
        raise ValueError("experiment_storage_root_must_not_be_symlink")
    if resume:
        if path is None:
            raise ValueError("experiment_resume_root_required")
        root = experiment_path(path)
        # 在 Runtime 导入及建库之前拒绝缺失断点；不要求无工具 Run 有检查点。
        if not (root / "test.db").is_file():
            raise FileNotFoundError("experiment_database_missing")
        if not (root / "workspace").is_dir():
            raise FileNotFoundError("experiment_workspace_missing")
        read_call_count(root)
        # 只读核验原 SQLite，损坏数据库不能在后续建表时被当成正常断点。
        try:
            with closing(sqlite3.connect((root / "test.db").as_uri() + "?mode=ro", uri=True)) as db:
                healthy = db.execute("PRAGMA quick_check").fetchone() == ("ok",)
        except sqlite3.DatabaseError as exc:
            raise ValueError("experiment_database_invalid") from exc
        if not healthy:
            raise ValueError("experiment_database_invalid")
        return root

    root = experiment_path(path) if path is not None else None
    if root is not None and root.exists() and any(root.iterdir()):
        raise FileExistsError("experiment_root_not_empty_use_resume")
    # 先保存结构约定，再创建本次目录；mkdtemp 的父目录显式指向项目持久位置。
    EXPERIMENTS_ROOT.mkdir(parents=True, exist_ok=True)
    readme = EXPERIMENTS_ROOT / "README.md"
    if not readme.exists():
        readme.write_text(ROOT_README, encoding="utf-8")
    if root is None:
        root = Path(tempfile.mkdtemp(prefix=prefix, dir=EXPERIMENTS_ROOT)).resolve()
    else:
        root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(RUN_README, encoding="utf-8")
    save_call_count(root, 0)
    return root
