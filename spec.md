# ai-broker — spec.md

## 0. 目的

OpenClaw の cron 実験として、**東証（TSE）で売買できる銘柄のみ**を対象に「情報収集 → ブログ更新」と「週末の仮想売買 → 週次更新」を自動運用する。

- 変更（データ・記事・ルール・取引ログ）は **すべて GitHub でバージョン管理**
- 公開は **GitHub Pages**（静的サイト）
- 定期実行は **OpenClaw が担当**（ローカル or VPS 常駐）
- 売買は仮想（ペーパートレード）。**週末に判断し、月曜の始値で約定したものとして計算**
- 取引後は **全額株式（現金 0 円）**になるよう配分する（端数調整は最後の銘柄に寄せる）

---

## 1. スコープ

### 1.1 含む
- 平日（営業日）の日次データ収集
- 日次ブログ記事の生成・更新
- 週末（土日）の週次会議（チャットログ）生成
- 週次の仮想売買計画（注文）生成
- 月曜始値での約定処理（平日ジョブ内で反映）
- 各社員（アルゴリズム）の独立運用（独立口座）
- 資産の「毎日」前日比表示（円・％）
- 重要そうな材料（株価に影響しそうな情報）を収集し、売買しない日も表示

### 1.2 含まない（今回やらない）
- 実売買（証券口座 API 連携）
- NISA 対象かどうかの判定（**今回は「東証で買えるもの」に限定**）
- 100円単位などの発注単位制約（撤回：縛りなし）
- 機械学習の高度なモデル訓練（まずはルール＋軽い「進化」）

---

## 2. 成果物（リポジトリ）

### 2.1 リポジトリ名
- `ai-broker`

### 2.2 推奨ディレクトリ構成（最小で回る形）
```
ai-broker/
  spec.md
  README.md
  docs/                       # GitHub Pages 配信（docs/ を公開に設定）
    index.html
    posts/
      daily/
      weekly/
    assets/
      avatars/                # 社員アイコン（png）
      css/
  data/                       # すべてコミットして監査ログにする
    universe/
      tickers.json            # 対象銘柄ユニバース（TSE）
    prices/
      YYYY-MM-DD.json         # 日次終値データ
      meta.json               # データ取得元・更新情報
    macro/
      YYYY-MM-DD.json         # 指数・金利・為替(必要なら)など
    news/
      YYYY-MM-DD.md           # 重要材料（見出し＋出典）
    portfolios/
      taro.json
      aiko.json
      ribao.json
      jiro.json
      omakaseko.json
      mirai.json
    trades/
      YYYY-MM-DD/
        plans.json            # 週末に作る「注文計画」
        fills.json            # 月曜に反映する「約定結果」
    equity/
      YYYY-MM-DD.json         # 各社員の資産（評価額）と前日比
  agents/
    taro.md
    aiko.md
    ribao.md
    jiro.md
    omakaseko.md
    mirai.md
    weights.json              # 進化（重み）用の設定
  scripts/
    run_daily.py              # 平日：収集→評価→日次記事
    run_weekend.py            # 週末：会議→注文計画→週次記事
    lib/
      market.py               # 取得・正規化
      portfolio.py            # 評価・リバランス計算
      render.py               # 記事（Markdown/HTML）生成
      utils.py                # ロック・日付・ログ
  STATE/
    last_run.json
    lock/
```

---

## 3. Pages（ブログ）仕様

### 3.1 表示形式
- 記事本文は Markdown 生成でよい（GitHub Pages 側でそのまま表示するなら HTML に変換して配置）
- チャット風表示：`docs/assets/css/chat.css` を用意し、発言は以下の最小 HTML 断片で表現できること  
  （Markdown内にHTMLを埋め込んでも可）

例（1発言）：
```html
<div class="msg">
  <img class="avatar" src="/assets/avatars/taro.png" alt="taro">
  <div class="bubble">
    <div class="name">上昇太郎</div>
    <div class="text">今日の資産：1,012,340円（前日比 +12,340円 / +1.23%）</div>
  </div>
</div>
```

### 3.2 日次記事（平日）
出力先：
- `docs/posts/daily/YYYY-MM-DD.html`（または `.md`）

内容（最低限）：
- 市場サマリ（例：日経、TOPIX の前日比）
- 重要材料（最大3件、出典つき）
- 各社員の資産（当日・前日比 円/％）
- 各社員の一言（戦略目線の短文）

### 3.3 週次記事（週末）
出力先：
- `docs/posts/weekly/YYYY-Www.html`（週番号 or 日付）

内容（最低限）：
- 週間ランキング（社員の週次損益）
- 週末の討論会ログ（チャット）
- 各社員の「来週の配分」（全額株式、現金0円）
- 「約定は月曜始値」宣言

---

## 4. 取引（仮想）ルール

### 4.1 対象
- 東証で売買可能な銘柄・ETF・REIT（ユニバースは `data/universe/tickers.json`）

### 4.2 タイミング
- **週末（土日）**：注文計画（来週の配分）を確定
- **月曜（次営業日）**：始値で約定したものとして、保有を更新  
  ※ 実装上は「月曜の run_daily 内」で前週末の plans を fills に確定して反映する

