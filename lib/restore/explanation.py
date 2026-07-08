# -*- coding: utf-8 -*-
# command_station_app/lib/restore/explanation.py
# ============================================================
# 復元ページ 説明UI
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
def render_restore_page_intro() -> None:

    # ------------------------------------------------------------
    # AI利用なし
    # ------------------------------------------------------------
    render_info_card_compact(
        body_html="""
🟢 このページでは，<b>AIは使用しません</b>．バックアップ latest から正本へ復元します．
""",
    )

    # ------------------------------------------------------------
    # 使い方
    # ------------------------------------------------------------
    render_info_card_bullets_compact_custom(
        title="使い方",
        items=[
            ("▶️", "<b>復元元を確認するとき</b>"),
            ("", "backup / backup2 のうち，接続中のバックアップSSDを確認します．"),
            ("▶️", "<b>復元前に差分を確認するとき</b>"),
            ("", "Dry-run を実行して，コピー・削除される内容を確認します．"),
            ("▶️", "<b>実際に復元するとき</b>"),
            ("", "復元先の正本パスを確認し，確認チェックをオンにして実行します．"),
            ("▶️", "<b>結果を保存するとき</b>"),
            ("", "実行後，「結果をTXTで保存」から復元ログを保存します．"),
            ("⚠️", "復元では daily は使いません．必ず latest を復元元にします．"),
            ("⚠️", "復元は --delete を使います．復元先にしか存在しないファイルは削除されます．"),
            ("⚠️", ".DS_Store と _preview_cache/ は復元対象から除外します．"),
        ],
    )

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)


# ============================================================
# public API：詳細説明 expander
# ============================================================
def render_restore_explanation(
    *,
    location: str,
    projects_root,
    theme: dict[str, Any] | None = None,
    banner_key: str = "light_green",
) -> None:

    # ------------------------------------------------------------
    # 復元の重要警告
    # ------------------------------------------------------------
    st.warning(
        "復元は --delete を使います。復元先にしか存在しないファイルは削除され、"
        "バックアップ latest と同じ状態になります。"
    )

    st.caption(f"location: {location}")
    st.caption(f"projects_root: {projects_root}")

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
        label="復元説明（.txt）をダウンロード",
        data=build_restore_explanation_text(),
        file_name="restore_explanation.txt",
        mime="text/plain",
        key="restore_explanation_txt_download",
    )


# ============================================================
# expander 設定
# ============================================================
HELP_EXPANDER_KEY = "restore_help_expander"
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
RESTORE_USAGE_TEXT = """
<div style="line-height:1.7">

#### 1. このページの役割

このページは，バックアップSSD上の latest から，正本データを復元するためのページです。

復元は，用途ごとに分離して実行します。

- storages + auth
- inbox
- archive
- databases

---

#### 2. 基本的な流れ

1. 復元元となるバックアップSSDが接続されていることを確認します。
2. 復元対象の用途を選択します。
3. 復元元 latest のパスを確認します。
4. 復元先となる正本パスを確認します。
5. まず Dry-run で差分を確認します。
6. 問題がなければ確認チェックをオンにして復元を実行します。
7. 実行後，「結果をTXTで保存」からログを保存します。

---

#### 3. daily は使用しません

このページの復元では daily は使用しません。

復元元は，必ずバックアップSSD上の latest です。

---

#### 4. latest を使う理由

latest は，バックアップ時に正本の最新状態として作成された完全ミラーです。

復元では，この latest を正本へ戻すことで，正本をバックアップ時点の最新状態へそろえます。

</div>
"""


