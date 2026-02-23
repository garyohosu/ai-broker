"""
ユーティリティ: ロック管理・日付ユーティリティ・ロギング・git操作
"""
import os
import json
import logging
import subprocess
import sys
import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


# ─── 日付ユーティリティ ────────────────────────────────────────────────────────

def get_today() -> str:
    """今日の日付を YYYY-MM-DD 形式で返す（JST）"""
    jst = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(jst).strftime("%Y-%m-%d")


def get_yesterday_str(date_str: str) -> str:
    """前日の日付文字列を返す（土日をスキップしない）"""
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return (dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def get_prev_business_day(date_str: str) -> str:
    """前営業日を返す（土日をスキップ）"""
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    dt -= datetime.timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= datetime.timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def is_weekday(date_str: str = None) -> bool:
    """指定日（省略時は今日）が平日かどうか"""
    if date_str is None:
        date_str = get_today()
    return datetime.datetime.strptime(date_str, "%Y-%m-%d").weekday() < 5


def is_monday(date_str: str = None) -> bool:
    """指定日が月曜日かどうか"""
    if date_str is None:
        date_str = get_today()
    return datetime.datetime.strptime(date_str, "%Y-%m-%d").weekday() == 0


def get_day_of_week(date_str: str = None) -> int:
    """曜日を返す（0=月, 5=土, 6=日）"""
    if date_str is None:
        date_str = get_today()
    return datetime.datetime.strptime(date_str, "%Y-%m-%d").weekday()


def get_week_number(date_str: str) -> str:
    """ISO週番号文字列を返す（例: 2025-W03）"""
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%G-W%V")


def get_last_saturday(date_str: str) -> str:
    """指定日以前の直近土曜日を返す（当日が土曜なら当日）"""
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    days_since_sat = (dt.weekday() - 5) % 7
    return (dt - datetime.timedelta(days=days_since_sat)).strftime("%Y-%m-%d")


# ─── ロック管理 ──────────────────────────────────────────────────────────────

LOCK_DIR = ROOT / "STATE" / "lock"


def acquire_lock(date_str: str, job_type: str) -> bool:
    """ロックを取得する。既に存在する場合は False を返す"""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = LOCK_DIR / f"{date_str}_{job_type}.lock"
    if lock_file.exists():
        return False
    lock_file.write_text(
        json.dumps({"acquired_at": datetime.datetime.now().isoformat(), "job_type": job_type}),
        encoding="utf-8"
    )
    return True


def release_lock(date_str: str, job_type: str):
    """ロックを解放する"""
    lock_file = LOCK_DIR / f"{date_str}_{job_type}.lock"
    if lock_file.exists():
        lock_file.unlink()


# ─── 状態管理 ────────────────────────────────────────────────────────────────

def write_state(status: str, error: str = None, date_str: str = None, job_type: str = None):
    """STATE/last_run.json に実行状態を書き込む"""
    state_file = ROOT / "STATE" / "last_run.json"
    state = {
        "date": date_str or get_today(),
        "job_type": job_type or "unknown",
        "status": status,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    if error:
        state["error"] = str(error)[:500]
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── ロギング ────────────────────────────────────────────────────────────────

def setup_logging(name: str = "ai-broker") -> logging.Logger:
    """ロギングを設定して Logger を返す"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger(name)


# ─── JSON ファイル操作 ────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    """JSON ファイルを読み込む。存在しない場合は {} を返す"""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_json(path: Path, data: dict, indent: int = 2):
    """dict を JSON ファイルに保存する"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")


# ─── git 操作 ────────────────────────────────────────────────────────────────

def git_add_all():
    """git add -A"""
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)


def git_commit(message: str):
    """git commit"""
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)


def git_push():
    """git push"""
    subprocess.run(["git", "push"], cwd=ROOT, check=True)


def git_pull():
    """git pull（unstaged changes があっても自動 stash して安全に実行）"""
    subprocess.run(
        ["git", "pull", "--rebase", "--autostash"],
        cwd=ROOT, check=True,
    )


def git_commit_and_push(message: str):
    """add → commit → pull（リモートの差分を取り込む） → push をまとめて実行"""
    git_add_all()
    git_commit(message)
    # 他セッションの push がある場合に備えて rebase で取り込む
    subprocess.run(
        ["git", "pull", "--rebase", "--autostash"],
        cwd=ROOT, check=False,   # 失敗しても push を試みる
    )
    git_push()