### 4.3 全額株式（現金 0 円）
- 注文計画は「銘柄→比率（合計100%）」で表現する
- 月曜始値での約定時、各銘柄の購入額を `総資産 × 比率` で決め、最後の銘柄で端数調整して現金を 0 円にする

### 4.4 評価（毎営業日）
- 各社員の資産は **終値** で評価
- `当日資産 = Σ(保有株数 × 終値) + 現金（原則0）`
- `前日比 = 当日資産 − 前日資産`
- `前日比% = 前日比 / 前日資産`

---

## 5. 社員（アルゴリズム）

### 5.1 必須社員（初期）
- 上昇太郎（トレンドフォロー）
- 速読アイ子（ニュース/材料）
- 反町リバ男（逆張り）
- 金利次郎（マクロ：金利・指数）
- 運任せ子（ランダム：ベンチマーク）
- 進化未来（進化：重み調整・学習担当、初期は任意）

各社員は以下を持つ：
- `agents/<name>.md`：キャラ設定、判断基準、弱点
- `data/portfolios/<name>.json`：現在ポートフォリオ（銘柄と数量）
- `data/equity/YYYY-MM-DD.json`：評価結果に含まれる（社員別）

### 5.2 進化（最低限で安全）
- 進化未来は「ルール生成」ではなく、まず **社員の提案を重み付け**して配分を微調整する方式
- 更新頻度：**月1回**
- 学習期間：直近 12 週
- 変更内容は `agents/weights.json` にコミットし、週次記事でバージョンを明示する

---

## 6. データ収集仕様（毎日）

### 6.1 収集対象（最小セット）
- 個別：対象ユニバースの終値（できれば出来高）
- 指数：日経平均、TOPIX（任意：グロース250）
- 金利：日本10年国債利回り（取得可能な範囲で）
- ニュース：
  - TDnet（適時開示）を優先
  - 重要トピック（決算、業績修正、配当、自社株買い、M&A、規制、事故など）

### 6.2 出典管理
- 収集データには必ず「取得元」と「取得時刻」を `data/prices/meta.json` に記録
- ニュースは `data/news/YYYY-MM-DD.md` に、見出し＋出典名（可能ならURL）を残す

---

## 7. OpenClaw cron（運用）

### 7.1 実行内容（共通）
1. `git pull`
2. スクリプト実行（平日/週末）
3. `git add -A`
4. `git commit -m "..."`
5. `git push`

### 7.2 推奨スケジュール（JST）
- 平日：16:30（東証引け後）
- 土曜：21:00（週次会議・注文計画）
- 日曜：21:00（週次記事の整形・確定）

### 7.3 冪等性（同日二重実行対策）
- `STATE/lock/` にロックファイルを置く
- 同一日付の outputs が既に存在する場合は、原則「追記しない」か「上書きしない」  
  （上書きする場合は version を上げて差分が分かる形にする）

---

## 8. 失敗時の扱い（最低限）
- 失敗ログ：`STATE/last_run.json` に status と error 要約を書き込む
- 途中失敗でも、GitHub に中間生成物を push しない（コミット前にエラーで停止）
- 必要なら `scripts/lib/utils.py` にリトライ（最大1回）を実装

---

## 9. セキュリティ（最低限）
- 秘密情報（APIキー等）は **リポジトリに絶対に入れない**
- ログにトークンやパスを出さない
- 取得元が変わる可能性があるため、スクレイピング依存を最小化し、出典を常に記録する

---

## 10. 受け入れ条件（Acceptance Criteria）

### 10.1 初期セットアップ
- `ai-broker` リポジトリに `spec.md` が存在
- `docs/` 配下が GitHub Pages で公開され、トップが表示される

### 10.2 平日ジョブ
- 指定日に `data/prices/YYYY-MM-DD.json` が生成される
- `data/news/YYYY-MM-DD.md` が生成される（0件でもファイルは作る）
- `data/equity/YYYY-MM-DD.json` が生成され、全社員の資産と前日比が入る
- `docs/posts/daily/YYYY-MM-DD.*` が生成され、公開される
- すべてが 1 commit で push される

### 10.3 週末ジョブ
- `data/trades/YYYY-MM-DD/plans.json` が生成される（社員ごとに配分がある）
- `docs/posts/weekly/YYYY-Www.*` が生成され、討論会ログと配分が載る
- 月曜の平日ジョブで `fills.json` が確定し、各社員のポートフォリオが更新される

### 10.4 全額株式
- 月曜約定後、各社員の現金が 0 円（または計算上ゼロ）であることが、ログ上で確認できる

---

## 11. 次フェーズ（将来）
- アイコン自動生成（image_gen 連携や一括生成）
- 進化未来の強化（過学習防止のガードレール付き）
- 重要イベントのカレンダー化（決算週の自動注意喚起）
- 分析ページ（最大DD、勝率、シャープ等）の追加

## 12.注記
googleアドセンスを書くページに入れておくこと
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-6743751614716161"
     crossorigin="anonymous"></script>

各ページはCDNを使ったモダンなサイトとすること
記事は読んで面白いものを作る事。

