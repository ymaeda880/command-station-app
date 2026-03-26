# -*- coding: utf-8 -*-
# command_station_app/pages/120_バックアップ.py
"""
Storage / 認証データ / Inbox / Archive / Databases バックアップ用 Streamlit ページ（common_lib 正本運用）

- location は command_station secrets.toml から取得（common_lib）
- Storages の場所は storages_config の正本 API を使用
- Inbox の場所は inbox_config の正本 API を使用
- Archive / Databases は storage.toml + secrets.toml(mode) の正本 resolver を使用（main）
- バックアップ先SSDは「用途別キー（B確定）」で probe する（停止しない）

このページでは、
① storages + auth のバックアップ
② inbox のバックアップ
③ archive のバックアップ
④ databases のバックアップ
を「別セクション」「別ボタン」「別確認チェック」で実行する。

保存先（共通）：
  <SSD物理root>/aisv_Backups/backups/<name>/{latest,daily,logs}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sys
from pathlib import Path
import shlex
import subprocess

import streamlit as st

# ============================================================
# common_lib を import 可能にする（projects を sys.path に追加）
# ============================================================
_THIS = Path(__file__).resolve()
PROJECTS_ROOT = _THIS.parents[3]  # .../projects

if str(PROJECTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECTS_ROOT))

# ============================================================
# common_lib
# ============================================================
from common_lib.env.config import get_location_from_command_station_secrets
from common_lib.storage.storages_config import resolve_storages_root
from common_lib.storage.inbox_config import resolve_inbox_root
from common_lib.storage.external_mount_probe import (
    probe_backup_mounts,                 # 互換：Storages用途（purpose_key="storage"）
    probe_backup_mounts_by_purpose,      # 新：用途別（B確定）
)
from common_lib.storage.external_ssd_root import resolve_storage_subdir_root
from common_lib.auth.paths import resolve_auth_data_root

from lib.backup.explanation import render_backup_explanation


# ============================================================
# 共通ユーティリティ
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
    role: str,
    mount: Path,
    backup_sets: list[dict],
    use_link_dest: bool,
    dry_run: bool,
) -> tuple[bool, str | None]:
    """
    指定した backup_sets を、指定 mount に対して latest + daily で実行する。
    失敗したら (False, reason) を返す。成功なら (True, None)。
    """
    root = mount / "aisv_Backups" / "backups"
    ensure_dir(root)

    rsync_base = ["rsync", "-a"]
    if dry_run:
        rsync_base.append("--dry-run")

    for s in backup_sets:
        name = s["name"]
        src: Path = s["src"]

        base = root / name
        latest = base / "latest"
        daily = base / "daily" / now_stamp()
        logs = base / "logs"

        ensure_dir(latest)
        ensure_dir(daily)
        ensure_dir(logs)

        # latest（完全ミラー：--delete）
        cmd_latest = rsync_base + ["--delete", f"{src}/", f"{latest}/"]
        st.write(f"#### {name} / latest")
        st.code(fmt_cmd(cmd_latest), language="bash")
        r1 = sh(cmd_latest)
        if not r1.ok:
            st.error(f"{name}: latest 失敗")
            return False, f"{name}: latest failed"

        # daily（スナップショット）
        cmd_daily = rsync_base.copy()
        if use_link_dest:
            cmd_daily += ["--link-dest", str(latest)]
        cmd_daily += [f"{src}/", f"{daily}/"]

        st.write(f"#### {name} / daily")
        st.code(fmt_cmd(cmd_daily), language="bash")
        r2 = sh(cmd_daily)
        if not r2.ok:
            st.error(f"{name}: daily 失敗")
            return False, f"{name}: daily failed"

    return True, None


# ============================================================
# UI
# ============================================================
st.set_page_config(page_title="Storageバックアップ", page_icon="💾", layout="centered")
st.title("💾 バックアップ（用途別：storages/auth・inbox・archive・databases）")

render_backup_explanation()
st.caption("SSD内 aisv_Backups/backups/ に storages / auth / inbox / archive / databases を分離して保存します。")

# ============================================================
# location（正本：command_station secrets.toml）
# ============================================================
try:
    loc = get_location_from_command_station_secrets(PROJECTS_ROOT)
except Exception as e:
    st.error(f"location 取得失敗：{e}")
    st.stop()

st.write(f"- location: **{loc}**")
st.write(f"- PROJECTS_ROOT: `{PROJECTS_ROOT}`")

# ============================================================
# バックアップ元（正本）
# ============================================================
storages_src = resolve_storages_root(PROJECTS_ROOT)
auth_src = resolve_auth_data_root(PROJECTS_ROOT)
inbox_src = resolve_inbox_root(PROJECTS_ROOT)

# Archive / Databases は main の internal/external(mode) を尊重して解決
archive_src = resolve_storage_subdir_root(PROJECTS_ROOT, subdir="Archive", role="main")
db_src = resolve_storage_subdir_root(PROJECTS_ROOT, subdir="Databases", role="main")

# 存在チェック（ここは正本なので止めてOK）
for p in (storages_src, auth_src, inbox_src, archive_src, db_src):
    if not p.exists():
        st.error(f"バックアップ元が存在しません: {p}")
        st.stop()

# ============================================================
# 実行中フラグ（セクション別）
# ============================================================
if "backup_running_storage" not in st.session_state:
    st.session_state["backup_running_storage"] = False
if "backup_running_inbox" not in st.session_state:
    st.session_state["backup_running_inbox"] = False
if "backup_running_archive" not in st.session_state:
    st.session_state["backup_running_archive"] = False
if "backup_running_databases" not in st.session_state:
    st.session_state["backup_running_databases"] = False


def _any_running() -> bool:
    return bool(
        st.session_state["backup_running_storage"]
        or st.session_state["backup_running_inbox"]
        or st.session_state["backup_running_archive"]
        or st.session_state["backup_running_databases"]
    )


# ============================================================
# SSD 判定（用途別：B確定）
# ============================================================
st.divider()
st.write("### バックアップ先SSD（用途別：接続中のみボタン表示）")

def _show_probe(title: str, probe_list) -> None:
    st.write(f"#### {title}")
    for r in probe_list:
        if r.path:
            st.success(f"✅ role={r.role}：接続中（{r.path}）")
        else:
            st.warning(f"⚠️ role={r.role}：{r.reason}")

probe_storage = probe_backup_mounts(PROJECTS_ROOT, roles=("backup", "backup2"))
probe_inbox = probe_backup_mounts_by_purpose(PROJECTS_ROOT, purpose_key="inbox", roles=("backup", "backup2"))
probe_archive = probe_backup_mounts_by_purpose(PROJECTS_ROOT, purpose_key="archive", roles=("backup", "backup2"))
probe_databases = probe_backup_mounts_by_purpose(PROJECTS_ROOT, purpose_key="databases", roles=("backup", "backup2"))

_show_probe("storages/auth（purpose=storage）", probe_storage)
_show_probe("inbox（purpose=inbox）", probe_inbox)
_show_probe("archive（purpose=archive）", probe_archive)
_show_probe("databases（purpose=databases）", probe_databases)

# ============================================================
# セクション① storages + auth（保存先は storages の用途別SSDにまとめる）
# ============================================================
st.divider()
st.subheader("① storages + auth バックアップ（latest + daily）")

use_link_dest_sa = st.checkbox("（storages+auth）daily は差分（--link-dest）で節約", value=True, key="use_link_dest_sa")
dry_run_sa = st.checkbox("（storages+auth）Dry-run（コピーせず表示のみ）", value=False, key="dry_run_sa")
confirm_sa = st.checkbox(
    "（storages+auth）確認：選択したSSDに latest（--delete）と daily を作成します（不可逆）",
    value=False,
    key="confirm_sa",
)

st.write("バックアップ対象：")
st.write(f"- storages: `{storages_src}`")
st.write(f"- auth    : `{auth_src}`")

enabled_sa = [(r.role, r.path) for r in probe_storage if r.path is not None]
if not enabled_sa:
    st.error("（storages+auth）接続中のバックアップ先SSDがありません")
    st.stop()

cols_sa = st.columns(len(enabled_sa))
clicked_sa: tuple[str, Path] | None = None

for i, (role, mount) in enumerate(enabled_sa):
    with cols_sa[i]:
        disabled = _any_running()
        if st.button(f"{role} へ（storages+auth）", disabled=disabled, type="primary", key=f"btn_sa_{role}"):
            clicked_sa = (role, mount)

if clicked_sa:
    role, mount = clicked_sa
    if not confirm_sa:
        st.error("（storages+auth）確認チェックをオンにしてください")
    else:
        st.session_state["backup_running_storage"] = True
        try:
            ok, reason = backup_sets(
                role=role,
                mount=mount,
                backup_sets=[
                    {"name": "storages", "src": storages_src},
                    {"name": "auth", "src": auth_src},
                ],
                use_link_dest=use_link_dest_sa,
                dry_run=dry_run_sa,
            )
            if ok:
                st.success("（storages+auth）バックアップが完了しました")
            else:
                st.error(f"（storages+auth）バックアップ失敗：{reason}")
        finally:
            st.session_state["backup_running_storage"] = False


# ============================================================
# セクション② inbox（用途別SSD）
# ============================================================
st.divider()
st.subheader("② inbox バックアップ（latest + daily）")

use_link_dest_in = st.checkbox("（inbox）daily は差分（--link-dest）で節約", value=True, key="use_link_dest_in")
dry_run_in = st.checkbox("（inbox）Dry-run（コピーせず表示のみ）", value=False, key="dry_run_in")
confirm_in = st.checkbox(
    "（inbox）確認：選択したSSDに latest（--delete）と daily を作成します（不可逆）",
    value=False,
    key="confirm_in",
)

st.write("バックアップ対象：")
st.write(f"- inbox: `{inbox_src}`")

enabled_in = [(r.role, r.path) for r in probe_inbox if r.path is not None]
if not enabled_in:
    st.error("（inbox）接続中のバックアップ先SSDがありません")
    st.stop()

cols_in = st.columns(len(enabled_in))
clicked_in: tuple[str, Path] | None = None

for i, (role, mount) in enumerate(enabled_in):
    with cols_in[i]:
        disabled = _any_running()
        if st.button(f"{role} へ（inbox）", disabled=disabled, type="primary", key=f"btn_in_{role}"):
            clicked_in = (role, mount)

if clicked_in:
    role, mount = clicked_in
    if not confirm_in:
        st.error("（inbox）確認チェックをオンにしてください")
    else:
        st.session_state["backup_running_inbox"] = True
        try:
            ok, reason = backup_sets(
                role=role,
                mount=mount,
                backup_sets=[
                    {"name": "inbox", "src": inbox_src},
                ],
                use_link_dest=use_link_dest_in,
                dry_run=dry_run_in,
            )
            if ok:
                st.success("（inbox）バックアップが完了しました")
            else:
                st.error(f"（inbox）バックアップ失敗：{reason}")
        finally:
            st.session_state["backup_running_inbox"] = False


# ============================================================
# セクション③ archive（用途別SSD）
# ============================================================
st.divider()
st.subheader("③ archive バックアップ（latest + daily）")

use_link_dest_ar = st.checkbox("（archive）daily は差分（--link-dest）で節約", value=True, key="use_link_dest_ar")
dry_run_ar = st.checkbox("（archive）Dry-run（コピーせず表示のみ）", value=False, key="dry_run_ar")
confirm_ar = st.checkbox(
    "（archive）確認：選択したSSDに latest（--delete）と daily を作成します（不可逆）",
    value=False,
    key="confirm_ar",
)

st.write("バックアップ対象：")
st.write(f"- archive: `{archive_src}`")

enabled_ar = [(r.role, r.path) for r in probe_archive if r.path is not None]
if not enabled_ar:
    st.error("（archive）接続中のバックアップ先SSDがありません")
    st.stop()

cols_ar = st.columns(len(enabled_ar))
clicked_ar: tuple[str, Path] | None = None

for i, (role, mount) in enumerate(enabled_ar):
    with cols_ar[i]:
        disabled = _any_running()
        if st.button(f"{role} へ（archive）", disabled=disabled, type="primary", key=f"btn_ar_{role}"):
            clicked_ar = (role, mount)

if clicked_ar:
    role, mount = clicked_ar
    if not confirm_ar:
        st.error("（archive）確認チェックをオンにしてください")
    else:
        st.session_state["backup_running_archive"] = True
        try:
            ok, reason = backup_sets(
                role=role,
                mount=mount,
                backup_sets=[
                    {"name": "archive", "src": archive_src},
                ],
                use_link_dest=use_link_dest_ar,
                dry_run=dry_run_ar,
            )
            if ok:
                st.success("（archive）バックアップが完了しました")
            else:
                st.error(f"（archive）バックアップ失敗：{reason}")
        finally:
            st.session_state["backup_running_archive"] = False


# ============================================================
# セクション④ databases（用途別SSD）
# ============================================================
st.divider()
st.subheader("④ databases バックアップ（latest + daily）")

use_link_dest_db = st.checkbox("（databases）daily は差分（--link-dest）で節約", value=True, key="use_link_dest_db")
dry_run_db = st.checkbox("（databases）Dry-run（コピーせず表示のみ）", value=False, key="dry_run_db")
confirm_db = st.checkbox(
    "（databases）確認：選択したSSDに latest（--delete）と daily を作成します（不可逆）",
    value=False,
    key="confirm_db",
)

st.write("バックアップ対象：")
st.write(f"- databases: `{db_src}`")

enabled_db = [(r.role, r.path) for r in probe_databases if r.path is not None]
if not enabled_db:
    st.error("（databases）接続中のバックアップ先SSDがありません")
    st.stop()

cols_db = st.columns(len(enabled_db))
clicked_db: tuple[str, Path] | None = None

for i, (role, mount) in enumerate(enabled_db):
    with cols_db[i]:
        disabled = _any_running()
        if st.button(f"{role} へ（databases）", disabled=disabled, type="primary", key=f"btn_db_{role}"):
            clicked_db = (role, mount)

if clicked_db:
    role, mount = clicked_db
    if not confirm_db:
        st.error("（databases）確認チェックをオンにしてください")
    else:
        st.session_state["backup_running_databases"] = True
        try:
            ok, reason = backup_sets(
                role=role,
                mount=mount,
                backup_sets=[
                    {"name": "databases", "src": db_src},
                ],
                use_link_dest=use_link_dest_db,
                dry_run=dry_run_db,
            )
            if ok:
                st.success("（databases）バックアップが完了しました")
            else:
                st.error(f"（databases）バックアップ失敗：{reason}")
        finally:
            st.session_state["backup_running_databases"] = False


st.caption("※ storages / auth / inbox / archive / databases は完全に分離して保存されます（用途別SSD）")