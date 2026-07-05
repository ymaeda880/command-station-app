# -*- coding: utf-8 -*-
# command_station_app/pages/120_バックアップ.py
# ============================================================
# 💾 バックアップ（用途別：storages/auth・inbox・archive・databases）
#
# 目的：
# - 正本SSD（main）上のデータ（storages/auth/inbox/archive/databases）を、
#   バックアップSSD（backup / backup2：物理的に別）へ rsync で保存する。
# - バックアップは用途別に分離して保存する
#   （aisv_Backups/<location>/backups/<name>/...）。
#
# 保存先（共通）：
#   <バックアップSSDのマウントポイント>/aisv_Backups/<location>/backups/<name>/{latest,daily,logs}
#
# location の例：
# - home
# - prec
# - portable
#
# バックアップ方式：
# - latest: 完全ミラー（--delete）
# - daily : スナップショット（任意で --link-dest による差分節約）
#
# テンプレ準拠：
# - page_session_heartbeat を必ず実行（sub_session を真実として扱う）
# - バナー表示（app settings.toml の ui_banner_key）
# - 管理者チェック：sub_session が admin_users に含まれるかで判定（cookie/JWT 再読込なし）
# - use_container_width 不使用
# - st.form 不使用
# - st.button()/st.download_button() に width 引数を使わない
#
# SSD構成ポリシー（容量に応じて構成を選択）：
#
# 【ケース①】容量が小さい場合（単一バックアップSSD構成：管理が容易）
#
# /Volumes/MainSSD
# ├── Storages
# ├── InBoxStorages
# ├── Archive
# └── Databases
#
# /Volumes/BackupSSD
# └── aisv_Backups/prec/backups
#     ├── storages
#     ├── auth
#     ├── inbox
#     ├── archive
#     └── databases
#
# ※ location ごとに分離
#   例：
#   - aisv_Backups/home/backups/...
#   - aisv_Backups/prec/backups/...
#   - aisv_Backups/portable/backups/...
#
# 【ケース②】容量が大きい場合（用途別バックアップSSD構成：分散）
#
# /Volumes/MainSSD
# ├── Storages
# ├── InBoxStorages
# ├── Archive
# └── Databases
#
# /Volumes/BackupSSD_Storage  → aisv_Backups/<location>/backups/{storages,auth}
# /Volumes/BackupSSD_Inbox    → aisv_Backups/<location>/backups/inbox
# /Volumes/BackupSSD_Archive  → aisv_Backups/<location>/backups/archive
# /Volumes/BackupSSD_Database → aisv_Backups/<location>/backups/databases
# ============================================================

from __future__ import annotations

# ============================================================
# imports（stdlib）
# ============================================================
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import shlex
import subprocess
import sys

# ============================================================
# imports（3rd party）
# ============================================================
import streamlit as st

# ============================================================
# page config（最初に1回だけ）
# ============================================================
st.set_page_config(
    page_title="バックアップ（用途別）",
    page_icon="💾",
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
from common_lib.sessions.page_entry import page_session_heartbeat
from common_lib.env.config import get_ui_banner_key_from_app_settings
from common_lib.ui.banner_lines import render_banner_line_by_key
from common_lib.ui.ui_basics import subtitle
import common_lib.auth.auth_helpers as authh  # is_admin / get_admin_users 等

# ============================================================
# common_lib（env / storage / auth paths）
# ============================================================
from common_lib.env.config import get_location_from_command_station_secrets
from common_lib.storage.storages_config import resolve_storages_root
from common_lib.storage.inbox_config import resolve_inbox_root
from common_lib.storage.external_mount_probe import probe_backup_mounts_by_purpose
from common_lib.storage.external_ssd_root import resolve_storage_subdir_root_v2
from common_lib.auth.paths import resolve_auth_data_root

# ============================================================
# app lib
# ============================================================
from lib.backup.explanation import render_backup_explanation

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
    st.title("💾 バックアップ（用途別：storages/auth・inbox・archive・databases）")
    st.caption(
        f"バックアップはバックアップSSD側の "
        f"aisv_Backups/{loc}/backups/ に用途別で分離して保存します。"
    )

with right:
    st.success(f"✅ 管理者ログイン中: **{sub_admin}**")

subtitle("バックアップ実行ページ")

render_backup_explanation()
st.caption(
    "保存先: "
    f"`<SSD>/aisv_Backups/{loc}/backups/<name>/{{latest,daily,logs}}`"
    "（latestは--delete、dailyは任意で--link-dest）"
)

st.write(f"- location: **{loc}**")
st.write(f"- projects_root: `{PROJECTS_ROOT}`")
st.write(f"- app_name: `{APP_NAME}`")
st.write(f"- page_name: `{PAGE_NAME}`")
st.write(f"- backup_root: `<SSD>/aisv_Backups/{loc}/backups/`")

# ============================================================
# バックアップ元（正本）
# ============================================================
storages_src = resolve_storages_root(PROJECTS_ROOT)
auth_src = resolve_auth_data_root(PROJECTS_ROOT)
inbox_src = resolve_inbox_root(PROJECTS_ROOT)

archive_src = resolve_storage_subdir_root_v2(PROJECTS_ROOT, subdir="Archive", role="main")
db_src = resolve_storage_subdir_root_v2(PROJECTS_ROOT, subdir="Databases", role="main")

for p in (storages_src, auth_src, inbox_src, archive_src, db_src):
    if not p.exists():
        st.error(f"バックアップ元が存在しません: {p}")
        st.stop()

# ============================================================
# 共通ユーティリティ（rsync）
# ============================================================
@dataclass
class RunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]


