"""
AI クライアント（Anthropic SDK 優先、Codex CLI / OpenAI API フォールバック）

優先順位:
  1. Anthropic API  （ANTHROPIC_API_KEY 設定時）
  2. Codex CLI      （codex exec）
  3. OpenAI API     （OPENAI_API_KEY 設定時）
  4. フォールバック（ハードコード）

※ Gemini CLI はタイムアウト多発のため、現在は無効化。
"""
import os
import json
import re
import random
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict

from .utils import ROOT
from .portfolio import AGENT_NAMES, AGENTS

logger = logging.getLogger("ai-broker")

AGENTS_DIR = ROOT / "agents"

# モデル設定
ANTHROPIC_MODEL = "claude-opus-4-6"
OPENAI_MODEL    = "gpt-4o"


# ─── Anthropic SDK ────────────────────────────────────────────────────────────

def _get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


def _call_anthropic(client, system: str, user: str, max_tokens: int) -> str:
    try:
        import anthropic as _anthropic
        with client.messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=max(max_tokens, 1024),
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            response = stream.get_final_message()
        text_blocks = [b.text for b in response.content if b.type == "text"]
        result = "\n".join(text_blocks).strip()
        logger.info(f"[anthropic] ✓ {len(result)} chars (tokens: {response.usage.output_tokens})")
        return result
    except Exception as e:
        logger.error(f"Anthropic API エラー: {e}")
        return ""


# ─── CLI フォールバック ───────────────────────────────────────────────────────

