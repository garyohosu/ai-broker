"""
市場データ取得・正規化モジュール
yfinance を使って東証銘柄・指数・金利データを取得する
"""
import logging
import datetime
from pathlib import Path

import yfinance as yf
import pandas as pd

from .utils import ROOT, load_json, save_json, get_today

logger = logging.getLogger("ai-broker")

UNIVERSE_FILE = ROOT / "data" / "universe" / "tickers.json"
PRICES_DIR    = ROOT / "data" / "prices"
MACRO_DIR     = ROOT / "data" / "macro"
NEWS_DIR      = ROOT / "data" / "news"

# yfinance 上の指数シンボル
INDEX_SYMBOLS = {
    "N225":    "^N225",   # 日経平均
    "TOPIX":   "1306.T",  # TOPIX 連動 ETF（代用）
}


# ─── ユニバース ────────────────────────────────────────────────────────────────

from typing import List, Dict

def get_universe() -> List[str]:
    data = load_json(UNIVERSE_FILE)
    return data.get("tickers", [])


def get_ticker_labels() -> Dict[str, str]:
    data = load_json(UNIVERSE_FILE)
    return data.get("labels", {})


# ─── 価格取得 ─────────────────────────────────────────────────────────────────

def _history(ticker: str, start: str, end: str) -> pd.DataFrame:
    """yfinance.Ticker.history で安全にデータ取得"""
    try:
        t = yf.Ticker(ticker)
        df = t.history(start=start, end=end, auto_adjust=True)
        return df
    except Exception as e:
        logger.warning(f"yfinance error for {ticker}: {e}")
        return pd.DataFrame()


def _latest_row_before(df: pd.DataFrame, date_str: str):
    """date_str 以前の最新行を返す。なければ None"""
    if df.empty:
        return None
    mask = df.index.strftime("%Y-%m-%d") <= date_str
    sub = df[mask]
    if sub.empty:
        return None
    return sub.iloc[-1]