def sh(cmd: list[str]) -> RunResult:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return RunResult(
        ok=(p.returncode == 0),
        returncode=p.returncode,
        stdout=p.stdout or "",
        stderr=p.stderr or "",
        cmd=cmd,
    )


def fmt_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(x) for x in cmd)


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def backup_sets(
    *,
    mount: Path,
    location: str,
    backup_sets: list[dict],
    use_link_dest: bool,
    dry_run: bool,
) -> tuple[bool, str | None]:
    """
    指定した backup_sets を、指定 mount に対して latest + daily で実行する。
    失敗したら (False, reason) を返す。成功なら (True, None)。
    """
    root = mount / "aisv_Backups" / str(location) / "backups"
    ensure_dir(root)

    rsync_base = ["rsync", "-a"]
    if dry_run:
        rsync_base.append("--dry-run")

    for s in backup_sets:
        name = str(s["name"])
        src: Path = s["src"]

        base = root / name
        latest = base / "latest"
        daily = base / "daily" / now_stamp()
        logs = base / "logs"

        ensure_dir(latest)
        ensure_dir(daily)
        ensure_dir(logs)

        cmd_latest = rsync_base + ["--delete", f"{src}/", f"{latest}/"]
        st.write(f"#### {name} / latest")
        st.code(fmt_cmd(cmd_latest), language="bash")
        r1 = sh(cmd_latest)
        if not r1.ok:
            st.error(f"{name}: latest 失敗（returncode={r1.returncode}）")
            if r1.stderr:
                st.text(r1.stderr)
            return False, f"{name}: latest failed"

        cmd_daily = rsync_base.copy()
        if use_link_dest:
            cmd_daily += ["--link-dest", str(latest)]
        cmd_daily += [f"{src}/", f"{daily}/"]

        st.write(f"#### {name} / daily")
        st.code(fmt_cmd(cmd_daily), language="bash")
        r2 = sh(cmd_daily)
        if not r2.ok:
            st.error(f"{name}: daily 失敗（returncode={r2.returncode}）")
            if r2.stderr:
                st.text(r2.stderr)
            return False, f"{name}: daily failed"

    return True, None


# ============================================================
# 実行中フラグ（セクション別）
# ============================================================
KEY_RUNNING_STORAGE = f"{PAGE_NAME}__running_storage"
KEY_RUNNING_INBOX = f"{PAGE_NAME}__running_inbox"
KEY_RUNNING_ARCHIVE = f"{PAGE_NAME}__running_archive"
KEY_RUNNING_DATABASES = f"{PAGE_NAME}__running_databases"

if KEY_RUNNING_STORAGE not in st.session_state:
    st.session_state[KEY_RUNNING_STORAGE] = False
if KEY_RUNNING_INBOX not in st.session_state:
    st.session_state[KEY_RUNNING_INBOX] = False
if KEY_RUNNING_ARCHIVE not in st.session_state:
    st.session_state[KEY_RUNNING_ARCHIVE] = False
if KEY_RUNNING_DATABASES not in st.session_state:
    st.session_state[KEY_RUNNING_DATABASES] = False


def _any_running() -> bool:
    return bool(
        st.session_state[KEY_RUNNING_STORAGE]
        or st.session_state[KEY_RUNNING_INBOX]
        or st.session_state[KEY_RUNNING_ARCHIVE]
        or st.session_state[KEY_RUNNING_DATABASES]
    )


# ============================================================
# SSD 判定（用途別：B確定）— probe を完全統一
# ============================================================
st.divider()
st.subheader("バックアップ先SSD（用途別：接続中のみボタン表示）")


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
# セクション① storages + auth（purpose=storage）
# ============================================================
st.divider()
st.subheader("① storages + auth バックアップ（latest + daily）")
st.caption("auth：<projects_root>/auth_portal_project/auth_portal_app/data")