# ============================================================
# 詳細説明：復元元と復元先
# ============================================================
RESTORE_SOURCE_TARGET_TEXT = """
<div style="line-height:1.7">

#### 1. 復元元

復元元は，バックアップSSD上の latest です。

形式は次の通りです。

""" + _pre("<SSD_MOUNT>/aisv_Backups/<location>/backups/<name>/latest") + """

例：

""" + _pre("/Volumes/PAIS_HOME_HD10TB/aisv_Backups/Home/backups/archive/latest") + """

---

#### 2. 復元先

復元先は，現在の正本パスです。

正本パスは，internal / external の設定に従って解決されます。

例：

""" + _pre("/Volumes/PAIS_HOME_SSD4TB/Archive") + """

---

#### 3. 復元方向

復元方向は一方向です。

""" + _pre("backup latest  →  正本") + """

正本から backup latest へ戻す処理ではありません。

---

#### 4. backup / backup2

backup と backup2 のどちらを使うかは，接続中のバックアップSSDから選択します。

復元時には，どのSSDの latest を使うかを必ず確認してください。

</div>
"""


# ============================================================
# 詳細説明：latest と daily
# ============================================================
RESTORE_LATEST_DAILY_TEXT = """
<div style="line-height:1.7">

#### 1. 復元では latest のみを使います

復元元は latest です。

daily は復元元として使用しません。

---

#### 2. latest の意味

latest は，バックアップ時に作成される最新ミラーです。

バックアップ時には，正本から latest へ rsync --delete が実行されます。

そのため latest は，バックアップ時点の正本にそろえられています。

---

#### 3. daily の意味

daily は，時刻付きスナップショットです。

履歴を残すための保存領域であり，この復元ページでは直接使用しません。

---

#### 4. daily を使わない理由

daily は過去時点のスナップショットであり，どの時点を戻すかの判断が必要になります。

このページでは，誤操作を避けるため，復元対象を latest に限定します。

---

#### 5. 過去時点へ戻したい場合

過去の daily へ戻したい場合は，このページの通常復元ではなく，別途，対象 daily を確認したうえで個別対応する必要があります。

</div>
"""


# ============================================================
# 詳細説明：rsync
# ============================================================
RESTORE_RSYNC_TEXT = """
<div style="line-height:1.7">

#### 1. 使用する rsync

このページでは，Homebrew 版 rsync を使用します。

""" + _pre("/opt/homebrew/bin/rsync") + """

---

#### 2. 復元の実行

復元では，次のような rsync を実行します。

""" + _pre("rsync -a --delete --itemize-changes --exclude=.DS_Store --exclude=_preview_cache/ <latest>/ <restore_to>/") + """

---

#### 3. --delete

--delete により，復元元 latest に存在しないファイルは，復元先から削除されます。

つまり，復元先は latest と同じ状態へそろえられます。

---

#### 4. --itemize-changes

--itemize-changes により，追加・更新・削除されたファイル名を出力します。

この出力は，画面表示やTXTログの保存に使います。

---

#### 5. Dry-run

Dry-run では，次のような rsync を実行します。

""" + _pre("rsync -a --delete --dry-run --itemize-changes --exclude=.DS_Store --exclude=_preview_cache/ <latest>/ <restore_to>/") + """

Dry-run では，コピー・削除は実行されません。

復元前に必ず Dry-run で差分を確認してください。

</div>
"""


# ============================================================
# 詳細説明：除外対象
# ============================================================
RESTORE_EXCLUDES_TEXT = """
<div style="line-height:1.7">

#### 1. 除外対象

このページでは，次のファイル・フォルダを復元対象から除外します。

""" + _pre('RSYNC_EXCLUDES = [\n    "--exclude=.DS_Store",\n    "--exclude=_preview_cache/",\n]') + """

---

#### 2. .DS_Store

.DS_Store は macOS が自動作成する表示設定用ファイルです。

業務データの正本ではないため，復元対象から除外します。

---

#### 3. _preview_cache/

_preview_cache/ は，画面プレビュー用に作成される補助キャッシュです。

元ファイルではないため，復元対象から除外します。

---

#### 4. 除外と --delete の関係

除外対象は rsync の管理対象外になります。

そのため，--delete を使う場合でも，除外対象は復元元・復元先の同期判定から外れます。

</div>
"""


