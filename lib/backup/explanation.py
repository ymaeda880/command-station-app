# -*- coding: utf-8 -*-
# command_station_app/lib/backup/explanation.py
# ============================================================
# バックアップページ 説明UI
#
# 機能：
# - ページ上部の概要説明を描画する
# - 詳細説明 expander を描画する
# - 説明本文を .txt としてダウンロードできるようにする
# ============================================================

from __future__ import annotations

# ============================================================
# imports
# ============================================================
from typing import Any
import re

import streamlit as st

from common_lib.ui.help_expander import render_themed_help_expander
from common_lib.ui.intro_panel import (
    render_info_card_compact,
    render_info_card_bullets_compact_custom,
)


# ============================================================
# ページ上部説明UI
# ============================================================
def render_backup_page_intro() -> None:

    # ------------------------------------------------------------
    # AI利用なし
    # ------------------------------------------------------------
    render_info_card_compact(
        body_html="""
🟢 このページでは，<b>AIは使用しません</b>．正本データを外部記憶装置へバックアップします．
""",
    )

    # ------------------------------------------------------------
    # 使い方
    # ------------------------------------------------------------
    render_info_card_bullets_compact_custom(
        title="使い方",
        items=[
            ("▶️", "<b>差分を確認するとき</b>"),
            ("", "Dry-run をオンにして実行します．コピー・削除は行われません．"),
            ("▶️", "<b>バックアップするとき</b>"),
            ("", "Dry-run をオフにし，確認チェックをオンにして実行します．"),
            ("▶️", "<b>結果を保存するとき</b>"),
            ("", "実行後，「結果をTXTで保存」からログを保存します．"),
            ("⚠️", "latest は --delete を使用します．バックアップ先SSDを必ず確認してください．"),
            ("⚠️", ".DS_Store と _preview_cache/ はバックアップ対象から除外します．"),
        ],
    )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)


# ============================================================
# public API：詳細説明 expander
# ============================================================
def render_backup_explanation(
    *,
    theme: dict[str, Any] | None = None,
    banner_key: str = "light_green",
) -> None:
    render_themed_help_expander(
        expander_key=HELP_EXPANDER_KEY,
        expander_title=HELP_EXPANDER_TITLE,
        tabs=HELP_TABS,
        theme=theme,
        banner_key=banner_key,
        expanded=False,
    )

    # ------------------------------------------------------------
    # 説明本文のTXTダウンロード
    # ------------------------------------------------------------
    st.download_button(
        label="バックアップ説明（.txt）をダウンロード",
        data=build_backup_explanation_text(),
        file_name="backup_explanation.txt",
        mime="text/plain",
        key="backup_explanation_txt_download",
    )


# ============================================================
# expander 設定
# ============================================================
HELP_EXPANDER_KEY = "backup_help_expander"
HELP_EXPANDER_TITLE = "詳細説明（クリックで展開）"


# ============================================================
# HTML表示用の補助
# ============================================================
def _pre(text: str) -> str:
    return (
        "<pre style='"
        "background:#f7f7f7;"
        "padding:10px 12px;"
        "border-radius:8px;"
        "overflow-x:auto;"
        "line-height:1.5;"
        "font-size:0.92em;"
        "'>"
        f"{text}"
        "</pre>"
    )


# ============================================================
# 詳細説明：使い方
# ============================================================
BACKUP_USAGE_TEXT = f"""
<div style="line-height:1.7">

#### 1. このページの役割

このページは，正本データを外部記憶装置へバックアップするためのページです。

バックアップは，用途ごとに分離して実行します。

- storages + auth
- inbox
- archive
- databases

---

#### 2. 基本的な流れ

1. バックアップ先SSDが接続されていることを確認します。
2. 対象セクションのバックアップ元パスを確認します。
3. 必要に応じて Dry-run をオンにして差分を確認します。
4. 実行する場合は Dry-run をオフにします。
5. 確認チェックをオンにします。
6. 接続中のSSDボタンを押してバックアップを実行します。
7. 実行後，「結果をTXTで保存」からログを保存します。

---

#### 3. 実行結果ログ

実行結果は，画面表示に加えて，TXTで保存できます。

TXTログには，実行した rsync コマンド，returncode，追加・更新・削除されたファイル情報を記録します。

</div>
"""


# ============================================================
# 詳細説明：対象データ
# ============================================================
BACKUP_TARGETS_TEXT = """
<div style="line-height:1.7">

#### 1. バックアップ対象

このページでは，次のデータをバックアップします。

- storages
- auth
- inbox
- archive
- databases

---

#### 2. storages + auth

storages は，ユーザーごとの保存領域や管理用データを含む保存領域です。

auth は，認証ポータルのユーザー情報やパスワード関連データを保存する領域です。

---

#### 3. inbox

inbox は，InBox 用の保存領域です。

---

#### 4. archive

archive は，プロジェクト報告書や関連書類などの保存領域です。

---

#### 5. databases

databases は，RAG 用データベースなどを保存する領域です。

</div>
"""


