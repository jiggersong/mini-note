"""Health Check — workspace 健康状态诊断。"""

from pathlib import Path


def run_health_check(workspace: Path) -> dict:
    """执行健康检查，返回 JSON 兼容的报告。

    Returns:
        {"ok": bool, "checks": [{"name": str, "passed": bool, "detail": str}]}
    """
    checks = []

    # 1. 目录完整性
    required_dirs = [
        "meta", "raw/archive", "raw/extracted", "raw/inbox",
        "wiki", ".state",
    ]
    for d in required_dirs:
        p = workspace / d
        checks.append({
            "name": f"目录存在: {d}",
            "passed": p.is_dir(),
            "detail": "OK" if p.is_dir() else "缺失",
        })

    # 2. 关键文件存在
    required_files = [
        "wiki/index.md",
        "wiki/overview.md",
        "wiki/log.md",
        "meta/purpose.md",
    ]
    for f in required_files:
        p = workspace / f
        checks.append({
            "name": f"文件存在: {f}",
            "passed": p.is_file(),
            "detail": "OK" if p.is_file() else "缺失",
        })

    # 3. SQLite 可读（如存在）
    db_path = workspace / ".state" / "notes.db"
    if db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            conn.execute("SELECT 1")
            conn.close()
            checks.append({
                "name": "SQLite 可读",
                "passed": True,
                "detail": "OK",
            })
        except Exception as e:
            checks.append({
                "name": "SQLite 可读",
                "passed": False,
                "detail": str(e),
            })
    else:
        checks.append({
            "name": "SQLite 可读",
            "passed": True,
            "detail": "notes.db 不存在（首次运行前正常）",
        })

    # 汇总
    all_ok = all(c["passed"] for c in checks)
    return {
        "ok": all_ok,
        "checks": checks,
    }
