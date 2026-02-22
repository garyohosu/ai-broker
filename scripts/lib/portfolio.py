"""
ポートフォリオ評価・リバランス計算モジュール
"""
import logging
from pathlib import Path

from .utils import ROOT, load_json, save_json

logger = logging.getLogger("ai-broker")

PORTFOLIOS_DIR = ROOT / "data" / "portfolios"
EQUITY_DIR     = ROOT / "data" / "equity"
TRADES_DIR     = ROOT / "data" / "trades"

AGENTS        = ["taro", "aiko", "ribao", "jiro", "omakaseko", "mirai"]
AGENT_NAMES   = {
    "taro":      "上昇太郎",
    "aiko":      "速読アイ子",
    "ribao":     "反町リバ男",
    "jiro":      "金利次郎",
    "omakaseko": "運任せ子",
    "mirai":     "進化未来",
}
INITIAL_CASH  = 1_000_000  # 初期資金 100万円


# ─── ポートフォリオ読み書き ───────────────────────────────────────────────────

def load_portfolio(agent: str) -> dict:
    path = PORTFOLIOS_DIR / f"{agent}.json"
    data = load_json(path)
    if not data:
        data = {
            "agent":        agent,
            "name":         AGENT_NAMES.get(agent, agent),
            "cash":         INITIAL_CASH,
            "holdings":     {},
            "last_updated": "",
        }
    return data


def save_portfolio(agent: str, portfolio: dict):
    save_json(PORTFOLIOS_DIR / f"{agent}.json", portfolio)


# ─── ポートフォリオ評価 ───────────────────────────────────────────────────────

def evaluate_portfolio(portfolio: dict, prices: dict) -> dict:
    """現在の価格でポートフォリオを評価する

    prices は {ticker: {close: float}} または {ticker: float} のどちらも受け付ける
    戻り値: {total, holdings_value, cash, items: [{ticker, shares, price, value}]}
    """
    holdings_value = 0.0
    items = []

    for ticker, shares in portfolio.get("holdings", {}).items():
        p = prices.get(ticker, {})
        price = p.get("close", 0.0) if isinstance(p, dict) else float(p or 0)
        value = shares * price
        holdings_value += value
        items.append({
            "ticker": ticker,
            "shares": shares,
            "price":  price,
            "value":  round(value, 0),
        })

    cash  = float(portfolio.get("cash", 0))
    total = holdings_value + cash

    return {
        "total":          round(total,          0),
        "holdings_value": round(holdings_value, 0),
        "cash":           round(cash,           0),
        "items":          items,
    }


# ─── 約定計算 ─────────────────────────────────────────────────────────────────

def calculate_fills(allocation: dict, total_assets: float, open_prices: dict) -> dict:
    """アロケーション比率と総資産から実際の購入株数を計算する

    allocation:  {ticker: ratio}  合計 1.0
    total_assets: 総資産（円）
    open_prices: {ticker: 始値}

    戻り値: {ticker: {shares, price, amount}}
    最後の銘柄で端数調整して現金を 0 円にする
    """
    fills: dict[str, dict] = {}
    tickers = [t for t in allocation if open_prices.get(t, 0) > 0]
    if not tickers:
        return fills

    total_spent = 0.0

    for i, ticker in enumerate(tickers):
        price = open_prices[ticker]
        is_last = (i == len(tickers) - 1)

        if is_last:
            remaining = total_assets - total_spent
            shares = max(0, int(remaining / price))
        else:
            target = total_assets * allocation.get(ticker, 0)
            shares = max(0, int(target / price))

        amount = shares * price
        total_spent += amount
        fills[ticker] = {
            "shares": shares,
            "price":  round(price,  2),
            "amount": round(amount, 2),
        }

    return fills


def apply_fills_to_portfolio(agent: str, fills: dict, date_str: str) -> dict:
    """約定結果をポートフォリオに反映する（全額株式、現金 0 円）"""
    portfolio = load_portfolio(agent)
    portfolio["holdings"] = {
        ticker: fill["shares"]
        for ticker, fill in fills.items()
        if fill["shares"] > 0
    }
    portfolio["cash"]         = 0
    portfolio["last_updated"] = date_str
    save_portfolio(agent, portfolio)
    return portfolio


# ─── 資産計算（全エージェント） ───────────────────────────────────────────────

