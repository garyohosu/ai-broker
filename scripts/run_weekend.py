#!/usr/bin/env python3
"""
週末ジョブ: 週次討論 → 注文計画生成（土曜） / 週次記事確定（日曜） → commit & push

実行: python scripts/run_weekend.py [--date YYYY-MM-DD] [--dry-run]
"""
import sys
import argparse
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib.utils import (
    setup_logging, get_today, get_prev_business_day,
    get_day_of_week, get_week_number, get_last_saturday,
    acquire_lock, release_lock, write_state,
    git_commit_and_push, git_pull, load_json, ROOT,
)
from lib.market import load_prices, load_news
from lib.portfolio import (
    AGENTS, AGENT_NAMES,
    load_equity, compute_weekly_pnl,
    save_plans, load_plans, merge_plans_with_weights,
)
from lib.claude_client import get_weekly_discussion, get_trade_plan
from lib.render import render_weekly_post, save_weekly_post

logger = setup_logging()

CHAT_DIR = ROOT / "data" / "news"   # 討論ログは data/news/ に保存


# ─── Saturday: 討論 → 注文計画 ───────────────────────────────────────────────

def run_saturday(date_str: str, dry_run: bool):
    logger.info(f"土曜ジョブ開始: {date_str}")
    from lib.market import get_universe

    # 直前営業日の価格・資産データ
    prev_biz    = get_prev_business_day(date_str)
    price_data  = load_prices(prev_biz)
    equity_data = load_equity(prev_biz)

    if not price_data:
        logger.warning(f"価格データなし: {prev_biz}（続行します）")
        price_data = {}
    if not equity_data:
        logger.warning(f"資産データなし: {prev_biz}（続行します）")
        equity_data = {}

    # 週初（前月曜）の資産を取得して週次損益を計算
    dt      = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    monday  = (dt - datetime.timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
    mon_eq  = load_equity(monday) or equity_data
    pnl     = compute_weekly_pnl(equity_data, mon_eq)

    # コンテキスト文字列
    indices     = price_data.get("indices", {})
    market_ctx  = _build_market_context(prev_biz, indices, equity_data)
    equity_ctx  = _build_equity_context(pnl)
    universe    = get_universe()

    # ─── 週次討論生成 ──────────────────────────────────────────────────────
    logger.info("週次討論生成中...")
    chat_log = get_weekly_discussion(market_ctx, equity_ctx, universe)

    # 討論ログを保存（週次記事生成時に再利用）
    chat_path = ROOT / "data" / "trades" / date_str / "chat.json"
    from lib.utils import save_json
    save_json(chat_path, {"date": date_str, "chat": chat_log})
    logger.info(f"討論ログ保存: {chat_path}")

    # ─── 各エージェントの注文計画生成 ──────────────────────────────────────
    logger.info("注文計画生成中...")
    plans: dict[str, dict] = {}
    for agent in AGENTS:
        if agent == "mirai":
            continue  # mirai は後で重み統合
        alloc = get_trade_plan(agent, market_ctx, equity_ctx, universe)
        plans[agent] = alloc
        logger.info(f"  {agent}: {alloc}")

    # 進化未来：重み付け統合
    weights = load_json(ROOT / "agents" / "weights.json").get("weights", {})
    mirai_alloc  = merge_plans_with_weights(plans, weights)
    plans["mirai"] = mirai_alloc
    logger.info(f"  mirai (統合): {mirai_alloc}")

    save_plans(date_str, plans)

    # ─── commit & push ────────────────────────────────────────────────────
    if not dry_run:
        git_commit_and_push(f"weekend-sat: {date_str} — 週次討論・注文計画")

    write_state("success", date_str=date_str, job_type="weekend-sat")
    logger.info(f"土曜ジョブ完了: {date_str}")


# ─── Sunday: 週次記事確定 ──────────────────────────────────────────────────────

def run_sunday(date_str: str, dry_run: bool):
    logger.info(f"日曜ジョブ開始: {date_str}")

    sat_str = get_last_saturday(date_str)
    week_str = get_week_number(sat_str)

    # 土曜の討論ログと計画を読み込む
    chat_data = load_json(ROOT / "data" / "trades" / sat_str / "chat.json")
    chat_log  = chat_data.get("chat", [])
    plans_raw = load_plans(sat_str)
    plans     = plans_raw.get("plans", {})

    if not chat_log:
        logger.warning(f"討論ログなし: {sat_str}（空で続行）")

    # 週次損益
    prev_biz    = get_prev_business_day(sat_str)
    equity_data = load_equity(prev_biz) or {}
    dt          = datetime.datetime.strptime(sat_str, "%Y-%m-%d")
    monday      = (dt - datetime.timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
    mon_eq      = load_equity(monday) or equity_data
    pnl         = compute_weekly_pnl(equity_data, mon_eq)

    # ─── 週次記事生成 ──────────────────────────────────────────────────────
    logger.info("週次記事生成中...")
    html = render_weekly_post(week_str, sat_str, chat_log, plans, pnl)
    save_weekly_post(week_str, html)

    # ─── commit & push ────────────────────────────────────────────────────
    if not dry_run:
        git_commit_and_push(f"weekend-sun: {week_str} — 週次記事確定")

    write_state("success", date_str=date_str, job_type="weekend-sun")
    logger.info(f"日曜ジョブ完了: {date_str}")


# ─── コンテキスト文字列ヘルパー ───────────────────────────────────────────────

def _build_market_context(date_str: str, indices: dict, equity_data: dict) -> str:
    lines = [f"集計日: {date_str}"]
    n225  = indices.get("N225",  {})
    topix = indices.get("TOPIX", {})
    if n225:
        sign = "+" if n225.get("change", 0) >= 0 else ""
        lines.append(f"日経平均: {n225.get('close', 0):,.2f} ({sign}{n225.get('change_pct', 0):.2f}%)")
    if topix:
        sign = "+" if topix.get("change", 0) >= 0 else ""
        lines.append(f"TOPIX ETF: {topix.get('close', 0):,.2f} ({sign}{topix.get('change_pct', 0):.2f}%)")
    return "\n".join(lines)


def _build_equity_context(pnl: dict) -> str:
    lines = []
    for agent, d in pnl.items():
        name = d.get("name", AGENT_NAMES.get(agent, agent))
        sign = "+" if d.get("pnl", 0) >= 0 else ""
        lines.append(
            f"{name}: ¥{int(d.get('total', 0)):,} ({sign}{int(d.get('pnl', 0)):,}円 / {sign}{d.get('pnl_pct', 0):.2f}%)"
        )
    return "\n".join(lines)


def get_universe():
    from lib.market import get_universe as _gu
    return _gu()


# ─── メイン ───────────────────────────────────────────────────────────────────

def run(date_str: str, dry_run: bool = False):
    logger.info(f"=== run_weekend 開始: {date_str} (dry_run={dry_run}) ===")

    dow = get_day_of_week(date_str)
    if dow not in (5, 6):
        logger.warning(f"{date_str} は週末ではありません（曜日={dow}）。スキップします。")
        return

    job_type = "weekend-sat" if dow == 5 else "weekend-sun"

    if not acquire_lock(date_str, job_type):
        logger.warning(f"{date_str} の {job_type} ジョブはすでに実行済みです。")
        return

    try:
        write_state("running", date_str=date_str, job_type=job_type)

        if not dry_run:
            try:
                git_pull()
            except Exception as e:
                logger.warning(f"git pull 失敗（継続）: {e}")

        if dow == 5:
            run_saturday(date_str, dry_run)
        else:
            run_sunday(date_str, dry_run)

    except Exception as e:
        logger.exception(f"run_weekend エラー: {e}")
        write_state("error", error=str(e), date_str=date_str, job_type=job_type)
        raise
    finally:
        release_lock(date_str, job_type)

    logger.info(f"=== run_weekend 完了: {date_str} ===")


def main():
    parser = argparse.ArgumentParser(description="ai-broker 週末ジョブ")
    parser.add_argument("--date",    default=None, help="実行日 YYYY-MM-DD（省略時は今日）")
    parser.add_argument("--dry-run", action="store_true", help="git commit/push をスキップ")
    args = parser.parse_args()

    date_str = args.date or get_today()
    run(date_str, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
