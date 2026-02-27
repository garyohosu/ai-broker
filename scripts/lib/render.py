"""
記事（HTML）生成モジュール
日次・週次ポストを生成して docs/posts/ に保存する
"""
from typing import List, Dict, Tuple
import logging
from pathlib import Path
from datetime import datetime

from .utils import ROOT
from .portfolio import AGENT_NAMES, AGENTS, INITIAL_CASH

logger = logging.getLogger("ai-broker")

POSTS_DAILY_DIR  = ROOT / "docs" / "posts" / "daily"
POSTS_WEEKLY_DIR = ROOT / "docs" / "posts" / "weekly"
ASSETS_DIR       = ROOT / "docs" / "assets"

PUB_ID = "ca-pub-6743751614716161"

ADSENSE_TAG = (
    f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
    f'?client={PUB_ID}" crossorigin="anonymous"></script>'
)

# レスポンシブ広告ユニット（記事中・記事末に挿入）
AD_UNIT = f"""
<div class="my-6">
  <ins class="adsbygoogle"
       style="display:block"
       data-ad-client="{PUB_ID}"
       data-ad-format="auto"
       data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</div>"""

AVATAR_URL = "https://api.dicebear.com/9.x/pixel-art/svg?seed={seed}"

AGENT_COLORS = {
    "taro":      "#3b82f6",   # blue
    "aiko":      "#10b981",   # emerald
    "ribao":     "#8b5cf6",   # violet
    "jiro":      "#f59e0b",   # amber
    "omakaseko": "#ec4899",   # pink
    "mirai":     "#14b8a6",   # teal
}

# ─── 共通 HTML ヘルパー ───────────────────────────────────────────────────────

def _head(title: str, extra_css: str = "") -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} | ai-broker</title>
  {ADSENSE_TAG}
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../../assets/css/style.css">
  <link rel="stylesheet" href="../../assets/css/chat.css">
  <style>body{{font-family:'Noto Sans JP',sans-serif;}}{extra_css}</style>
</head>
<body class="bg-gray-50 text-gray-800 min-h-screen">
"""


def _nav(breadcrumb: str = "") -> str:
    return f"""
<nav class="bg-white border-b border-gray-200 shadow-sm sticky top-0 z-10">
  <div class="max-w-4xl mx-auto px-4 py-3 flex items-center gap-2 text-sm">
    <a href="../../" class="font-bold text-blue-600 hover:text-blue-800">🤖 ai-broker</a>
    {f'<span class="text-gray-400">/</span><span class="text-gray-600">{breadcrumb}</span>' if breadcrumb else ''}
  </div>
</nav>
"""


def _footer() -> str:
    return """
<footer class="mt-16 py-8 border-t border-gray-200 text-center text-sm text-gray-400">
  <p>ai-broker — 仮想ペーパートレード実験 | <a href="https://github.com/garyohosu/ai-broker" class="underline hover:text-gray-600" target="_blank">GitHub</a></p>
  <p class="mt-1">売買はすべて仮想です。実際の投資を推奨するものではありません。</p>