def compute_all_equity(date_str: str, price_data: dict, prev_date_str: str = None) -> dict:
    """全エージェントの資産を評価して data/equity/YYYY-MM-DD.json に保存する"""
    prices = price_data.get("prices", {})

    # 前日資産を読み込む
    prev_totals: dict[str, float] = {}
    if prev_date_str:
        prev = load_json(EQUITY_DIR / f"{prev_date_str}.json")
        for a in AGENTS:
            prev_totals[a] = prev.get("agents", {}).get(a, {}).get("total", float(INITIAL_CASH))
    else:
        prev_totals = {a: float(INITIAL_CASH) for a in AGENTS}

    equity_data: dict = {"date": date_str, "agents": {}}

    for agent in AGENTS:
        portfolio  = load_portfolio(agent)
        eval_res   = evaluate_portfolio(portfolio, prices)
        total      = eval_res["total"] or INITIAL_CASH
        prev_total = prev_totals.get(agent, float(INITIAL_CASH))

        change     = total - prev_total
        change_pct = (change / prev_total * 100) if prev_total else 0.0

        equity_data["agents"][agent] = {
            "name":       AGENT_NAMES.get(agent, agent),
            "total":      total,
            "prev":       round(prev_total, 0),
            "change":     round(change,     0),
            "change_pct": round(change_pct, 2),
            "holdings":   eval_res["items"],
            "cash":       eval_res["cash"],
        }

    save_json(EQUITY_DIR / f"{date_str}.json", equity_data)
    logger.info(f"資産データ保存: {date_str}")
    return equity_data


def load_equity(date_str: str) -> dict:
    return load_json(EQUITY_DIR / f"{date_str}.json")


# ─── 取引計画 ─────────────────────────────────────────────────────────────────

def save_plans(date_str: str, plans: dict):
    """data/trades/YYYY-MM-DD/plans.json に保存"""
    path = TRADES_DIR / date_str / "plans.json"
    save_json(path, {"date": date_str, "plans": plans})
    logger.info(f"注文計画保存: {path}")


def load_plans(date_str: str) -> dict:
    path = TRADES_DIR / date_str / "plans.json"
    return load_json(path)


def save_fills(date_str: str, fills: dict):
    """data/trades/YYYY-MM-DD/fills.json に保存"""
    path = TRADES_DIR / date_str / "fills.json"
    save_json(path, {"date": date_str, "fills": fills})
    logger.info(f"約定結果保存: {path}")


def find_latest_plans(before_date: str) -> tuple[str, dict]:
    """before_date より前の最新の plans.json を探す。(date_str, plans) を返す"""
    if not TRADES_DIR.exists():
        return "", {}

    candidates = sorted(
        [d.name for d in TRADES_DIR.iterdir() if d.is_dir() and d.name < before_date],
        reverse=True,
    )
    for date_dir in candidates:
        plans_file = TRADES_DIR / date_dir / "plans.json"
        if plans_file.exists():
            data = load_json(plans_file)
            if data.get("plans"):
                return date_dir, data["plans"]

    return "", {}


# ─── 進化未来の重み統合 ────────────────────────────────────────────────────────

def merge_plans_with_weights(agent_plans: dict, weights: dict) -> dict:
    """各エージェントの allocation を weights で加重平均してミライの配分を生成"""
    merged: dict[str, float] = {}
    total_weight = 0.0

    for agent, plan in agent_plans.items():
        w = weights.get(agent, 0.0)
        if w <= 0:
            continue
        total_weight += w
        for ticker, ratio in plan.items():
            merged[ticker] = merged.get(ticker, 0.0) + ratio * w

    if total_weight > 0:
        merged = {t: round(v / total_weight, 4) for t, v in merged.items()}

    # 合計を 1.0 に正規化
    s = sum(merged.values())
    if s > 0:
        merged = {t: round(v / s, 4) for t, v in merged.items()}

    return merged


def compute_weekly_pnl(equity_data: dict, prev_monday_equity: dict) -> dict:
    """週次損益を計算して返す"""
    result: dict[str, dict] = {}
    for agent in AGENTS:
        curr  = equity_data.get("agents", {}).get(agent, {}).get("total", INITIAL_CASH)
        prev  = prev_monday_equity.get("agents", {}).get(agent, {}).get("total", INITIAL_CASH)
        pnl   = curr - prev
        pct   = (pnl / prev * 100) if prev else 0.0
        result[agent] = {
            "name":     AGENT_NAMES.get(agent, agent),
            "total":    curr,
            "pnl":      round(pnl, 0),
            "pnl_pct":  round(pct, 2),
        }
    return result
