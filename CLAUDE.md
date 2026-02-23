# ai-broker — Claude への指示（OpenClaw cron 用）

このファイルは OpenClaw の cron ジョブがトリガーされたときに Claude が従う指示です。

## 実行環境の前提

- 作業ディレクトリ: このリポジトリのルート（`ai-broker/`）
- 必要な環境変数: `OPENAI_API_KEY`
- Python 3.12+、git が使用可能なこと

## cron から呼ばれたときの動作

### 「平日ジョブを実行」と言われた場合

```bash
cd /path/to/ai-broker
python scripts/run_daily.py
```

### 「週末ジョブを実行」と言われた場合

```bash
cd /path/to/ai-broker
python scripts/run_weekend.py
```

## 注意事項

- スクリプトはロックファイルで冪等性を保っているため、同日に二重実行されても安全
- エラー時は `STATE/last_run.json` にエラー内容が記録される
- git push まで自動で行うため、認証情報（SSH or HTTPS token）が設定済みであること