def _call_codex_cli(prompt: str, timeout: int = 240) -> str:
    """Codex CLI で LLM を呼び出す（non-interactive: codex exec）"""
    output_file = None
    try:
        with tempfile.NamedTemporaryFile(prefix="codex_out_", suffix=".txt", delete=False) as tf:
            output_file = tf.name

        result = subprocess.run(
            [
                "codex", "exec",
                "--sandbox", "read-only",
                "--output-last-message", output_file,
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            logger.debug(f"[cli] codex exec: returncode={result.returncode}")
            return ""

        if output_file and os.path.exists(output_file):
            out = Path(output_file).read_text(encoding="utf-8").strip()
            if out:
                logger.info(f"[cli] ✓ codex exec: {len(out)} chars")
                return out
            logger.debug("[cli] codex exec: empty output")
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.warning("[cli] codex exec: timeout")
    except Exception as e:
        logger.debug(f"[cli] codex exec: {e}")
    finally:
        if output_file and os.path.exists(output_file):
            try:
                os.remove(output_file)
            except Exception:
                pass
    return ""


def _call_cli(prompt: str, timeout: int = 180) -> str:
    """gemini CLI で LLM を呼び出す（最終フォールバック）"""
    try:
        result = subprocess.run(
            ["gemini", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = result.stdout.strip()
        if result.returncode == 0 and len(out) > 20:
            logger.info(f"[cli] ✓ gemini: {len(out)} chars")
            return out
        logger.debug(f"[cli] gemini: returncode={result.returncode}, len={len(out)}")
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.warning("[cli] gemini: timeout")
    except Exception as e:
        logger.debug(f"[cli] gemini: {e}")
    return ""


# ─── OpenAI API フォールバック ─────────────────────────────────────────────

def _get_openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except ImportError:
        return None


def _call_openai(client, system: str, user: str, max_tokens: int) -> str:
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            max_completion_tokens=max_tokens,
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
    """Anthropic API → Codex CLI → OpenAI API → 空文字 の順で試みる"""
    # 1. Anthropic API（最優先）
    ac = _get_anthropic_client()
    if ac:
        result = _call_anthropic(ac, system, user, max_tokens)
        if result:
            return result

    # 2. Codex CLI
    result = _call_codex_cli(f"{system}\n\n{user}")
    if result:
        return result

    # 3. OpenAI API
    oc = _get_openai_client()
    if oc:
        result = _call_openai(oc, system, user, max_tokens)
        if result:
            return result

    return ""


# ─── エージェント設定 ─────────────────────────────────────────────────────

def _load_agent_desc(agent: str) -> str:
    path = AGENTS_DIR / f"{agent}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"Agent: {AGENT_NAMES.get(agent, agent)}"


# ─── 日次コメント ─────────────────────────────────────────────────────────────

def get_all_daily_comments(market_context: str) -> Dict[str, str]:
    """全エージェントの日次コメントを1回のLLM呼び出しでまとめて生成する"""
    agents_profiles = "\n\n".join(
        f"【{AGENT_NAMES[a]}（{a}）】\n{_load_agent_desc(a)[:300]}"
        for a in AGENTS
    )

    system = (
        "以下の6人の仮想株式投資AIエージェントそれぞれの視点から、"
        "今日の市場状況に対する一言コメント（40〜80字）を生成してください。\n"
        "各自のキャラクターと戦略に忠実に、一人称で話してください。\n\n"
        "必ず以下のJSON形式のみで回答してください（前後に余計なテキスト不要）:\n"
        '{"taro":"コメント","aiko":"コメント","ribao":"コメント",'
        '"jiro":"コメント","omakaseko":"コメント","mirai":"コメント"}'
    )
    user = (
        f"今日の市場状況:\n{market_context}\n\n"
        f"各エージェントのキャラクター:\n{agents_profiles}\n\n"
        "全員分のコメントをJSONで回答してください。"
    )

    text = _call(system, user, 800)
    result: Dict[str, str] = {}
    try:
        m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            for agent in AGENTS:
                comment = str(parsed.get(agent, "")).strip()
                if comment:
                    result[agent] = comment
    except Exception as e:
        logger.warning(f"一括コメントパース失敗: {e} / text={text[:200]}")

    # 取得できなかったエージェントはフォールバック
    for agent in AGENTS:
        if agent not in result:
            logger.debug(f"フォールバック: {agent}")
            result[agent] = _fallback_comment(agent)

    logger.info(f"コメント生成: {sum(1 for a in AGENTS if result.get(a) != _fallback_comment(a))}/{len(AGENTS)} 人がLLM生成")
    return result


def get_daily_comment(agent: str, market_context: str) -> str:
    """エージェントの日次一言コメントを生成する（後方互換用）"""
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


def get_daily_column(
    agent: str,
    market_context: str,
    news_items: List[str],
    equity_data: dict,
) -> Dict:
    """指定エージェントが今日の読み物コラムを執筆する"""
    name = AGENT_NAMES.get(agent, agent)
    desc = _load_agent_desc(agent)

    # 順位情報
    agents_sorted = sorted(
        AGENTS,
        key=lambda a: equity_data.get("agents", {}).get(a, {}).get("total", 0),
        reverse=True,
    )
    ranking_str = "　".join(
        f"{i+1}位:{AGENT_NAMES.get(a, a)}"
        for i, a in enumerate(agents_sorted)
    )
    my_eq     = equity_data.get("agents", {}).get(agent, {})
    my_total  = my_eq.get("total",      1_000_000)
    my_change = my_eq.get("change",     0)
    my_pct    = my_eq.get("change_pct", 0)
    my_rank   = (agents_sorted.index(agent) + 1) if agent in agents_sorted else "?"
    sign      = "+" if my_change >= 0 else ""

    news_str = "\n".join(f"- {n}" for n in news_items[:3]) or "（本日のニュースなし）"

    system = (
        f"あなたは仮想の株式投資AIエージェント「{name}」です。\n"
        f"{desc}\n\n"
        "今日の市場について、ブログのコラムを書いてください。\n"
        "条件:\n"
        "・一人称で話し、自分のキャラクターと投資哲学を全開にすること\n"
        "・今日の具体的な市場データやニュースに必ず言及すること\n"
        "・読者が「明日もまた読みたい」と思うような面白さ・毒気・温かみを入れること\n"
        "・他のエージェントへのライバル意識や自分の順位への一言があるとなお良い\n"
        "・必ず以下のJSON形式のみで回答してください:\n"
        '{"title": "コラムタイトル（25字以内）", "body": "本文（250〜450字）"}'
    )
    user = (
        f"今日の市場:\n{market_context}\n\n"
        f"今日の重要ニュース:\n{news_str}\n\n"
        f"現在の順位: {ranking_str}\n"
        f"自分の今日の成績: {my_rank}位　¥{int(my_total):,}"
        f"（前日比 {sign}{int(my_change):,}円 / {sign}{my_pct:.2f}%）\n\n"
        "今日のコラムをJSONで書いてください。"
    )

    text = _call(system, user, 800)
    result: Dict = {"agent": agent, "columnist": name,
                    "title": f"{name}の今日の一言", "body": ""}
    try:
        m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            if parsed.get("title"):
                result["title"] = parsed["title"]
            if parsed.get("body"):
                result["body"] = parsed["body"]
    except Exception as e:
        logger.warning(f"コラムパース失敗: {e}")

    # JSON抽出に失敗した場合でも、本文が空なら必ずフォールバックを入れる
    if not result.get("body"):
        result["body"] = text[:450] if text else f"{name}が今日の市場を分析中..."

    logger.info(f"コラム生成: {result['title']}")
    return result


def analyze_news_impact(
    news_items: List[Dict],
    market_context: str,
) -> List[Dict]:
    """ニュース一覧からAIが株価影響の大きい上位3件を選んで返す"""
    if not news_items:
        return []

    news_text = "\n".join(
        f"{i+1}. {item['title']}（{item.get('publisher', '')}）"
        f" 関連: {', '.join(item.get('related_tickers', []))}"
        for i, item in enumerate(news_items[:40])
    )

    system = (
        "あなたは東京証券取引所の株式アナリストです。\n"
        "以下のニュースから株価に最も影響を与えそうな重要ニュースを最大3件選び、"
        "各ニュースの影響度を判断してください。\n\n"
        "必ず以下のJSON形式のみで回答してください（前後に余計なテキスト不要）:\n"
        '[{"index": 番号, "impact_type": "買い材料/売り材料/中立", "reason": "理由30字以内"}]'
    )
    user = (
        f"市場状況:\n{market_context}\n\n"
        f"ニュース一覧:\n{news_text}\n\n"
        "最大3件を選んでJSONで回答してください。"
    )

    text = _call(system, user, 500)
    selected: List[Dict] = []
    try:
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if m:
            for entry in json.loads(m.group())[:3]:
                idx = int(entry.get("index", 0)) - 1
                if 0 <= idx < len(news_items):
                    item = dict(news_items[idx])
                    impact_type = entry.get("impact_type", "")
                    reason      = entry.get("reason", "")
                    item["impact"] = f"{impact_type}：{reason}" if reason else impact_type
                    selected.append(item)
    except Exception as e:
        logger.warning(f"ニュース分析パース失敗: {e} / text={text[:200]}")

    # AI選別に失敗した場合、ニュース0件を避けるため先頭3件を中立でフォールバック採用
    if not selected and news_items:
        for item in news_items[:3]:
            fallback = dict(item)
            fallback["impact"] = "中立：AI選別失敗のため暫定採用"
            selected.append(fallback)
        logger.warning("ニュース分析フォールバック: 先頭3件を暫定採用")

    logger.info(f"ニュース分析: {len(selected)} 件を選出")
    return selected


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
