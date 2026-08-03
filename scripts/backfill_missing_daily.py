#!/usr/bin/env python3
"""欠落した過去営業日の日次データと記事を安全に補完する。"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bootstrap import ensure_repo_python

ensure_repo_python()

import pandas as pd
import yfinance as yf

from lib.market import INDEX_SYMBOLS, get_universe, save_macro, save_news, save_prices
from lib.portfolio import AGENTS, AGENT_NAMES, INITIAL_CASH
from lib.render import render_daily_post, save_daily_post
from lib.utils import ROOT, load_json, save_json

MISSING_DATES = ["2026-03-17", "2026-03-18", "2026-03-23", "2026-04-02", "2026-05-26"]


def download(symbols: list[str]) -> pd.DataFrame:
    start = (dt.date.fromisoformat(min(MISSING_DATES)) - dt.timedelta(days=5)).isoformat()
    end = (dt.date.fromisoformat(max(MISSING_DATES)) + dt.timedelta(days=2)).isoformat()
    last_error = None
    for attempt in range(4):
        try:
            frame = yf.download(
                symbols, start=start, end=end, auto_adjust=True, group_by="ticker",
                threads=False, progress=False, timeout=30,
            )
            if not frame.empty:
                return frame
        except Exception as exc:
            last_error = exc
        time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"historical market download failed: {last_error}")


def row_for(frame: pd.DataFrame, symbol: str, date_str: str) -> pd.Series:
    block = frame[symbol] if isinstance(frame.columns, pd.MultiIndex) else frame
    matches = block[block.index.strftime("%Y-%m-%d") == date_str]
    if matches.empty:
        raise RuntimeError(f"no exact trading row: {symbol} {date_str}")
    return matches.iloc[0]


def existing_equity_dates() -> list[str]:
    return sorted(p.stem for p in (ROOT / "data/equity").glob("2026-*.json"))


def snapshot_holdings(date_str: str, agent: str) -> tuple[dict[str, float], float]:
    later = next((d for d in existing_equity_dates() if d > date_str), None)
    if not later:
        raise RuntimeError(f"no later equity snapshot for {date_str}")
    data = load_json(ROOT / "data/equity" / f"{later}.json").get("agents", {}).get(agent, {})
    holdings = {item["ticker"]: item["shares"] for item in data.get("holdings", [])}
    return holdings, float(data.get("cash", 0))


def previous_total(date_str: str, agent: str) -> float:
    prior = [d for d in existing_equity_dates() if d < date_str]
    if not prior:
        return float(INITIAL_CASH)
    data = load_json(ROOT / "data/equity" / f"{prior[-1]}.json")
    return float(data.get("agents", {}).get(agent, {}).get("total", INITIAL_CASH))


def build_equity(date_str: str, prices: dict) -> dict:
    result = {"date": date_str, "agents": {}}
    for agent in AGENTS:
        holdings, cash = snapshot_holdings(date_str, agent)
        items = []
        holdings_value = 0.0
        for ticker, shares in holdings.items():
            price = float(prices.get(ticker, {}).get("close", 0))
            value = shares * price
            holdings_value += value
            items.append({"ticker": ticker, "shares": shares, "price": price, "value": round(value, 0)})
        total = round(holdings_value + cash, 0) or INITIAL_CASH
        prev = previous_total(date_str, agent)
        change = total - prev
        result["agents"][agent] = {
            "name": AGENT_NAMES[agent], "total": total, "prev": round(prev, 0),
            "change": round(change, 0), "change_pct": round(change / prev * 100, 2) if prev else 0,
            "holdings": items, "cash": round(cash, 0),
        }
    save_json(ROOT / "data/equity" / f"{date_str}.json", result)
    return result


def main() -> None:
    universe = get_universe()
    symbols = universe + list(INDEX_SYMBOLS.values())
    frame = download(symbols)
    for date_str in MISSING_DATES:
        prices = {}
        for ticker in universe:
            row = row_for(frame, ticker, date_str)
            prices[ticker] = {
                "close": round(float(row["Close"]), 2), "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2), "low": round(float(row["Low"]), 2),
                "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
            }
        indices = {}
        for name, symbol in INDEX_SYMBOLS.items():
            row = row_for(frame, symbol, date_str)
            block = frame[symbol] if isinstance(frame.columns, pd.MultiIndex) else frame
            prior = block[block.index.strftime("%Y-%m-%d") < date_str].dropna(subset=["Close"])
            prev_close = float(prior.iloc[-1]["Close"])
            close = float(row["Close"])
            indices[name] = {
                "close": round(close, 2), "prev_close": round(prev_close, 2),
                "change": round(close - prev_close, 2),
                "change_pct": round((close - prev_close) / prev_close * 100, 2),
            }
        if len(prices) != len(universe) or len(indices) != len(INDEX_SYMBOLS):
            raise RuntimeError(f"incomplete data for {date_str}")
        save_prices(date_str, prices, indices)
        save_macro(date_str, indices)
        news = [{"title": "過去営業日の欠落を補完しました（当時のニュースは再取得対象外）", "publisher": "ai-broker"}]
        save_news(date_str, news)
        equity = build_equity(date_str, prices)
        comments = {a: "履歴補完データとして、当日の実市場価格で資産評価を再計算しました。" for a in AGENTS}
        column = "このページは運用停止期間の欠落を補うため、Yahoo Financeの当日OHLCデータと既存の保有スナップショットから再構成しました。新たな仮想売買は行っていません。"
        html = render_daily_post(date_str, {"prices": prices, "indices": indices}, equity, "- 過去営業日の履歴補完", comments, column)
        save_daily_post(date_str, html)
        save_json(ROOT / "data/trades" / date_str / "daily_signal_plans.json", {
            "date": date_str, "plans": {}, "note": "履歴補完のため当時の売買シグナルは生成しない",
        })
    save_json(ROOT / "data/prices" / "meta.json", {
        "last_updated": "2026-08-03", "source": "Yahoo Finance (yfinance)", "tickers_count": len(universe)
    })


if __name__ == "__main__":
    main()