def fetch_prices(date_str: str) -> Dict[str, Dict]:
    """ユニバース全銘柄の終値などを取得して返す"""
    tickers = get_universe()
    if not tickers:
        logger.warning("ユニバースが空です")
        return {}

    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    start = (dt - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    end   = (dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    result: dict[str, dict] = {}
    for ticker in tickers:
        df = _history(ticker, start, end)
        row = _latest_row_before(df, date_str)
        if row is None:
            logger.warning(f"価格データなし: {ticker}")
            continue
        result[ticker] = {
            "close":  round(float(row["Close"]),  2),
            "open":   round(float(row["Open"]),   2),
            "high":   round(float(row["High"]),   2),
            "low":    round(float(row["Low"]),    2),
            "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
        }

    logger.info(f"{len(result)}/{len(tickers)} 銘柄の価格取得完了")
    return result


def fetch_indices(date_str: str) -> Dict[str, Dict]:
    """指数データを取得して返す"""
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    start = (dt - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    end   = (dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    result: dict[str, dict] = {}
    for name, symbol in INDEX_SYMBOLS.items():
        df = _history(symbol, start, end)
        row = _latest_row_before(df, date_str)
        if row is None:
            logger.warning(f"指数データなし: {name}")
            continue

        close = float(row["Close"])

        # 前日終値を取得
        mask_prev = df.index.strftime("%Y-%m-%d") < row.name.strftime("%Y-%m-%d")
        prev_df = df[mask_prev]
        prev_close = float(prev_df.iloc[-1]["Close"]) if not prev_df.empty else close

        change     = close - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0

        result[name] = {
            "close":      round(close,      2),
            "prev_close": round(prev_close, 2),
            "change":     round(change,     2),
            "change_pct": round(change_pct, 2),
        }

    return result


def fetch_open_prices(date_str: str, tickers: List[str]) -> Dict[str, float]:
    """指定日の始値を返す（月曜約定用）"""
    if not tickers:
        return {}

    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    start = date_str
    end   = (dt + datetime.timedelta(days=5)).strftime("%Y-%m-%d")

    result: dict[str, float] = {}
    for ticker in tickers:
        df = _history(ticker, start, end)
        if df.empty:
            logger.warning(f"始値データなし: {ticker}")
            continue
        # 指定日以降の最初の取引日の始値
        mask = df.index.strftime("%Y-%m-%d") >= date_str
        sub = df[mask]
        if not sub.empty:
            result[ticker] = round(float(sub.iloc[0]["Open"]), 2)

    return result


# ─── データ保存 ───────────────────────────────────────────────────────────────

def save_prices(date_str: str, prices: dict, indices: dict):
    """data/prices/YYYY-MM-DD.json に保存"""
    path = PRICES_DIR / f"{date_str}.json"
    data = {
        "date":    date_str,
        "prices":  prices,
        "indices": indices,
        "meta": {
            "source":     "Yahoo Finance (yfinance)",
            "fetched_at": datetime.datetime.now().isoformat(),
        },
    }
    save_json(path, data)

    # meta.json を更新
    save_json(PRICES_DIR / "meta.json", {
        "last_updated":   date_str,
        "source":         "Yahoo Finance (yfinance)",
        "tickers_count":  len(prices),
    })
    logger.info(f"価格データ保存: {path}")


def load_prices(date_str: str) -> dict:
    """data/prices/YYYY-MM-DD.json を読み込む"""
    return load_json(PRICES_DIR / f"{date_str}.json")


def save_macro(date_str: str, indices: dict):
    """data/macro/YYYY-MM-DD.json に保存"""
    path = MACRO_DIR / f"{date_str}.json"
    save_json(path, {
        "date":       date_str,
        "indices":    indices,
        "fetched_at": datetime.datetime.now().isoformat(),
    })


# ─── ニュース ─────────────────────────────────────────────────────────────────

def _parse_yf_news_item(item: dict, fallback_ticker: str) -> Dict:
    """yfinance ニュースアイテムを正規化する（新旧API両対応）"""
    # yfinance 0.2.x 以降: item = {"id": ..., "content": {...}}
    content = item.get("content")
    if content:
        title     = content.get("title", "").strip()
        pub_str   = content.get("pubDate") or content.get("displayTime", "")
        publisher = (content.get("provider") or {}).get("displayName", "")
        link      = (content.get("clickThroughUrl") or {}).get("url", "")
        try:
            pub_dt = datetime.datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            pub_ts = pub_dt.timestamp()
            pub_at = pub_dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pub_ts = 0
            pub_at = ""
        return {"title": title, "publisher": publisher, "link": link,
                "published_at": pub_at, "pub_ts": pub_ts,
                "related_tickers": [fallback_ticker]}
    # 旧API: item = {"title": ..., "providerPublishTime": ..., ...}
    title   = item.get("title", "").strip()
    pub_ts  = float(item.get("providerPublishTime", 0))
    pub_at  = datetime.datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M") if pub_ts else ""
    return {"title": title, "publisher": item.get("publisher", ""),
            "link": item.get("link", ""), "published_at": pub_at, "pub_ts": pub_ts,
            "related_tickers": item.get("relatedTickers", [fallback_ticker])}


def fetch_news(date_str: str) -> List[Dict]:
    """ユニバース銘柄のニュースを yfinance で取得して返す（重複排除済み）"""
    tickers = get_universe()
    dt      = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    cutoff  = (dt - datetime.timedelta(days=2)).timestamp()   # 直近2日

    seen_titles: set = set()
    all_news:    List[Dict] = []

    for ticker in tickers:
        try:
            news = yf.Ticker(ticker).news or []
            for raw in news:
                parsed = _parse_yf_news_item(raw, ticker)
                title  = parsed["title"]
                if not title or title in seen_titles:
                    continue
                if parsed["pub_ts"] < cutoff:
                    continue
                seen_titles.add(title)
                all_news.append(parsed)
        except Exception as e:
            logger.debug(f"ニュース取得エラー {ticker}: {e}")

    logger.info(f"ニュース取得: {len(all_news)} 件")
    return all_news


def save_news(date_str: str, analyzed_items: List[Dict]):
    """AI分析済みニュースを data/news/YYYY-MM-DD.md に保存"""
    path = NEWS_DIR / f"{date_str}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# ニュース {date_str}\n"]
    if analyzed_items:
        for item in analyzed_items:
            title     = item.get("title", "")
            publisher = item.get("publisher", "")
            link      = item.get("link", "")
            impact    = item.get("impact", "")
            src       = f"（{publisher}）" if publisher else ""
            link_part = f" [{link}]" if link else ""
            lines.append(f"- {title}{src}{link_part}")
            if impact:
                lines.append(f"  - 株価影響: {impact}")
    else:
        lines.append("_（本日の重要材料は収集できませんでした）_")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"ニュース保存: {path} ({len(analyzed_items)} 件)")


def create_news_placeholder(date_str: str):
    """ニュースファイルが存在しない場合にプレースホルダを作成"""
    path = NEWS_DIR / f"{date_str}.md"
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# ニュース {date_str}\n\n_（本日の重要材料は自動収集されませんでした）_\n",
        encoding="utf-8",
    )
    logger.info(f"ニュースプレースホルダ作成: {path}")


def load_news(date_str: str) -> str:
    """data/news/YYYY-MM-DD.md を読み込む"""
    path = NEWS_DIR / f"{date_str}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"# ニュース {date_str}\n\n_（情報なし）_\n"


def parse_news_items(news_md: str) -> List[Dict]:
    """Markdown からニュース行を抽出する（最大3件）"""
    items = []
    for line in news_md.splitlines():
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            items.append({"text": line[2:].strip()})
        if len(items) >= 3:
            break
    return items