</footer>
</body>
</html>
"""


def _fmt_jpy(value: float) -> str:
    return f"¥{int(value):,}"


def _fmt_change(change: float, pct: float) -> str:
    sign  = "+" if change >= 0 else ""
    color = "text-red-600" if change >= 0 else "text-blue-600"
    return f'<span class="{color} font-semibold">{sign}{int(change):,}円 ({sign}{pct:.2f}%)</span>'


def _index_card(name: str, data: dict) -> str:
    c    = data.get("change",     0)
    pct  = data.get("change_pct", 0)
    sign = "+" if c >= 0 else ""
    clr  = "text-red-600" if c >= 0 else "text-blue-600"
    return f"""
    <div class="bg-white rounded-xl shadow-sm p-4 border border-gray-100">
      <div class="text-xs text-gray-500 mb-1">{name}</div>
      <div class="text-2xl font-bold">{data.get('close', 0):,.2f}</div>
      <div class="{clr} text-sm font-semibold">{sign}{c:,.2f} ({sign}{pct:.2f}%)</div>
    </div>"""


def _column_section(column: Dict) -> str:
    agent    = column.get("agent", "")
    name     = column.get("columnist", "")
    title    = column.get("title", "今日のコラム")
    body     = column.get("body", "").replace("\n", "<br>")
    color    = AGENT_COLORS.get(agent, "#6b7280")
    avatar   = AVATAR_URL.format(seed=agent)
    return f"""
  <section class="mb-8">
    <h2 class="text-lg font-bold mb-3 flex items-center gap-2"><span>✍️</span>今日のコラム</h2>
    <div class="bg-white rounded-2xl shadow-md overflow-hidden" style="border:2px solid {color}">
      <div class="flex items-center gap-3 px-5 py-3" style="background:color-mix(in srgb,{color} 12%,white)">
        <img src="{avatar}" alt="{name}" class="w-12 h-12 rounded-full border-2 flex-shrink-0" style="border-color:{color}">
        <div>
          <div class="font-bold" style="color:{color}">{name}</div>
          <div class="text-xs text-gray-400">担当コラムニスト</div>
        </div>
        <span class="ml-auto text-xs font-semibold px-2 py-1 rounded-full text-white" style="background:{color}">今日の担当</span>
      </div>
      <div class="px-6 py-5">
        <h3 class="text-xl font-bold mb-4 leading-snug" style="color:{color}">「{title}」</h3>
        <p class="text-gray-700 leading-relaxed text-sm whitespace-pre-line">{body}</p>
      </div>
    </div>
  </section>"""


def _agent_card(agent: str, eq: dict, comment: str) -> str:
    name    = eq.get("name", AGENT_NAMES.get(agent, agent))
    total   = eq.get("total",      INITIAL_CASH)
    change  = eq.get("change",     0)
    pct     = eq.get("change_pct", 0)
    color   = AGENT_COLORS.get(agent, "#6b7280")
    avatar  = AVATAR_URL.format(seed=agent)
    sign    = "+" if change >= 0 else ""
    chg_clr = "text-red-600" if change >= 0 else "text-blue-600"
    return f"""
  <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex gap-4 items-start">
    <img src="{avatar}" alt="{name}" class="w-14 h-14 rounded-full border-2 flex-shrink-0"
         style="border-color:{color}">
    <div class="flex-1 min-w-0">
      <div class="font-bold text-base" style="color:{color}">{name}</div>
      <div class="text-xl font-bold mt-1">{_fmt_jpy(total)}</div>
      <div class="{chg_clr} text-sm">{sign}{int(change):,}円 ({sign}{pct:.2f}%)</div>
      <div class="mt-3 text-sm text-gray-700 bg-gray-50 rounded-lg px-3 py-2 border-l-4"
           style="border-color:{color}">
        {comment}
      </div>
    </div>
  </div>"""


# ─── 日次記事 ─────────────────────────────────────────────────────────────────

def render_daily_post(
    date_str:      str,
    price_data:    Dict,
    equity_data:   Dict,
    news_md:       str,
    agent_comments: Dict[str, str],
    column:        Dict = None,
) -> str:
    """日次 HTML 記事を生成して返す"""
    indices     = price_data.get("indices", {})
    n225        = indices.get("N225",   {})
    topix       = indices.get("TOPIX",  {})
    news_items  = _parse_news_md(news_md)

    # ニュースセクション
    news_html = ""
    for item in news_items[:3]:
        news_html += f'<li class="py-2 border-b border-gray-100 last:border-0 text-sm">{item}</li>\n'
    if not news_items:
        news_html = '<li class="py-2 text-sm text-gray-400">本日の重要材料なし</li>'

    # エージェントカード
    agents_html = ""
    for agent in AGENTS:
        eq      = equity_data.get("agents", {}).get(agent, {})
        comment = agent_comments.get(agent, "...")
        agents_html += _agent_card(agent, eq, comment)

    # 指数カード
    idx_html = ""
    if n225:
        idx_html += _index_card("日経平均", n225)
    if topix:
        idx_html += _index_card("TOPIX ETF(1306)", topix)

    # ランキング
    sorted_agents = sorted(
        AGENTS,
        key=lambda a: equity_data.get("agents", {}).get(a, {}).get("total", 0),
        reverse=True,
    )
    rank_rows = ""
    for i, agent in enumerate(sorted_agents, 1):
        eq   = equity_data.get("agents", {}).get(agent, {})
        name = eq.get("name", AGENT_NAMES.get(agent, agent))
        tot  = eq.get("total",      INITIAL_CASH)
        chg  = eq.get("change",     0)
        pct  = eq.get("change_pct", 0)
        sign = "+" if chg >= 0 else ""
        clr  = "text-red-600" if chg >= 0 else "text-blue-600"
        medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}位"
        rank_rows += f"""
      <tr class="border-b border-gray-100 hover:bg-gray-50">
        <td class="py-2 px-3 text-center w-12">{medal}</td>
        <td class="py-2 px-3 font-medium">{name}</td>
        <td class="py-2 px-3 text-right font-mono">{_fmt_jpy(tot)}</td>
        <td class="py-2 px-3 text-right {clr} font-mono">{sign}{int(chg):,}</td>
        <td class="py-2 px-3 text-right {clr} font-mono">{sign}{pct:.2f}%</td>
      </tr>"""

    column_html = _column_section(column) if column and column.get("body") else ""

    html = _head(date_str, "") + _nav("日次レポート") + f"""