use_link_dest_sa = st.checkbox(
    "（storages+auth）daily は差分（--link-dest）で節約",
    value=True,
    key=f"{PAGE_NAME}__use_link_dest_sa",
)
dry_run_sa = st.checkbox(
    "（storages+auth）Dry-run（コピーせず表示のみ）",
    value=False,
    key=f"{PAGE_NAME}__dry_run_sa",
)
confirm_sa = st.checkbox(
    "（storages+auth）確認：選択したSSDに latest（--delete）と daily を作成します（不可逆）",
    value=False,
    key=f"{PAGE_NAME}__confirm_sa",
)

st.write("バックアップ対象：")
st.write(f"- storages: `{storages_src}`")
st.write(f"- auth    : `{auth_src}`")


enabled_sa = [(r.role, r.path) for r in probe_storage if r.path is not None]
clicked_sa: Optional[Tuple[str, Path]] = None

if not enabled_sa:
    st.warning("（storages+auth）接続中のバックアップ先SSDがありません。このセクションはスキップします。")
else:
    cols_sa = st.columns(len(enabled_sa))

    for i, (role, mount) in enumerate(enabled_sa):
        with cols_sa[i]:
            if st.button(
                f"{role} へ（storages+auth）",
                disabled=_any_running(),
                type="primary",
                key=f"{PAGE_NAME}__btn_sa_{role}",
            ):
                clicked_sa = (role, mount)


if clicked_sa:
    role, mount = clicked_sa
    if not confirm_sa:
        st.error("（storages+auth）確認チェックをオンにしてください")
    else:
        st.session_state[KEY_RUNNING_STORAGE] = True
        try:
            ok, reason = backup_sets(
                mount=mount,
                location=loc,
                backup_sets=[
                    {"name": "storages", "src": storages_src},
                    {"name": "auth", "src": auth_src},
                ],
                use_link_dest=bool(use_link_dest_sa),
                dry_run=bool(dry_run_sa),
            )
            if ok:
                st.success(f"（storages+auth）バックアップが完了しました（role={role}, mount={mount}）")
            else:
                st.error(f"（storages+auth）バックアップ失敗：{reason}")
        finally:
            st.session_state[KEY_RUNNING_STORAGE] = False

# ============================================================
# セクション② inbox（purpose=inbox）
# ============================================================
st.divider()
st.subheader("② inbox バックアップ（latest + daily）")

use_link_dest_in = st.checkbox(
    "（inbox）daily は差分（--link-dest）で節約",
    value=True,
    key=f"{PAGE_NAME}__use_link_dest_in",
)
dry_run_in = st.checkbox(
    "（inbox）Dry-run（コピーせず表示のみ）",
    value=False,
    key=f"{PAGE_NAME}__dry_run_in",
)
confirm_in = st.checkbox(
    "（inbox）確認：選択したSSDに latest（--delete）と daily を作成します（不可逆）",
    value=False,
    key=f"{PAGE_NAME}__confirm_in",
)

st.write("バックアップ対象：")
st.write(f"- inbox: `{inbox_src}`")


enabled_in = [(r.role, r.path) for r in probe_inbox if r.path is not None]
clicked_in: Optional[Tuple[str, Path]] = None

if not enabled_in:
    st.warning("（inbox）接続中のバックアップ先SSDがありません。このセクションはスキップします。")
else:
    cols_in = st.columns(len(enabled_in))

    for i, (role, mount) in enumerate(enabled_in):
        with cols_in[i]:
            if st.button(
                f"{role} へ（inbox）",
                disabled=_any_running(),
                type="primary",
                key=f"{PAGE_NAME}__btn_in_{role}",
            ):
                clicked_in = (role, mount)

if clicked_in:
    role, mount = clicked_in
    if not confirm_in:
        st.error("（inbox）確認チェックをオンにしてください")
    else:
        st.session_state[KEY_RUNNING_INBOX] = True
        try:
            ok, reason = backup_sets(
                mount=mount,
                location=loc,
                backup_sets=[
                    {"name": "inbox", "src": inbox_src},
                ],
                use_link_dest=bool(use_link_dest_in),
                dry_run=bool(dry_run_in),
            )
            if ok:
                st.success(f"（inbox）バックアップが完了しました（role={role}, mount={mount}）")
            else:
                st.error(f"（inbox）バックアップ失敗：{reason}")
        finally:
            st.session_state[KEY_RUNNING_INBOX] = False

