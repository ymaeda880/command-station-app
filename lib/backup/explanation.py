# -*- coding: utf-8 -*-
# lib/backup/explanation.py
#
# Storageバックアップ（latest + daily）ページの利用者向け説明（Streamlit用）
#
# - pages/73_バックアップ.py から import して呼び出す
# - 表示（expander）で概要を読めるようにしつつ、
#   「正本」はダウンロードした .txt（プレーンテキスト）として保存できるようにする
#
# ※ StreamlitのMarkdown表示は環境により崩れることがあるため、
#    st.text と download_button を併用する（表示は補助／正本はダウンロード）

from __future__ import annotations
import streamlit as st


def _backup_explanation_text() -> str:
    """ダウンロード用の説明本文（プレーンテキスト）を返す。"""
    return """Storageバックアップ（latest + daily） 説明

1. 目的
・プロジェクト配下の重要データを外付けSSDへ rsync でバックアップする。
・「latest（最新ミラー）」と「daily（時刻付きスナップショット）」を併用する。

2. バックアップ対象（論理単位）
・storages: <project_root>/Storages
・auth:     <project_root>/auth_portal_project/auth_portal_app/data
※ storages と auth は完全に分離して保存する。

3. バックアップ先のディレクトリ構造（SSD側）
<SSD_MOUNT>/aisv_Backups/backups/
  storages/
    latest/                 （最新ミラー：--delete 付き）
    daily/YYYY-MM-DD_HHMMSS/（時刻付きスナップショット）
    logs/                   （実行ログJSON）
  auth/
    latest/
    daily/YYYY-MM-DD_HHMMSS/
    logs/

4. latest と daily の意味（重要）
・latest:
  rsync --delete により「完全同期（ミラー）」を維持する。
  注意：--delete によりバックアップ先の不要ファイルは削除される（不可逆）。
・daily:
  時刻付きディレクトリにスナップショットを作成する。
  オプション「daily は差分（--link-dest）で節約」を有効にすると、
  --link-dest=latest を使い、差分はハードリンクとなって容量を節約できる。

5. 設定ファイル要件（必須）
(A) secrets.toml
  [env]
  location = "<location_name>"

(B) settings.toml
  [locations.<location_name>]
  project_root = "/absolute/path/to/projects"

  [backup.ssd]
  ssd1 = "Extreme SSD"
  ssd2 = "aisv backup"   # 任意

※ project_root / SSD設定が欠けている場合は停止する（暗黙のデフォルトは置かない方針）。

6. SSD の解釈（マウント判定）
・ssd1/ssd2 が絶対パス（/ で始まる）の場合：そのパスをそのまま使用する。
・それ以外は /Volumes/<label> を期待マウント先として扱う。
・接続中（存在してディレクトリである）SSDのみ、実行ボタンを有効化する。

7. UIオプション
・daily は差分（--link-dest）で節約：
  daily を link-dest で作成して容量を節約する（推奨）。
・Dry-run：
  rsync --dry-run（コピーせず、実行内容の表示のみ）。
・確認チェック：
  選択したSSDに latest（--delete）と daily を作成する（不可逆）ことの明示確認。

8. ログ
・各バックアップセットごとに logs/ 配下へ JSONログを保存する。
・失敗時は *_latest_failed.json 等を出力して中断する。

9. 注意事項（重要）
・latest は --delete を伴うため不可逆である。
・SSD選択を誤ると、バックアップ先内容が上書きされる可能性がある。
・実行環境に rsync が必要。
・Python 3.11+（tomllib 使用）が前提。
"""


def render_backup_explanation() -> None:
    """バックアップ説明の expander を描画し、.txt ダウンロードを提供する。

    呼び出し側（例）:
        from lib.backup.explanation import render_backup_explanation
        render_backup_explanation()
    """
    text = _backup_explanation_text()

    with st.expander("ℹ️ Storageバックアップの説明（クリックで開く）", expanded=False):
        # 正本：ダウンロード（あなたがクリックして .txt を保存する前提）
        st.download_button(
            label="説明（.txt）をダウンロード",
            data=text,
            file_name="backup_explanation.txt",
            mime="text/plain",
        )

        # 表示：事故りにくいよう st.text を使う（Markdown依存を避ける）
        st.text(text)