<main class="max-w-4xl mx-auto px-4 py-8">

  <h1 class="text-2xl font-bold mb-1">📈 {date_str} 日次レポート</h1>
  <p class="text-sm text-gray-500 mb-6">東証引け後の自動更新 | 売買はすべて仮想ペーパートレードです</p>

  <!-- 指数サマリ -->
  <section class="mb-8">
    <h2 class="text-lg font-bold mb-3 flex items-center gap-2"><span>📊</span>市場サマリ</h2>
    <div class="grid grid-cols-2 gap-4 sm:grid-cols-3">
      {idx_html}
    </div>
  </section>

  <!-- 今日のコラム -->
  {column_html}

  {AD_UNIT}

  <!-- 重要材料 -->
  <section class="mb-8">
    <h2 class="text-lg font-bold mb-3 flex items-center gap-2"><span>📰</span>重要材料（最大3件）</h2>
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
      <ul>{news_html}</ul>
    </div>
  </section>

  <!-- 本日ランキング -->
  <section class="mb-8">
    <h2 class="text-lg font-bold mb-3 flex items-center gap-2"><span>🏆</span>本日ランキング</h2>
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-gray-500 text-xs uppercase">
          <tr>
            <th class="py-2 px-3 text-center">順位</th>
            <th class="py-2 px-3 text-left">社員</th>
            <th class="py-2 px-3 text-right">資産</th>
            <th class="py-2 px-3 text-right">前日比(円)</th>
            <th class="py-2 px-3 text-right">前日比(%)</th>
          </tr>
        </thead>
        <tbody>{rank_rows}</tbody>
      </table>
    </div>
  </section>

  <!-- エージェントカード -->
  <section class="mb-8">
    <h2 class="text-lg font-bold mb-3 flex items-center gap-2"><span>🤖</span>各社員の一言</h2>
    <div class="grid gap-4 sm:grid-cols-2">
      {agents_html}
    </div>
  </section>

  {AD_UNIT}

</main>
""" + _footer()

    return html


def save_daily_post(date_str: str, html: str):
    path = POSTS_DAILY_DIR / f"{date_str}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    logger.info(f"日次記事保存: {path}")
    _update_index()


# ─── 週次記事 ─────────────────────────────────────────────────────────────────

def render_weekly_post(
    week_str:    str,
    date_str:    str,
    chat_log:    List[Dict],
    plans:       Dict,
    weekly_pnl:  Dict,
) -> str:
    """週次 HTML 記事を生成して返す"""
    # 週次ランキング
    sorted_agents = sorted(weekly_pnl.keys(), key=lambda a: weekly_pnl[a].get("pnl", 0), reverse=True)
    rank_rows = ""
    for i, agent in enumerate(sorted_agents, 1):
        d    = weekly_pnl[agent]
        name = d.get("name", AGENT_NAMES.get(agent, agent))
        tot  = d.get("total",   INITIAL_CASH)
        pnl  = d.get("pnl",     0)
        pct  = d.get("pnl_pct", 0)
        sign = "+" if pnl >= 0 else ""
        clr  = "text-red-600" if pnl >= 0 else "text-blue-600"
        medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}位"
        rank_rows += f"""
      <tr class="border-b border-gray-100 hover:bg-gray-50">
        <td class="py-2 px-3 text-center w-12">{medal}</td>
        <td class="py-2 px-3 font-medium">{name}</td>
        <td class="py-2 px-3 text-right font-mono">{_fmt_jpy(tot)}</td>
        <td class="py-2 px-3 text-right {clr} font-mono">{sign}{int(pnl):,}</td>
        <td class="py-2 px-3 text-right {clr} font-mono">{sign}{pct:.2f}%</td>
      </tr>"""

    # 討論チャット
    chat_html = ""
    for msg in chat_log:
        agent   = msg.get("agent", "")
        name    = msg.get("name",  AGENT_NAMES.get(agent, agent))
        message = msg.get("message", "")
        color   = AGENT_COLORS.get(agent, "#6b7280")
        avatar  = AVATAR_URL.format(seed=agent)
        chat_html += f"""
    <div class="msg">
      <img class="avatar" src="{avatar}" alt="{name}" style="border-color:{color}">
      <div class="bubble" style="border-left-color:{color}">
        <div class="name" style="color:{color}">{name}</div>
        <div class="text">{message}</div>
      </div>
    </div>"""

    # 来週の配分テーブル
    alloc_rows = ""
    for agent in AGENTS:
        alloc = plans.get(agent, {})
        name  = AGENT_NAMES.get(agent, agent)
        color = AGENT_COLORS.get(agent, "#6b7280")
        if not alloc:
            alloc_rows += f"""
      <tr class="border-b border-gray-100">
        <td class="py-2 px-3 font-medium" style="color:{color}">{name}</td>
        <td class="py-2 px-3 text-gray-400 text-sm italic" colspan="2">（未定）</td>
      </tr>"""
            continue
        top3 = sorted(alloc.items(), key=lambda x: x[1], reverse=True)[:5]
        alloc_str = "　".join(f"{t} {v*100:.0f}%" for t, v in top3)
        alloc_rows += f"""
      <tr class="border-b border-gray-100">
        <td class="py-2 px-3 font-medium" style="color:{color}">{name}</td>
        <td class="py-2 px-3 text-sm font-mono">{alloc_str}</td>
      </tr>"""

    html = _head(f"週次 {week_str}", "") + _nav("週次レポート") + f"""