# ============================================================
# セクション③ archive（purpose=archive）
# ============================================================
st.divider()
st.subheader("③ archive バックアップ（latest + daily）")

use_link_dest_ar = st.checkbox(
    "（archive）daily は差分（--link-dest）で節約",
    value=True,
    key=f"{PAGE_NAME}__use_link_dest_ar",
)
dry_run_ar = st.checkbox(
    "（archive）Dry-run（コピーせず表示のみ）",
    value=False,
    key=f"{PAGE_NAME}__dry_run_ar",
)
confirm_ar = st.checkbox(
    "（archive）確認：選択したSSDに latest（--delete）と daily を作成します（不可逆）",
    value=False,
    key=f"{PAGE_NAME}__confirm_ar",
)

st.write("バックアップ対象：")
st.write(f"- archive: `{archive_src}`")

enabled_ar = [(r.role, r.path) for r in probe_archive if r.path is not None]
clicked_ar: Optional[Tuple[str, Path]] = None

if not enabled_ar:
    st.warning("（archive）接続中のバックアップ先SSDがありません。このセクションはスキップします。")
else:
    cols_ar = st.columns(len(enabled_ar))

    for i, (role, mount) in enumerate(enabled_ar):
        with cols_ar[i]:
            if st.button(
                f"{role} へ（archive）",
                disabled=_any_running(),
                type="primary",
                key=f"{PAGE_NAME}__btn_ar_{role}",
            ):
                clicked_ar = (role, mount)

if clicked_ar:
    role, mount = clicked_ar
    if not confirm_ar:
        st.error("（archive）確認チェックをオンにしてください")
    else:
        st.session_state[KEY_RUNNING_ARCHIVE] = True
        try:
            ok, reason = backup_sets(
                mount=mount,
                location=loc,
                backup_sets=[
                    {"name": "archive", "src": archive_src},
                ],
                use_link_dest=bool(use_link_dest_ar),
                dry_run=bool(dry_run_ar),
            )
            if ok:
                st.success(f"（archive）バックアップが完了しました（role={role}, mount={mount}）")
            else:
                st.error(f"（archive）バックアップ失敗：{reason}")
        finally:
            st.session_state[KEY_RUNNING_ARCHIVE] = False

# ============================================================
# セクション④ databases（purpose=databases）
# ============================================================
st.divider()
st.subheader("④ databases バックアップ（latest + daily）")

use_link_dest_db = st.checkbox(
    "（databases）daily は差分（--link-dest）で節約",
    value=True,
    key=f"{PAGE_NAME}__use_link_dest_db",
)
dry_run_db = st.checkbox(
    "（databases）Dry-run（コピーせず表示のみ）",
    value=False,
    key=f"{PAGE_NAME}__dry_run_db",
)
confirm_db = st.checkbox(
    "（databases）確認：選択したSSDに latest（--delete）と daily を作成します（不可逆）",
    value=False,
    key=f"{PAGE_NAME}__confirm_db",
)

st.write("バックアップ対象：")
st.write(f"- databases: `{db_src}`")

enabled_db = [(r.role, r.path) for r in probe_databases if r.path is not None]
clicked_db: Optional[Tuple[str, Path]] = None

if not enabled_db:
    st.warning("（databases）接続中のバックアップ先SSDがありません。このセクションはスキップします。")
else:
    cols_db = st.columns(len(enabled_db))

    for i, (role, mount) in enumerate(enabled_db):
        with cols_db[i]:
            if st.button(
                f"{role} へ（databases）",
                disabled=_any_running(),
                type="primary",
                key=f"{PAGE_NAME}__btn_db_{role}",
            ):
                clicked_db = (role, mount)

if clicked_db:
    role, mount = clicked_db
    if not confirm_db:
        st.error("（databases）確認チェックをオンにしてください")
    else:
        st.session_state[KEY_RUNNING_DATABASES] = True
        try:
            ok, reason = backup_sets(
                mount=mount,
                location=loc,
                backup_sets=[
                    {"name": "databases", "src": db_src},
                ],
                use_link_dest=bool(use_link_dest_db),
                dry_run=bool(dry_run_db),
            )
            if ok:
                st.success(f"（databases）バックアップが完了しました（role={role}, mount={mount}）")
            else:
                st.error(f"（databases）バックアップ失敗：{reason}")
        finally:
            st.session_state[KEY_RUNNING_DATABASES] = False

# ============================================================
# フッタ
# ============================================================
st.caption(
    f"※ storages / auth / inbox / archive / databases は "
    f"aisv_Backups/{loc}/backups/ に用途別で完全に分離して保存されます。"
)