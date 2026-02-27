#!/usr/bin/env python3
"""
平日ジョブ: 価格収集 → 約定処理（月曜のみ） → 資産評価 → 日次記事生成 → commit & push

実行: python scripts/run_daily.py [--date YYYY-MM-DD] [--dry-run]
"""
import sys
import hashlib
import argparse
import datetime
from pathlib import Path

# パスを通す
sys.path.insert(0, str(Path(__file__).parent))

from lib.utils import (
    setup_logging, get_today, get_prev_business_day,
    is_weekday, is_monday, acquire_lock, release_lock,
    write_state, git_commit_and_push, git_pull,
)
from lib.market import (
    fetch_prices, fetch_indices, fetch_open_prices,
    save_prices, save_macro, fetch_news, save_news, create_news_placeholder, load_news,
)
from lib.portfolio import (
    AGENTS, AGENT_NAMES, compute_all_equity, load_equity,
    find_latest_plans, calculate_fills, apply_fills_to_portfolio,
    save_fills,
)
from lib.claude_client import get_all_daily_comments, analyze_news_impact, get_daily_column
from lib.render import render_daily_post, save_daily_post

logger = setup_logging()


def build_market_context(date_str: str, price_data: dict, prev_equity: dict) -> str:
    """Claude に渡す市場コンテキスト文字列を構築する"""
    indices = price_data.get("indices", {})
    lines   = [f"日付: {date_str}"]

    n225  = indices.get("N225",  {})
    topix = indices.get("TOPIX", {})
    if n225:
        sign = "+" if n225.get("change", 0) >= 0 else ""
        lines.append(f"日経平均: {n225.get('close', 0):,.2f} ({sign}{n225.get('change_pct', 0):.2f}%)")
    if topix:
        sign = "+" if topix.get("change", 0) >= 0 else ""
        lines.append(f"TOPIX ETF: {topix.get('close', 0):,.2f} ({sign}{topix.get('change_pct', 0):.2f}%)")

    return "\n".join(lines)


def run(date_str: str, dry_run: bool = False):
    logger.info(f"=== run_daily 開始: {date_str} (dry_run={dry_run}) ===")

    if not is_weekday(date_str):
        logger.warning(f"{date_str} は平日ではありません。スキップします。")
        return

    # ─── ロック取得 ────────────────────────────────────────────────
    if not acquire_lock(date_str, "daily"):
        logger.warning(f"{date_str} の daily ジョブはすでに実行済みです。")
        return

    try:
        write_state("running", date_str=date_str, job_type="daily")

        # ─── git pull ──────────────────────────────────────────────
        if not dry_run:
            try:
                git_pull()
            except Exception as e:
                logger.warning(f"git pull 失敗（継続）: {e}")

        # ─── 価格取得 ──────────────────────────────────────────────
        logger.info("価格データ取得中...")
        prices  = fetch_prices(date_str)
        indices = fetch_indices(date_str)
        save_prices(date_str, prices, indices)
        save_macro(date_str, indices)

        # ─── ニュース取得・AI分析 ──────────────────────────────────
        logger.info("ニュース取得中...")
        raw_news = fetch_news(date_str)
        if raw_news:
            market_ctx_for_news = build_market_context(date_str, {"prices": prices, "indices": indices}, {})
            logger.info("ニュースのAI分析中...")
            analyzed_news = analyze_news_impact(raw_news, market_ctx_for_news)
            save_news(date_str, analyzed_news)
        else:
            create_news_placeholder(date_str)
        news_md = load_news(date_str)

        # ─── 月曜：約定処理 ───────────────────────────────────────
        if is_monday(date_str):
            logger.info("月曜日：前週末の注文計画を約定処理します")
            plan_date, plans = find_latest_plans(date_str)

            if plans:
                logger.info(f"計画を発見: {plan_date}")
                all_tickers = list({t for p in plans.values() for t in p})
                open_prices = fetch_open_prices(date_str, all_tickers)

                all_fills: dict = {}
                for agent in AGENTS:
                    alloc = plans.get(agent, {})
                    if not alloc:
                        continue

                    # 総資産は直前の営業日の資産評価額から取得
                    prev_biz = get_prev_business_day(date_str)
                    prev_eq  = load_equity(prev_biz)
                    total    = (
                        prev_eq.get("agents", {}).get(agent, {}).get("total")
                        or 1_000_000
                    )

                    fills = calculate_fills(alloc, float(total), open_prices)
                    if fills:
                        apply_fills_to_portfolio(agent, fills, date_str)
                        all_fills[agent] = fills
                        logger.info(f"  {agent}: {len(fills)} 銘柄約定")

                if all_fills:
                    save_fills(plan_date, all_fills)
            else:
                logger.info("有効な注文計画が見つかりません")

        # ─── 資産評価 ──────────────────────────────────────────────
        prev_biz    = get_prev_business_day(date_str)
        price_data  = {"prices": prices, "indices": indices}
        equity_data = compute_all_equity(date_str, price_data, prev_biz)

        # ─── エージェントコメント生成（全員を1回のLLMで生成）─────
        logger.info("エージェントコメント生成中...")
        prev_equity    = load_equity(prev_biz)
        market_ctx     = build_market_context(date_str, price_data, prev_equity)
        agent_comments = get_all_daily_comments(market_ctx)
        for agent, comment in agent_comments.items():
            logger.info(f"  {agent}: {comment[:40]}...")

        # ─── 今日のコラム担当を選出・生成 ────────────────────────
        columnist_idx   = int(hashlib.md5(date_str.encode()).hexdigest(), 16) % len(AGENTS)
        columnist_agent = AGENTS[columnist_idx]
        logger.info(f"今日のコラム担当: {AGENT_NAMES.get(columnist_agent, columnist_agent)}")
        news_lines = [l[2:].strip() for l in news_md.splitlines() if l.startswith("- ")]
        column = get_daily_column(columnist_agent, market_ctx, news_lines, equity_data)

        # ─── 日次記事生成 ─────────────────────────────────────────
        logger.info("日次記事生成中...")
        html = render_daily_post(date_str, price_data, equity_data, news_md, agent_comments, column)
        save_daily_post(date_str, html)

        # ─── commit & push ────────────────────────────────────────
        if not dry_run:
            logger.info("git commit & push...")
            git_commit_and_push(f"daily: {date_str} — 価格収集・資産評価・記事更新")

        write_state("success", date_str=date_str, job_type="daily")
        logger.info(f"=== run_daily 完了: {date_str} ===")

    except Exception as e:
        logger.exception(f"run_daily エラー: {e}")
        write_state("error", error=str(e), date_str=date_str, job_type="daily")
        raise
    finally:
        release_lock(date_str, "daily")


def main():
    parser = argparse.ArgumentParser(description="ai-broker 平日ジョブ")
    parser.add_argument("--date",    default=None, help="実行日 YYYY-MM-DD（省略時は今日）")
    parser.add_argument("--dry-run", action="store_true", help="git commit/push をスキップ")
    args = parser.parse_args()

    date_str = args.date or get_today()
    run(date_str, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