# ============================================================
# 詳細説明：パス設定
# ============================================================
BACKUP_PATHS_TEXT = f"""
<div style="line-height:1.7">

#### 1. location

このページでは，command_station_app/.streamlit/secrets.toml の location を使用します。

例：

{_pre('[env]\\nlocation = "Home"')}

この場合，当該パソコンは Home 環境として扱われます。

---

#### 2. 正本パス

正本パスは，internal / external の設定に従って解決されます。

例：Archive を外部記憶装置に置く場合

{_pre('[archive]\\nmode = "external"')}

さらに storage.toml に実際の保存先を指定します。

{_pre('[archive.storage.external.Home]\\nroot = "/Volumes/PAIS_HOME_SSD4TB/Archive"')}

---

#### 3. バックアップ先パス

バックアップ先は，backup / backup2 として設定します。

{_pre('[archive.backup.Home]\\nroot = "/Volumes/PAIS_HOME_HD10TB"\\n\\n[archive.backup2.Home]\\nroot = "/Volumes/PAIS_HOME_HD10TB_2"')}

---

#### 4. 保存先の基本形

{_pre('<SSD_MOUNT>/aisv_Backups/<location>/backups/<name>/{latest,daily,logs}')}

例：

{_pre('/Volumes/PAIS_HOME_HD10TB/aisv_Backups/Home/backups/archive/latest\\n/Volumes/PAIS_HOME_HD10TB/aisv_Backups/Home/backups/archive/daily/YYYY-MM-DD_HHMMSS\\n/Volumes/PAIS_HOME_HD10TB/aisv_Backups/Home/backups/archive/logs')}

</div>
"""


# ============================================================
# 詳細説明：latest と daily
# ============================================================
BACKUP_LATEST_DAILY_TEXT = """
<div style="line-height:1.7">

#### 1. latest

latest は，正本の最新状態を保持する完全ミラーです。

rsync の --delete を使用するため，正本に存在しないファイルは，バックアップ先 latest から削除されます。

---

#### 2. daily

daily は，時刻付きディレクトリに作成するスナップショットです。

保存先は daily/YYYY-MM-DD_HHMMSS/ です。

---

#### 3. --link-dest

daily は，必要に応じて --link-dest を使って作成します。

--link-dest を使うと，latest と同じ内容のファイルはハードリンクで共有されます。

そのため，latest と daily に同じファイルが見えていても，同じデータが二重に保存されるわけではありません。

---

#### 4. daily は latest のコピーではありません

daily は，正本から直接作成されます。

--link-dest=latest は，daily 作成時に latest と同じ内容のファイルをハードリンクで共有するための指定です。

latest をコピー元にする指定ではありません。

---

#### 5. latest を手動変更した場合

latest を手動で変更しても，次回バックアップ時には，正本から latest へ rsync --delete が実行されます。

そのため，latest だけに加えた手動変更は，正本の内容で上書きされます。

</div>
"""


# ============================================================
# 詳細説明：rsync
# ============================================================
BACKUP_RSYNC_TEXT = f"""
<div style="line-height:1.7">

#### 1. 使用する rsync

このページでは，Homebrew 版 rsync を使用します。

{_pre('/opt/homebrew/bin/rsync')}

---

#### 2. latest の実行

latest では，次のような rsync を実行します。

{_pre('rsync -a --itemize-changes --exclude=.DS_Store --exclude=_preview_cache/ --delete <src>/ <latest>/')}

--delete を使用するため，正本に存在しないファイルは latest から削除されます。

---

#### 3. daily の実行

daily では，次のような rsync を実行します。

{_pre('rsync -a --itemize-changes --link-dest <latest> --exclude=.DS_Store --exclude=_preview_cache/ <src>/ <daily>/')}

--link-dest を有効にしている場合，変更のないファイルは latest とハードリンクで共有されます。

---

#### 4. Dry-run

Dry-run では，次のような rsync を実行します。

{_pre('rsync -ani --dry-run --exclude=.DS_Store --exclude=_preview_cache/ --delete <src>/ <latest>/')}

Dry-run では，コピー・削除は実行されません。

---

#### 5. --itemize-changes

通常実行でも --itemize-changes を付けます。

これにより，バックアップ実行後のTXTログに，追加・更新・削除されたファイル名を残せます。

</div>
"""