<main class="max-w-4xl mx-auto px-4 py-8">

  <h1 class="text-2xl font-bold mb-1">📅 {week_str} 週次レポート</h1>
  <p class="text-sm text-gray-500 mb-6">
    週末ミーティング（{date_str}） | 約定は<strong>来週月曜の始値</strong>で実施
  </p>

  <!-- 週次ランキング -->
  <section class="mb-8">
    <h2 class="text-lg font-bold mb-3 flex items-center gap-2"><span>🏆</span>今週の成績</h2>
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-gray-500 text-xs uppercase">
          <tr>
            <th class="py-2 px-3 text-center">順位</th>
            <th class="py-2 px-3 text-left">社員</th>
            <th class="py-2 px-3 text-right">資産</th>
            <th class="py-2 px-3 text-right">週次損益(円)</th>
            <th class="py-2 px-3 text-right">週次損益(%)</th>
          </tr>
        </thead>
        <tbody>{rank_rows}</tbody>
      </table>
    </div>
  </section>

  {AD_UNIT}

  <!-- 討論会 -->
  <section class="mb-8">
    <h2 class="text-lg font-bold mb-3 flex items-center gap-2"><span>💬</span>週末討論会</h2>
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-5 chat-container">
      {chat_html}
    </div>
  </section>

  <!-- 来週の配分 -->
  <section class="mb-8">
    <h2 class="text-lg font-bold mb-3 flex items-center gap-2"><span>📋</span>来週の配分（全額株式）</h2>
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50 text-gray-500 text-xs uppercase">
          <tr>
            <th class="py-2 px-3 text-left">社員</th>
            <th class="py-2 px-3 text-left">銘柄・比率（上位5件）</th>
          </tr>
        </thead>
        <tbody>{alloc_rows}</tbody>
      </table>
    </div>
    <p class="mt-3 text-xs text-gray-400 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2">
      ⚠️ 約定は来週月曜の始値で実施します。全額を株式に投資（現金 0 円）する設定です。
    </p>
  </section>

  {AD_UNIT}

</main>
""" + _footer()

    return html


def save_weekly_post(week_str: str, html: str):
    path = POSTS_WEEKLY_DIR / f"{week_str}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    logger.info(f"週次記事保存: {path}")
    _update_index()


# ─── index.html 更新 ─────────────────────────────────────────────────────────

def _update_index():
    """docs/index.html の記事一覧を更新する"""
    daily_files  = sorted(POSTS_DAILY_DIR.glob("*.html"),  reverse=True)[:10]
    weekly_files = sorted(POSTS_WEEKLY_DIR.glob("*.html"), reverse=True)[:5]

    daily_li  = "\n".join(
        f'<li><a href="./posts/daily/{f.stem}.html" class="text-blue-600 hover:underline">{f.stem}</a></li>'
        for f in daily_files
    ) or "<li class='text-gray-400'>まだ記事がありません</li>"

    weekly_li = "\n".join(
        f'<li><a href="./posts/weekly/{f.stem}.html" class="text-blue-600 hover:underline">{f.stem}</a></li>'
        for f in weekly_files
    ) or "<li class='text-gray-400'>まだ記事がありません</li>"

    index_path = ROOT / "docs" / "index.html"
    if index_path.exists():
        content = index_path.read_text(encoding="utf-8")
        # 記事一覧プレースホルダを更新
        import re
        content = re.sub(
            r'<!-- DAILY_LIST_START -->.*?<!-- DAILY_LIST_END -->',
            f'<!-- DAILY_LIST_START -->\n{daily_li}\n<!-- DAILY_LIST_END -->',
            content, flags=re.DOTALL,
        )
        content = re.sub(
            r'<!-- WEEKLY_LIST_START -->.*?<!-- WEEKLY_LIST_END -->',
            f'<!-- WEEKLY_LIST_START -->\n{weekly_li}\n<!-- WEEKLY_LIST_END -->',
            content, flags=re.DOTALL,
        )
        index_path.write_text(content, encoding="utf-8")


# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def _parse_news_md(md: str) -> List[str]:
    items = []
    for line in md.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ")):
            items.append(line[2:].strip())
        if len(items) >= 3:
            break
    return items
