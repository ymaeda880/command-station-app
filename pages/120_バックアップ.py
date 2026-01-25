# -*- coding: utf-8 -*-
# command_station_app/pages/73_バックアップ.py
"""
Storage / 認証データ / Inbox バックアップ用 Streamlit ページ（common_lib 正本運用）

- location は command_station secrets.toml から取得（common_lib）
- Storages の場所は storages_config の正本 API を使用
- Inbox の場所は inbox_config の正本 API を使用
- backup / backup2 の SSD 判定は probe API（停止しない）

このページでは、
① storages + auth のバックアップ
② inbox のバックアップ
を「別セクション」「別ボタン」「別確認チェック」で実行する。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sys
from pathlib import Path
import json
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
from common_lib.storage.external_mount_probe import probe_backup_mounts
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
st.title("💾 バックアップ（storages/auth と inbox を別実行）")

render_backup_explanation()
st.caption("SSD内 aisv_Backups/backups/ に storages / auth / inbox を分離して保存します。")

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

# 存在チェック（ここは正本なので止めてOK）
for p in (storages_src, auth_src, inbox_src):
    if not p.exists():
        st.error(f"バックアップ元が存在しません: {p}")
        st.stop()

# ============================================================
# SSD 判定（probe：停止しない）※ページ内で共通
# ============================================================
st.divider()
st.write("### バックアップ先SSD")

probe = probe_backup_mounts(PROJECTS_ROOT, roles=("backup", "backup2"))

for r in probe:
    if r.path:
        st.success(f"✅ role={r.role}：接続中（{r.path}）")
    else:
        st.warning(f"⚠️ role={r.role}：{r.reason}")

enabled = [(r.role, r.path) for r in probe if r.path is not None]
if not enabled:
    st.error("接続中のバックアップ先SSDがありません")
    st.stop()

# ============================================================
# 実行中フラグ（セクション別）
# ============================================================
if "backup_running_storage" not in st.session_state:
    st.session_state["backup_running_storage"] = False

if "backup_running_inbox" not in st.session_state:
    st.session_state["backup_running_inbox"] = False


# ============================================================
# セクション① storages + auth
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

cols_sa = st.columns(len(enabled))
clicked_sa: tuple[str, Path] | None = None

for i, (role, mount) in enumerate(enabled):
    with cols_sa[i]:
        disabled = st.session_state["backup_running_storage"] or st.session_state["backup_running_inbox"]
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
# セクション② inbox
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

cols_in = st.columns(len(enabled))
clicked_in: tuple[str, Path] | None = None

for i, (role, mount) in enumerate(enabled):
    with cols_in[i]:
        disabled = st.session_state["backup_running_inbox"] or st.session_state["backup_running_storage"]
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


st.caption("※ storages / auth / inbox は完全に分離して保存されます")