# ============================================================
# 詳細説明：実行結果ログ
# ============================================================
RESTORE_LOG_TEXT = """
<div style="line-height:1.7">

#### 1. TXTログ

復元実行後，結果をTXTで保存できます。

TXTログには，主に次の情報を記録します。

- 実行日時
- location
- 復元元 latest
- 復元先正本パス
- Dry-run の有無
- 実行した rsync コマンド
- returncode
- 追加されたファイル
- 更新されたファイル
- 削除されたファイル
- rsync の raw stdout

---

#### 2. 追加・更新・削除の意味

復元ログにおける追加・更新・削除は，復元先で発生する変更です。

- 追加：latest にあり，復元先にないファイルを復元先へ作成します。
- 更新：latest と復元先で内容や時刻が異なるファイルを更新します。
- 削除：latest に存在しないファイルを復元先から削除します。

---

#### 3. raw stdout

TXTログには，rsync の raw stdout も参考情報として残します。

これは，トラブル時に rsync の実際の出力を確認できるようにするためです。

</div>
"""


# ============================================================
# 詳細説明：注意点
# ============================================================
RESTORE_CAUTION_TEXT = """
<div style="line-height:1.7">

#### 1. 復元は不可逆処理を含みます

復元では --delete を使用します。

そのため，復元先にしか存在しないファイルは削除されます。

実行前に，復元元 latest と復元先正本パスを必ず確認してください。

---

#### 2. 必ず Dry-run を先に実行してください

復元前には，必ず Dry-run を実行してください。

Dry-run で追加・更新・削除の内容を確認してから，通常実行してください。

---

#### 3. daily は使いません

このページでは daily を使いません。

復元元は latest のみです。

---

#### 4. 復元先を間違えないでください

復元先を間違えると，別の正本データが latest の内容で上書き・削除される可能性があります。

特に Home / Prec / Portable など location の違いに注意してください。

---

#### 5. backup / backup2 の取り違え

backup と backup2 は物理的に別の記憶装置であることを想定しています。

復元時には，どちらのバックアップSSDから戻すのかを必ず確認してください。

</div>
"""


# ============================================================
# 詳細説明：FAQ
# ============================================================
RESTORE_FAQ_TEXT = """
<div style="line-height:1.7">

#### Q1. このページではAIを使いますか？

いいえ。このページではAIは使用しません。

---

#### Q2. 復元では daily を使いますか？

いいえ。復元では daily は使いません。

必ず latest を復元元にします。

---

#### Q3. latest とは何ですか？

latest は，バックアップ時に正本の最新状態として作成された完全ミラーです。

---

#### Q4. 復元すると何が起きますか？

backup latest の内容で，復元先の正本をそろえます。

復元先にしか存在しないファイルは削除されます。

---

#### Q5. Dry-run ではファイルは変更されますか？

いいえ。Dry-run ではコピー・削除は行われません。

---

#### Q6. .DS_Store と _preview_cache/ は復元されますか？

いいえ。どちらも復元対象から除外します。

---

#### Q7. 実行結果を保存できますか？

はい。実行後に「結果をTXTで保存」からログを保存できます。

</div>
"""


# ============================================================
# 詳細説明タブ
# ============================================================
HELP_TABS = [
    ("復元（使い方）", RESTORE_USAGE_TEXT),
    ("復元元と復元先", RESTORE_SOURCE_TARGET_TEXT),
    ("latest / daily", RESTORE_LATEST_DAILY_TEXT),
    ("rsync", RESTORE_RSYNC_TEXT),
    ("除外対象", RESTORE_EXCLUDES_TEXT),
    ("実行結果ログ", RESTORE_LOG_TEXT),
    ("注意点", RESTORE_CAUTION_TEXT),
    ("FAQ", RESTORE_FAQ_TEXT),
]


# ============================================================
# TXTダウンロード用説明本文
# ============================================================
def build_restore_explanation_text() -> str:
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