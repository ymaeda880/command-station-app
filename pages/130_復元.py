# -*- coding: utf-8 -*-
# command_station_app/pages/130_復元.py
# ============================================================
# ♻️ 復元（バックアップ latest から正本へ）
#
# 目的：
# - バックアップSSD上の latest から正本へ復元する。
# - 先に rsync --dry-run で差分を確認する。
# - 差分確認後のみ rsync --delete で復元する。
#
# 復元方向：
#   <BackupSSD>/aisv_Backups/<location>/backups/<name>/latest/
#   →
#   正本ディレクトリ
#
# 注意：
# - --delete を使うため、復元先は latest と完全一致する。
# - 復元先にしかないファイルは削除される。
# - 必ず差分確認後に実行する。
#
# テンプレ準拠：
# - page_session_heartbeat を必ず実行（sub_session を真実として扱う）
# - バナー表示（app settings.toml の ui_banner_key）
# - 管理者チェック：sub_session が admin_users に含まれるかで判定（cookie/JWT 再読込なし）
# - use_container_width 不使用
# - st.form 不使用
# - st.button()/st.download_button() に width 引数を使わない
#
# 方針：
# - SSD未接続でもページ全体を st.stop() で止めない。
# - 接続されていない対象セクションはスキップ表示にする。
# - 120_バックアップ.py と同じく、用途別セクション形式で表示する。
# ============================================================

from __future__ import annotations

# ============================================================
# imports（stdlib）
# ============================================================
from datetime import datetime
from pathlib import Path
import sys

# ============================================================
# imports（3rd party）
# ============================================================
import streamlit as st

# ============================================================
# page config（最初に1回だけ）
# ============================================================
st.set_page_config(
    page_title="Command Station",
    page_icon="♻️",
    layout="wide",
)

# ============================================================
# パス設定（テンプレ準拠：MONO_ROOT / PROJ_DIR / APP_DIR を sys.path へ）
# ============================================================
_THIS = Path(__file__).resolve()
APP_DIR = _THIS.parents[1]
PROJ_DIR = _THIS.parents[2]
MONO_ROOT = _THIS.parents[3]

