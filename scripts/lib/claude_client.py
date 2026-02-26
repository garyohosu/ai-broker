"""
AI クライアント（Codex CLI / Gemini CLI / OpenAI API 優先順位対応）

優先順位:
  1. codex exec  （Codex CLI 定額プラン）
  2. gemini      （Gemini CLI 無料枠）
  3. claude      （Claude CLI 定額プラン）
  4. OpenAI API  （OPENAI_API_KEY 設定時のみ）
  5. フォールバック（ハードコード）
"""
import os
import json
import re
import random
import logging
import subprocess
from pathlib import Path

from .utils import ROOT
from .portfolio import AGENT_NAMES, AGENTS

logger = logging.getLogger("ai-broker")

AGENTS_DIR = ROOT / "agents"

# OpenAI API（コストがかかるため最後の手段）
FAST_MODEL = "gpt-5.2"
QUALITY_MODEL = "gpt-5.2"


# ─── CLI ヘルパー ─────────────────────────────────────────────────────────────

def _call_cli(prompt: str, timeout: int = 180) -> str:
    """ローカル CLI ツールで LLM を呼び出す（定額・無料枠優先）"""
    cli_tools = [
        ["codex", "exec", "-"],   # Codex CLI（定額プラン）
        ["gemini"],               # Gemini CLI（無料枠）
        ["claude", "--print"],    # Claude CLI（定額プラン）
    ]
    for cmd in cli_tools:
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = result.stdout.strip()
            if result.returncode == 0 and len(out) > 50:
                logger.info(f"[cli] ✓ {cmd[0]}: {len(out)} chars")
                return out
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        except Exception as e:
            logger.debug(f"[cli] {cmd[0]}: {e}")
            continue
    return ""


# ─── OpenAI API フォールバック ─────────────────────────────────────────────

def _get_openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import openai
        openai.api_key = api_key
        return openai
    except ImportError:
        return None


def _call_openai(client, model: str, system: str, user: str, max_tokens: int) -> str:
    try:
        response = client.Completion.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"OpenAI API エラー: {e}")
        return ""


def _call(system: str, user: str, max_tokens: int = 300) -> str:
    """CLI → OpenAI API → 空文字 の順で試みる"""
    prompt = f"{system}\n\n{user}"
    # 1. CLI ツール
    result = _call_cli(prompt)
    if result:
        return result
    # 2. OpenAI API（コスト発生）
    client = _get_openai_client()
    if client:
        return _call_openai(client, FAST_MODEL, system, user, max_tokens)
    return ""


# ─── エージェント設定 ─────────────────────────────────────────────────────

def _load_agent_desc(agent: str) -> str:
    path = AGENTS_DIR / f"{agent}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"Agent: {AGENT_NAMES.get(agent, agent)}"


# ─── 日次コメント ─────────────────────────────────────────────────────────────

def get_daily_comment(agent: str, market_context: str) -> str:
    """エージェントの日次一言コメントを生成する"""
    name = AGENT_NAMES.get(agent, agent)
    desc = _load_agent_desc(agent)

    system = (
        f"あなたは仮想の株式投資AIエージェント「{name}」です。\n"
        f"{desc}\n\n"
        "一人称で話してください。"
    )
    user = (
        f"今日の市場状況:\n{market_context}\n\n"
        "自分の戦略目線で今日の一言コメントを50字以内で述べてください。"
    )

    text = _call(system, user, 150)
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

from typing import List, Dict

def get_weekly_discussion(
    market_context: str,
    equity_context: str,
    universe: List[str],
) -> List[Dict]:
    """全エージェントの週次討論チャットログを生成する"""
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

        text = _call(system, user, 250)
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
    mirai_text = _call(mirai_system, mirai_user, 250)
    chat.append({
        "agent":   "mirai",
        "name":    AGENT_NAMES["mirai"],
        "message": mirai_text or _fallback_comment("mirai"),
    })

    return chat


def _fallback_discussion() -> List[Dict]:
    return [
        {"agent": a, "name": AGENT_NAMES[a], "message": _fallback_comment(a)}
        for a in AGENTS
    ]


# ─── 取引計画生成 ─────────────────────────────────────────────────────────────

def get_trade_plan(
    agent: str,
    market_context: str,
    equity_context: str,
    universe: List[str],
) -> Dict[str, float]:
    """エージェントの来週の配分計画（allocation dict）を生成する"""
    if agent == "omakaseko":
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
        '{\"allocation\": {\"ティッカー\": 比率, ...}}\n'
        "比率の合計は 1.0 にしてください。東証銘柄（.T で終わるもの）のみ使用してください。"
    )
    user = (
        f"ユニバース（選択可能銘柄）: {universe_str}\n\n"
        f"今週の市場:\n{market_context}\n\n"
        f"今週の成績:\n{equity_context}\n\n"
        "来週の配分を JSON で回答してください。"
    )

    text = _call(system, user, 400)
    allocation = _parse_allocation(text, universe)

    if not allocation:
        allocation = _random_allocation(universe)

    return allocation


def _parse_allocation(text: str, valid_tickers: List[str]) -> Dict[str, float]:
    """LLM のテキストから allocation dict を抽出・正規化する"""
    try:
        m = re.search(r'\{[^{}]*"allocation"\s*:\s*\{.*?\}[^{}]*\}', text, re.DOTALL)
        if not m:
            m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return {}

        parsed = json.loads(m.group())
        raw = parsed.get("allocation", parsed)

        filtered = {
            k: float(v)
            for k, v in raw.items()
            if k in valid_tickers and float(v) > 0
        }
        if not filtered:
            return {}

        total = sum(filtered.values())
        return {k: round(v / total, 4) for k, v in filtered.items()}

    except Exception as e:
        logger.warning(f"allocation パース失敗: {e} / text={text[:200]}")
        return {}


def _random_allocation(universe: List[str], n: int = 4) -> Dict[str, float]:
    """ランダムに n 銘柄を選んで均等配分する"""
    picks = random.sample(universe, min(n, len(universe)))
    ratio = round(1.0 / len(picks), 4)
    alloc = {t: ratio for t in picks}
    alloc[picks[-1]] = round(1.0 - ratio * (len(picks) - 1), 4)
    return alloc
