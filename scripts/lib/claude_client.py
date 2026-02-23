"""
OpenAI API クライアント
エージェントのコメント生成・週次討論・取引計画生成
"""
import os
import json
import re
import random
import logging
from pathlib import Path

from openai import OpenAI

from .utils import ROOT
from .portfolio import AGENT_NAMES, AGENTS

logger = logging.getLogger("ai-broker")

AGENTS_DIR = ROOT / "agents"

# 高速・低コストモデル（コメント生成用）
FAST_MODEL = "gpt-5.2"
# 高品質モデル（週次討論用）
QUALITY_MODEL = "gpt-5.2"


def _get_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY が設定されていません")
    return OpenAI(api_key=api_key)


def _load_agent_desc(agent: str) -> str:
    path = AGENTS_DIR / f"{agent}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"Agent: {AGENT_NAMES.get(agent, agent)}"


def _call(client: OpenAI, model: str, system: str, user: str, max_tokens: int) -> str:
    """OpenAI API を呼び出して応答テキストを返す"""
    try:
        res = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI API エラー: {e}")
        return ""


# ─── 日次コメント ─────────────────────────────────────────────────────────────

def get_daily_comment(agent: str, market_context: str) -> str:
    """エージェントの日次一言コメントを生成する"""
    try:
        client = _get_client()
    except EnvironmentError:
        return _fallback_comment(agent)

    name = AGENT_NAMES.get(agent, agent)
    desc = _load_agent_desc(agent)

    system = (
        f"あなたは仮想の株式投資AIエージェント「{name}」です。\n"
        f"{desc}\n\n"
        "一人称（「私は〜」「俺は〜」「私が〜」など自分のキャラに合わせた一人称）で話してください。"
    )
    user = (
        f"今日の市場状況:\n{market_context}\n\n"
        "自分の戦略目線で今日の一言コメントを50字以内で述べてください。"
    )

    text = _call(client, FAST_MODEL, system, user, 150)
    return text or _fallback_comment(agent)


def _fallback_comment(agent: str) -> str:
    fallbacks = {
        "taro":      "今日も上昇トレンドを追い続ける！",
        "aiko":      "適時開示を確認中。材料次第で動く。",
        "ribao":     "売られすぎ銘柄を虎視眈々と狙っている。",
        "jiro":      "金利動向を注視。マクロ環境は慎重に見極める。",
        "omakaseko": "今日もお任せ♪ 運命に身を委ねましょう。",
        "mirai":     "データ収集中。重み調整は月次で実施予定。",
    }
    return fallbacks.get(agent, "状況を分析中...")


# ─── 週次討論 ─────────────────────────────────────────────────────────────────

def get_weekly_discussion(
    market_context: str,
    equity_context: str,
    universe: list[str],
) -> list[dict]:
    """全エージェントの週次討論チャットログを生成する"""
    try:
        client = _get_client()
    except EnvironmentError:
        return _fallback_discussion()

    chat = []
    discussion_agents = ["taro", "aiko", "ribao", "jiro", "omakaseko"]

    for agent in discussion_agents:
        name = AGENT_NAMES.get(agent, agent)
        desc = _load_agent_desc(agent)

        system = (
            f"あなたは仮想の株式投資AIエージェント「{name}」です。\n"
            f"{desc}\n\n"
            "週次ミーティングで自分の戦略と来週の見通しを述べてください。"
            "100〜150字程度の自然な口調で話してください。"
        )
        user = (
            f"今週の市場:\n{market_context}\n\n"
            f"今週の運用成績:\n{equity_context}\n\n"
            "来週の戦略を述べてください。"
        )

        text = _call(client, FAST_MODEL, system, user, 250)
        chat.append({
            "agent":   agent,
            "name":    name,
            "message": text or _fallback_comment(agent),
        })

    # 進化未来のまとめ
    mirai_context = "\n".join(f"【{c['name']}】{c['message']}" for c in chat)
    mirai_system = (
        f"あなたは仮想の株式投資AIエージェント「{AGENT_NAMES['mirai']}」です。\n"
        f"{_load_agent_desc('mirai')}\n\n"
        "他エージェントの発言を踏まえて、重み付け統合の視点からコメントしてください。"
    )
    mirai_user = (
        f"各エージェントの発言:\n{mirai_context}\n\n"
        "データドリブンな視点で来週の展望を100字程度でまとめてください。"
    )
    mirai_text = _call(client, FAST_MODEL, mirai_system, mirai_user, 250)
    chat.append({
        "agent":   "mirai",
        "name":    AGENT_NAMES["mirai"],
        "message": mirai_text or _fallback_comment("mirai"),
    })

    return chat


def _fallback_discussion() -> list[dict]:
    return [
        {"agent": a, "name": AGENT_NAMES[a], "message": _fallback_comment(a)}
        for a in AGENTS
    ]


# ─── 取引計画生成 ─────────────────────────────────────────────────────────────

def get_trade_plan(
    agent: str,
    market_context: str,
    equity_context: str,
    universe: list[str],
) -> dict[str, float]:
    """エージェントの来週の配分計画（allocation dict）を生成する"""
    if agent == "omakaseko":
        return _random_allocation(universe)

    try:
        client = _get_client()
    except EnvironmentError:
        return _random_allocation(universe)

    name = AGENT_NAMES.get(agent, agent)
    desc = _load_agent_desc(agent)
    universe_sample = universe[:20]
    universe_str = ", ".join(universe_sample)

    system = (
        f"あなたは仮想の株式投資AIエージェント「{name}」です。\n"
        f"{desc}\n\n"
        "来週の配分を決めてください。\n"
        "必ず以下のJSON形式のみで回答してください（前後に余計なテキスト不要）:\n"
        '{"allocation": {"ティッカー": 比率, ...}}\n'
        "比率の合計は 1.0 にしてください。東証銘柄（.T で終わるもの）のみ使用してください。"
    )
    user = (
        f"ユニバース（選択可能銘柄）: {universe_str}\n\n"
        f"今週の市場:\n{market_context}\n\n"
        f"今週の成績:\n{equity_context}\n\n"
        "来週の配分を JSON で回答してください。"
    )

    text = _call(client, FAST_MODEL, system, user, 400)
    allocation = _parse_allocation(text, universe)

    if not allocation:
        allocation = _random_allocation(universe)

    return allocation


def _parse_allocation(text: str, valid_tickers: list[str]) -> dict[str, float]:
    """LLM のテキストから allocation dict を抽出・正規化する"""
    try:
        m = re.search(r'\{[^{}]*"allocation"\s*:\s*\{.*?\}[^{}]*\}', text, re.DOTALL)
        if not m:
            m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return {}

        parsed = json.loads(m.group())
        raw = parsed.get("allocation", parsed)

        # 有効な銘柄のみ残す
        filtered = {
            k: float(v)
            for k, v in raw.items()
            if k in valid_tickers and float(v) > 0
        }
        if not filtered:
            return {}

        # 正規化
        total = sum(filtered.values())
        return {k: round(v / total, 4) for k, v in filtered.items()}

    except Exception as e:
        logger.warning(f"allocation パース失敗: {e} / text={text[:200]}")
        return {}


def _random_allocation(universe: list[str], n: int = 4) -> dict[str, float]:
    """ランダムに n 銘柄を選んで均等配分する"""
    picks = random.sample(universe, min(n, len(universe)))
    ratio = round(1.0 / len(picks), 4)
    # 端数調整
    alloc = {t: ratio for t in picks}
    alloc[picks[-1]] = round(1.0 - ratio * (len(picks) - 1), 4)
    return alloc
