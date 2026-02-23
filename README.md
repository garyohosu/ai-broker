# 🤖 ai-broker

**6人のAIエージェントが東証銘柄で仮想売買を競う、OpenClaw cron 実験**

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-公開中-blue?logo=github)](https://garyohosu.github.io/ai-broker/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

👉 **[ブログを見る → garyohosu.github.io/ai-broker](https://garyohosu.github.io/ai-broker/)**

---

## 概要

東証（TSE）上場銘柄のみを対象に、6人のAIエージェントがそれぞれの戦略で**仮想ペーパートレード**を行い、結果をGitHub Pagesに自動公開するプロジェクトです。

- 売買はすべて**仮想**（実際の投資ではありません）
- 変更（データ・記事・取引ログ）はすべて**GitHubでバージョン管理**
- 定期実行は**OpenClaw**が担当（cron）
- 週末に注文計画を決定し、**月曜の始値で約定**したものとして計算
- 取引後は**全額株式・現金ゼロ**で運用

---

## 投資エージェント一覧

| エージェント | 戦略 | 特徴 |
|---|---|---|
| 📈 **上昇太郎** | トレンドフォロー | 上昇モメンタムに乗る強気派 |
| 📰 **速読アイ子** | ニュース・材料 | 適時開示・決算を誰より早く読む |
| 🔄 **反町リバ男** | 逆張り | 売られすぎ銘柄を狙うコントラリアン |
| 📊 **金利次郎** | マクロ・金利 | 日銀・金利・指数からマクロ判断 |
| 🎲 **運任せ子** | ランダム | ベンチマーク対照用。サイコロで決める |
| 🧬 **進化未来** | 重み付け統合 | 他5人の提案を成績ベースで加重平均 |

各エージェントの詳細設定は [`agents/`](agents/) ディレクトリを参照。

---

## 自動更新スケジュール（JST）

| 時刻 | 内容 |
|---|---|
| 平日 16:30 | 価格収集 → 資産評価 → 日次記事 → push |
| 土曜 21:00 | 週次討論 → 注文計画生成 → push |
| 日曜 21:00 | 週次記事確定 → push |
| 月曜 16:30 | 前週末の計画を始値で約定 → ポートフォリオ更新 |

---

## ディレクトリ構成

```
ai-broker/
├── spec.md                   # 仕様書
├── agents/                   # エージェント定義
│   ├── taro.md / aiko.md ... # キャラ設定・判断基準
│   └── weights.json          # 進化未来の重み（月1回更新）
├── data/
│   ├── universe/tickers.json # 対象銘柄ユニバース（東証）
│   ├── prices/               # 日次終値データ
│   ├── macro/                # 指数・金利データ
│   ├── news/                 # 重要材料ニュース
│   ├── portfolios/           # 各社員の現在ポートフォリオ
│   ├── trades/               # 注文計画・約定結果
│   └── equity/               # 日次資産評価
├── docs/                     # GitHub Pages 配信
│   ├── index.html
│   ├── posts/daily/          # 日次記事
│   ├── posts/weekly/         # 週次記事
│   └── assets/css/
├── scripts/
│   ├── run_daily.py          # 平日ジョブ
│   ├── run_weekend.py        # 週末ジョブ
│   └── lib/                  # ライブラリ
│       ├── market.py         # 価格取得（yfinance）
│       ├── portfolio.py      # 評価・約定計算
│       ├── claude_client.py  # OpenAI API連携
│       ├── render.py         # HTML記事生成
│       └── utils.py          # ロック・日付・git操作
└── STATE/
    ├── last_run.json         # 最終実行状態
    └── lock/                 # 冪等性ロック
```

---

## セットアップ

### 必要環境
- Python 3.12+
- OpenAI API キー

### インストール

```bash
git clone https://github.com/garyohosu/ai-broker.git
cd ai-broker
pip install -r requirements.txt
```

### 環境変数

```bash
export OPENAI_API_KEY=sk-...
```

### 手動実行

```bash
# 平日ジョブ（今日の日付で実行）
python scripts/run_daily.py

# 特定日付で実行
python scripts/run_daily.py --date 2026-02-23

# git push なしでテスト
python scripts/run_daily.py --dry-run

# 週末ジョブ
python scripts/run_weekend.py
```

---

## 取引ルール

1. **対象**: 東証上場銘柄・ETF・REIT（[`data/universe/tickers.json`](data/universe/tickers.json) に記載）
2. **注文**: 毎週末に各エージェントが来週の配分比率（合計100%）を決定
3. **約定**: 翌月曜の**始値**で約定したものとして計算
4. **全額株式**: 約定後は現金ゼロ・全額株式で保有
5. **評価**: 毎営業日の**終値**で資産評価
6. **進化**: 進化未来は月1回、直近12週の成績を基に重みを更新

---

## 技術スタック

| 用途 | 技術 |
|---|---|
| 価格データ | [yfinance](https://github.com/ranaroussi/yfinance)（Yahoo Finance） |
| AI生成 | [OpenAI API](https://platform.openai.com/) (gpt-5.2) |
| 記事生成 | Python + Tailwind CSS CDN |
| 公開 | GitHub Pages (`docs/` ディレクトリ) |
| 定期実行 | OpenClaw cron |

---

## 免責事項

> 本プロジェクトの売買はすべて**仮想ペーパートレード**です。実際の投資・売買を推奨するものではありません。投資は自己責任で行ってください。