for p in (MONO_ROOT, PROJ_DIR, APP_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

PROJECTS_ROOT = MONO_ROOT
APP_NAME = _THIS.parents[1].name
PAGE_NAME = _THIS.stem

# ============================================================
# common_lib（正本：UI + sessions + auth）
# ============================================================
from common_lib.sessions.page_entry import page_session_heartbeat  # noqa: E402
from common_lib.env.config import get_ui_banner_key_from_app_settings  # noqa: E402
from common_lib.ui.banner_lines import render_banner_line_by_key  # noqa: E402
from common_lib.ui.ui_basics import subtitle  # noqa: E402
import common_lib.auth.auth_helpers as authh  # noqa: E402

# ============================================================
# common_lib（env / storage / auth paths）
# ============================================================
from common_lib.env.config import get_location_from_command_station_secrets  # noqa: E402
from common_lib.storage.storages_config import resolve_storages_root  # noqa: E402
from common_lib.storage.inbox_config import resolve_inbox_root  # noqa: E402
from common_lib.storage.external_mount_probe import probe_backup_mounts_by_purpose  # noqa: E402
from common_lib.storage.external_ssd_root import resolve_storage_subdir_root_v2  # noqa: E402
from common_lib.auth.paths import resolve_auth_data_root  # noqa: E402

# ============================================================
# app lib
# ============================================================
from lib.restore.explanation import (  # noqa: E402
    render_restore_page_intro,
    render_restore_explanation,
)
from lib.restore.rsync_utils import (  # noqa: E402
    build_backup_latest_path,
    build_diff_cmd,
    build_restore_cmd,
    fmt_cmd,
    has_no_diff,
    run_result_from_dict,
    run_result_to_dict,
    sh,
)
from lib.restore.diff_utils import (  # noqa: E402
    build_diff_download_text,
    render_rsync_diff_summary,
    render_rsync_result,
)

# ============================================================
# バナー表示（共通UI）
# ============================================================
banner_key = get_ui_banner_key_from_app_settings(Path(__file__))
render_banner_line_by_key(banner_key)

# ============================================================
# ログイン + heartbeat（必ず実行）
# - sub_session を「ログイン判定の真実」として扱う
# ============================================================
sub_session = page_session_heartbeat(
    st,
    PROJECTS_ROOT,
    app_name=APP_NAME,
    page_name=PAGE_NAME,
)

# ============================================================
# 管理者チェック（admin gate）
# - cookie/JWT の再読込はしない（二重取得を避ける）
# - sub_session が admin_users に含まれるかで判定
# ============================================================
sub_admin = None

if not sub_session:
    st.error("ログインしていません。ポータルからログインしてください。")
    st.stop()

if not authh.is_admin(sub_session):
    st.error("🚫 このページは管理者のみアクセスできます。")
    st.caption("ヒント：管理者ユーザーに追加されているか settings.toml（admin_users）を確認してください。")
    st.stop()

sub_admin = sub_session

# ============================================================
# location（正本：command_station secrets.toml）
# ============================================================
try:
    loc = get_location_from_command_station_secrets(PROJECTS_ROOT)
except Exception as e:
    st.error(f"location 取得失敗：{e}")
    st.stop()

# ============================================================
# UI（テンプレ）
# ============================================================
left, right = st.columns([2, 1])

with left:
    st.title("♻️ 復元")

with right:
    st.success(f"✅ 管理者ログイン中: **{sub_admin}**")


subtitle("復元実行ページ")

# ------------------------------------------------------------
# ページ説明
# ------------------------------------------------------------
render_restore_page_intro()

# ------------------------------------------------------------
# 詳細説明
# ------------------------------------------------------------
render_restore_explanation(
    location=loc,
    projects_root=PROJECTS_ROOT,
)


st.caption(
    "復元元: "
    f"`<SSD>/aisv_Backups/{loc}/backups/<name>/latest/`"
)
st.caption(
    "復元先: "
    "`resolver で解決した現在の正本ディレクトリ`"
)

st.write(f"- location: **{loc}**")
st.write(f"- restore_root: `<SSD>/aisv_Backups/{loc}/backups/<name>/latest/`")

# ============================================================
# 復元先（正本）
# ============================================================
try:
    storages_dst = resolve_storages_root(PROJECTS_ROOT)
    auth_dst = resolve_auth_data_root(PROJECTS_ROOT)
    inbox_dst = resolve_inbox_root(PROJECTS_ROOT)

    archive_dst = resolve_storage_subdir_root_v2(PROJECTS_ROOT, subdir="Archive", role="main")
    db_dst = resolve_storage_subdir_root_v2(PROJECTS_ROOT, subdir="Databases", role="main")
except Exception as e:
    st.error(f"復元先パス解決に失敗しました：{e}")
    st.stop()

# ============================================================
# 実行中フラグ（セクション別）
# ============================================================
KEY_RUNNING_STORAGE = f"{PAGE_NAME}__running_storage"
KEY_RUNNING_AUTH = f"{PAGE_NAME}__running_auth"
KEY_RUNNING_INBOX = f"{PAGE_NAME}__running_inbox"
KEY_RUNNING_ARCHIVE = f"{PAGE_NAME}__running_archive"
KEY_RUNNING_DATABASES = f"{PAGE_NAME}__running_databases"

if KEY_RUNNING_STORAGE not in st.session_state:
    st.session_state[KEY_RUNNING_STORAGE] = False
if KEY_RUNNING_AUTH not in st.session_state:
    st.session_state[KEY_RUNNING_AUTH] = False
if KEY_RUNNING_INBOX not in st.session_state:
    st.session_state[KEY_RUNNING_INBOX] = False
if KEY_RUNNING_ARCHIVE not in st.session_state:
    st.session_state[KEY_RUNNING_ARCHIVE] = False
if KEY_RUNNING_DATABASES not in st.session_state:
    st.session_state[KEY_RUNNING_DATABASES] = False


def _any_running() -> bool:
    return bool(
        st.session_state[KEY_RUNNING_STORAGE]
        or st.session_state[KEY_RUNNING_AUTH]
        or st.session_state[KEY_RUNNING_INBOX]
        or st.session_state[KEY_RUNNING_ARCHIVE]
        or st.session_state[KEY_RUNNING_DATABASES]
    )


# ============================================================
# session state helper
# ============================================================
def _init_restore_state(name: str) -> dict[str, str]:
    keys = {
        "diff_result": f"{PAGE_NAME}__{name}__diff_result",
        "diff_source": f"{PAGE_NAME}__{name}__diff_source",
        "diff_dest": f"{PAGE_NAME}__{name}__diff_dest",
        "diff_target": f"{PAGE_NAME}__{name}__diff_target",
        "diff_role": f"{PAGE_NAME}__{name}__diff_role",
    }

    if keys["diff_result"] not in st.session_state:
        st.session_state[keys["diff_result"]] = None
    if keys["diff_source"] not in st.session_state:
        st.session_state[keys["diff_source"]] = ""
    if keys["diff_dest"] not in st.session_state:
        st.session_state[keys["diff_dest"]] = ""
    if keys["diff_target"] not in st.session_state:
        st.session_state[keys["diff_target"]] = ""
    if keys["diff_role"] not in st.session_state:
        st.session_state[keys["diff_role"]] = ""

    return keys


def _clear_restore_state(keys: dict[str, str]) -> None:
    st.session_state[keys["diff_result"]] = None
    st.session_state[keys["diff_source"]] = ""
    st.session_state[keys["diff_dest"]] = ""
    st.session_state[keys["diff_target"]] = ""
    st.session_state[keys["diff_role"]] = ""


# ============================================================
# SSD 判定（用途別）
# ============================================================
st.divider()
st.subheader("復元元SSD（用途別：接続中のみボタン表示）")


def _show_probe(title: str, probe_list) -> None:
    st.write(f"#### {title}")
    for r in probe_list:
        if r.path:
            st.success(f"✅ role={r.role}：接続中（{r.path}）")
        else:
            st.warning(f"⚠️ role={r.role}：{r.reason}")


probe_storage = probe_backup_mounts_by_purpose(PROJECTS_ROOT, purpose_key="storage", roles=("backup", "backup2"))
probe_inbox = probe_backup_mounts_by_purpose(PROJECTS_ROOT, purpose_key="inbox", roles=("backup", "backup2"))
probe_archive = probe_backup_mounts_by_purpose(PROJECTS_ROOT, purpose_key="archive", roles=("backup", "backup2"))
probe_databases = probe_backup_mounts_by_purpose(PROJECTS_ROOT, purpose_key="databases", roles=("backup", "backup2"))

_show_probe("storages/auth（purpose=storage）", probe_storage)
_show_probe("inbox（purpose=inbox）", probe_inbox)
_show_probe("archive（purpose=archive）", probe_archive)
_show_probe("databases（purpose=databases）", probe_databases)


# ============================================================
# 復元セクション共通処理
# ============================================================
def _render_restore_section(
    *,
    section_no: str,
    name: str,
    label: str,
    purpose_key: str,
    restore_to: Path,
    probe_list,
    running_key: str,
    caption: str,
) -> None:
    """
    復元対象1件分のセクションを表示する。

    処理：
    - 接続中SSDだけ差分確認ボタンを表示する。
    - SSD未接続でもページ全体は止めない。
    - 差分確認後のみ復元実行を許可する。
    """
    st.divider()
    st.subheader(f"{section_no} {label} 復元（backup latest → 正本）")

    if caption:
        st.caption(caption)

    st.write("復元対象：")
    st.write(f"- 復元元: `<SSD>/aisv_Backups/{loc}/backups/{name}/latest/`")
    st.write(f"- 復元先: `{restore_to}`")

    restore_to_ok = restore_to.exists()

    if not restore_to_ok:
        st.error(f"復元先の正本ディレクトリが存在しません: {restore_to}")
        return

    keys = _init_restore_state(name)

    enabled = [(r.role, r.path) for r in probe_list if r.path is not None]
    clicked_diff = None

    if not enabled:
        st.warning(f"（{label}）接続中の復元元SSDがありません。このセクションはスキップします。")
    else:
        cols = st.columns(len(enabled))

        for i, (role, mount) in enumerate(enabled):
            restore_from = build_backup_latest_path(
                mount=mount,
                location=loc,
                name=name,
            )

            with cols[i]:
                st.write(f"**role={role}**")
                st.caption(f"`{restore_from}`")

                restore_from_ok = restore_from.exists() and restore_from.is_dir()

                if restore_from_ok:
                    try:
                        backup_dt = datetime.fromtimestamp(restore_from.stat().st_mtime)
                        st.caption(f"latest更新: {backup_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    except Exception:
                        st.caption("latest更新: 取得不可")
                else:
                    st.warning("latest がありません")

                if st.button(
                    f"{role} から差分確認",
                    disabled=_any_running() or not restore_from_ok,
                    type="primary",
                    key=f"{PAGE_NAME}__btn_diff_{name}_{role}",
                ):
                    clicked_diff = (role, mount, restore_from)

    if clicked_diff:
        role, mount, restore_from = clicked_diff

        st.session_state[running_key] = True
        try:
            diff_cmd = build_diff_cmd(
                restore_from=restore_from,
                restore_to=restore_to,
            )
            diff_result = sh(diff_cmd)

            st.session_state[keys["diff_result"]] = run_result_to_dict(diff_result)
            st.session_state[keys["diff_source"]] = str(restore_from)
            st.session_state[keys["diff_dest"]] = str(restore_to)
            st.session_state[keys["diff_target"]] = str(name)
            st.session_state[keys["diff_role"]] = str(role)

        finally:
            st.session_state[running_key] = False

    diff_result = run_result_from_dict(st.session_state.get(keys["diff_result"]))

    if diff_result is None:
        st.info(f"（{label}）先に接続中SSDから差分確認を実行してください。")
        return

    current_source = st.session_state.get(keys["diff_source"], "")
    current_dest = st.session_state.get(keys["diff_dest"], "")
    current_target = st.session_state.get(keys["diff_target"], "")
    current_role = st.session_state.get(keys["diff_role"], "")

    st.write(f"#### {label} / 差分確認結果")
    st.caption(f"差分確認済み role: `{current_role}`")

    st.caption("実行コマンド")
    st.code(fmt_cmd(diff_result.cmd), language="bash")

    if diff_result.ok:
        st.success(f"差分確認は正常終了しました。returncode={diff_result.returncode}")
    else:
        st.error(f"差分確認に失敗しました。returncode={diff_result.returncode}")

    if diff_result.stderr.strip():
        st.caption("stderr")
        st.code(diff_result.stderr, language="text")

    if not diff_result.ok:
        st.error(f"（{label}）差分確認に失敗しているため、復元は実行できません。")
        return

    if has_no_diff(diff_result):
        st.success(f"（{label}）差分はありません。復元先は latest と同じ状態です。")
    else:
        render_rsync_diff_summary(diff_result)

        diff_text = build_diff_download_text(
            result=diff_result,
            restore_from=Path(current_source),
            restore_to=Path(current_dest),
            target_label=label,
        )

        st.download_button(
            label=f"（{label}）復元差分テキストをダウンロード",
            data=diff_text.encode("utf-8"),
            file_name=f"restore_diff_{name}_{current_role}.txt",
            mime="text/plain",
            key=f"{PAGE_NAME}__download_restore_diff_{name}",
        )

    can_restore = bool(
        restore_to_ok
        and diff_result.ok
        and current_source
        and current_dest == str(restore_to)
        and current_target == str(name)
    )

    st.write(f"#### {label} / 確認後に復元")

    if not can_restore:
        st.info(f"（{label}）現在の復元元・復元先で差分確認を実行してください。")
        return

    st.error(
        f"（{label}）復元を実行すると、復元先の正本ディレクトリは "
        "バックアップ latest と同じ状態になります。"
    )

    confirm_restore = st.checkbox(
        f"（{label}）差分を確認しました。正本をバックアップ latest の状態へ復元します。",
        value=False,
        key=f"{PAGE_NAME}__confirm_restore_{name}",
    )

    typed = st.text_input(
        f"（{label}）確認のため RESTORE と入力してください",
        value="",
        key=f"{PAGE_NAME}__typed_restore_{name}",
    )

    if st.button(
        f"（{label}）復元を実行",
        type="primary",
        disabled=_any_running() or not (confirm_restore and typed == "RESTORE"),
        key=f"{PAGE_NAME}__btn_restore_{name}",
    ):
        st.session_state[running_key] = True
        try:
            restore_cmd = build_restore_cmd(
                restore_from=Path(current_source),
                restore_to=restore_to,
            )

            result = sh(restore_cmd)

            st.write(f"#### {label} / 復元実行結果")
            render_rsync_result("復元結果", result)

            if result.ok:
                st.success(f"（{label}）復元が完了しました。")
                _clear_restore_state(keys)
            else:
                st.error(f"（{label}）復元に失敗しました。stderr を確認してください。")

        finally:
            st.session_state[running_key] = False


# ============================================================
# セクション① storages（purpose=storage）
# ============================================================
_render_restore_section(
    section_no="①",
    name="storages",
    label="storages",
    purpose_key="storage",
    restore_to=storages_dst,
    probe_list=probe_storage,
    running_key=KEY_RUNNING_STORAGE,
    caption="Storages 正本へ復元します。",
)

# ============================================================
# セクション② auth（purpose=storage）
# ============================================================
_render_restore_section(
    section_no="②",
    name="auth",
    label="auth",
    purpose_key="storage",
    restore_to=auth_dst,
    probe_list=probe_storage,
    running_key=KEY_RUNNING_AUTH,
    caption="認証データ正本へ復元します。",
)

# ============================================================
# セクション③ inbox（purpose=inbox）
# ============================================================
_render_restore_section(
    section_no="③",
    name="inbox",
    label="inbox",
    purpose_key="inbox",
    restore_to=inbox_dst,
    probe_list=probe_inbox,
    running_key=KEY_RUNNING_INBOX,
    caption="InBoxStorages 正本へ復元します。",
)

# ============================================================
# セクション④ archive（purpose=archive）
# ============================================================
_render_restore_section(
    section_no="④",
    name="archive",
    label="archive",
    purpose_key="archive",
    restore_to=archive_dst,
    probe_list=probe_archive,
    running_key=KEY_RUNNING_ARCHIVE,
    caption="Archive 正本へ復元します。",
)

# ============================================================
# セクション⑤ databases（purpose=databases）
# ============================================================
_render_restore_section(
    section_no="⑤",
    name="databases",
    label="databases",
    purpose_key="databases",
    restore_to=db_dst,
    probe_list=probe_databases,
    running_key=KEY_RUNNING_DATABASES,
    caption="Databases 正本へ復元します。",
)

# ============================================================
# フッタ
# ============================================================
st.divider()
st.caption(
    f"※ storages / auth / inbox / archive / databases は "
    f"aisv_Backups/{loc}/backups/<name>/latest/ から用途別に復元されます。"
)