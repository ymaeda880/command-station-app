# -*- coding: utf-8 -*-
# lib/backup/explanation.py
#
# バックアップ（storages+auth / inbox）ページの利用者向け説明（Streamlit用）
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
    return """バックアップ（storages+auth / inbox）説明（latest + daily）

1. 目的
・プロジェクト配下の重要データを外付けSSDへ rsync でバックアップする。
・「latest（最新ミラー）」と「daily（時刻付きスナップショット）」を併用する。
・このページでは、下記を“別処理（別ボタン・別確認チェック）”として実行する。
  (A) storages + auth バックアップ
  (B) inbox バックアップ

2. バックアップ対象（論理単位）
(A) storages + auth
・storages: Storages（正本APIで解決：internal/external は設定に従う）
・auth    : auth_portal_project/auth_portal_app/data（固定パス：認証データ正本）
(B) inbox
・inbox   : InBoxStorages（正本APIで解決：internal/external は設定に従う）

※ storages / auth / inbox は完全に分離して保存する（混在させない）。

3. バックアップ先のディレクトリ構造（SSD側）
<SSD_MOUNT>/aisv_Backups/backups/
  storages/
    latest/                 （最新ミラー：--delete 付き）
    daily/YYYY-MM-DD_HHMMSS/（時刻付きスナップショット）
    logs/                   （実行ログ）
  auth/
    latest/
    daily/YYYY-MM-DD_HHMMSS/
    logs/
  inbox/
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

5. 設定ファイル要件（正本：command_station）
(A) secrets.toml（必須）
・location は command_station secrets.toml を正本として取得する。

(B) storage.toml（必須）
・バックアップ先SSDは storage.toml の定義を参照する。
  [storage.external.<location>.backup].root
  [storage.external.<location>.backup2].root （任意）

※ backup / backup2 は常に external（SSD）として扱う前提。
※ 未接続や設定不備は、ページ上で警告表示し、接続中のみボタンを有効化する。

6. SSD の判定（接続状態）
・storage.toml の root に書かれたパス（例：/Volumes/xxx）が
  実在しディレクトリである場合のみ「接続中」と判定する。
・未接続でもページは停止しない（管理者が状態確認できるようにする）。

7. UIオプション（セクションごとに独立）
・daily は差分（--link-dest）で節約：
  daily を link-dest で作成して容量を節約する（推奨）。
・Dry-run：
  rsync --dry-run（コピーせず、実行内容の表示のみ）。
・確認チェック：
  選択したSSDに latest（--delete）と daily を作成する（不可逆）ことの明示確認。
※ storages+auth と inbox は別処理のため、チェックもボタンも別々である。

8. 実行と同時実行防止
・実行中は同時実行を防止する（別セクションも含めて二重実行しない）。

9. ログ（今後の拡張余地）
・各バックアップセットごとに logs/ を用意している。
・実行ログの保存方針は運用に合わせて整理・拡張可能。

10. 注意事項（重要）
・latest は --delete を伴うため不可逆である。
・SSD選択を誤ると、バックアップ先内容が上書きされる可能性がある。
・実行環境に rsync が必要。
"""


def render_backup_explanation() -> None:
    """バックアップ説明の expander を描画し、.txt ダウンロードを提供する。"""
    text = _backup_explanation_text()

    with st.expander("ℹ️ バックアップの説明（クリックで開く）", expanded=False):
        st.download_button(
            label="説明（.txt）をダウンロード",
            data=text,
            file_name="backup_explanation.txt",
            mime="text/plain",
        )
        st.text(text)