# ============================================================
# 詳細説明：除外対象
# ============================================================
BACKUP_EXCLUDES_TEXT = f"""
<div style="line-height:1.7">

#### 1. 除外対象

このページでは，次のファイル・フォルダをバックアップ対象から除外します。

{_pre('rsync_excludes = [\\n    "--exclude=.DS_Store",\\n    "--exclude=_preview_cache/",\\n]')}

---

#### 2. .DS_Store

.DS_Store は macOS が自動作成する表示設定用ファイルです。

業務データの正本ではないため，バックアップ対象から除外します。

---

#### 3. _preview_cache/

_preview_cache/ は，画面プレビュー用に作成される補助キャッシュです。

元ファイルではないため，バックアップ対象から除外します。

---

#### 4. 除外の意味

除外対象は，latest にも daily にもコピーされません。

また，--delete を使う場合でも，除外対象は rsync の管理対象外になります。

</div>
"""


# ============================================================
# 詳細説明：実行結果ログ
# ============================================================
BACKUP_LOG_TEXT = """
<div style="line-height:1.7">

#### 1. TXTログ

バックアップ実行後，結果をTXTで保存できます。

TXTログには，主に次の情報を記録します。

- 実行日時
- location
- マウントポイント
- Dry-run の有無
- 実行した rsync コマンド
- returncode
- 追加されたファイル
- 更新されたファイル
- 削除されたファイル
- rsync の raw stdout

---

#### 2. 追加・更新・削除の整理

TXTログでは，rsync の itemize 出力を，利用者向けに次のように整理します。

- 追加
- 更新
- 削除
- ディレクトリ変更

---

#### 3. raw stdout

TXTログには，rsync の raw stdout も参考情報として残します。

これは，トラブル時に rsync の実際の出力を確認できるようにするためです。

</div>
"""


# ============================================================
# 詳細説明：注意点
# ============================================================
BACKUP_CAUTION_TEXT = """
<div style="line-height:1.7">

#### 1. latest は不可逆処理を含みます

latest では --delete を使用します。

そのため，バックアップ先にだけ存在するファイルは削除されます。

実行前に，バックアップ先SSDを間違えていないか必ず確認してください。

---

#### 2. Dry-run を先に実行してください

初回や設定変更後は，先に Dry-run を実行してください。

Dry-run で追加・更新・削除の内容を確認してから，通常実行することを推奨します。

---

#### 3. backup と backup2

backup / backup2 は，物理的に別の外部記憶装置にすることを想定しています。

同じSSD上に backup と backup2 を作ると，物理障害時の保護になりません。

---

#### 4. テスト運用後の削除

テスト運用で作成した latest・daily・logs は，正式運用開始前にフォルダーごと削除することを推奨します。

正式運用開始後の最初のバックアップを，基準となるベースラインとして扱います。

</div>
"""


# ============================================================
# 詳細説明：FAQ
# ============================================================
BACKUP_FAQ_TEXT = """
<div style="line-height:1.7">

#### Q1. このページではAIを使いますか？

いいえ。このページではAIは使用しません。

---

#### Q2. Dry-run ではファイルはコピーされますか？

いいえ。Dry-run ではコピー・削除は行われません。

---

#### Q3. latest は何ですか？

latest は，正本の最新状態を保持する完全ミラーです。

--delete により，正本に存在しないファイルは latest から削除されます。

---

#### Q4. daily は latest のコピーですか？

いいえ。daily は正本から直接作成されます。

--link-dest は，latest と同じ内容のファイルをハードリンクで共有するための指定です。

---

#### Q5. .DS_Store と _preview_cache/ はバックアップされますか？

いいえ。どちらもバックアップ対象から除外します。

---

#### Q6. 実行結果を保存できますか？

はい。実行後に「結果をTXTで保存」からログを保存できます。

</div>
"""


# ============================================================
# 詳細説明タブ
# ============================================================
HELP_TABS = [
    ("バックアップ（使い方）", BACKUP_USAGE_TEXT),
    ("対象データ", BACKUP_TARGETS_TEXT),
    ("パス設定", BACKUP_PATHS_TEXT),
    ("latest / daily", BACKUP_LATEST_DAILY_TEXT),
    ("rsync", BACKUP_RSYNC_TEXT),
    ("除外対象", BACKUP_EXCLUDES_TEXT),
    ("実行結果ログ", BACKUP_LOG_TEXT),
    ("注意点", BACKUP_CAUTION_TEXT),
    ("FAQ", BACKUP_FAQ_TEXT),
]


# ============================================================
# TXTダウンロード用説明本文
# ============================================================
def build_backup_explanation_text() -> str:
    """
    ダウンロード用の説明本文を返す。
    HTMLタグは簡易的に除去して，プレーンテキストにする。
    """
    text = "\n\n".join(content for _, content in HELP_TABS)

    text = re.sub(r"<pre[^>]*>", "\n", text)
    text = text.replace("</pre>", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip() + "\n"