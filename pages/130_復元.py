# -*- coding: utf-8 -*-
# command_station_app/pages/130_復元.py
# ============================================================
# ♻️ 復元（バックアップ latest から正本へ）
#
# 機能：
# - バックアップSSD上の latest から正本へ復元する
# - 先に rsync --dry-run で差分を表示する
# - 差分確認後のみ rsync --delete で復元する
#
# 復元方向：
#   <BackupSSD>/aisv_Backups/<location>/backups/<name>/latest/
#   →
#   正本ディレクトリ
#
# 注意：
# - --delete を使うため、復元先は latest と完全一致する
# - 復元先にしかないファイルは削除される
# - 必ず差分確認後に実行する
# ============================================================

from __future__ import annotations

# ============================================================
# imports（stdlib）
# ============================================================
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Optional
import os
import shlex
import subprocess
import sys

# ============================================================
# imports（3rd party）
# ============================================================
import streamlit as st

# ============================================================
# page config
# ============================================================
st.set_page_config(
    page_title="復元",
    page_icon="♻️",
    layout="wide",
)

# ============================================================
# constants
# ============================================================
DISPLAY_LIMIT = 500

# ============================================================
# path setup
# ============================================================
_THIS = Path(__file__).resolve()
APP_DIR = _THIS.parents[1]
PROJ_DIR = _THIS.parents[2]
MONO_ROOT = _THIS.parents[3]

for p in (MONO_ROOT, PROJ_DIR, APP_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

PROJECTS_ROOT = MONO_ROOT
APP_NAME = APP_DIR.name
PAGE_NAME = _THIS.stem

# ============================================================
# common_lib imports（UI / session / auth）
# ============================================================
from common_lib.sessions.page_entry import page_session_heartbeat  # noqa: E402
from common_lib.env.config import get_ui_banner_key_from_app_settings  # noqa: E402
from common_lib.ui.banner_lines import render_banner_line_by_key  # noqa: E402
from common_lib.ui.ui_basics import subtitle  # noqa: E402
import common_lib.auth.auth_helpers as authh  # noqa: E402

# ============================================================
# common_lib imports（location / storage path）
# ============================================================
from common_lib.env.config import get_location_from_command_station_secrets  # noqa: E402
from common_lib.storage.storages_config import resolve_storages_root  # noqa: E402
from common_lib.storage.inbox_config import resolve_inbox_root  # noqa: E402
from common_lib.storage.external_mount_probe import probe_backup_mounts_by_purpose  # noqa: E402
from common_lib.storage.external_ssd_root import resolve_storage_subdir_root_v2  # noqa: E402
from common_lib.auth.paths import resolve_auth_data_root  # noqa: E402


# ============================================================
# dataclass（コマンド実行結果）
# ============================================================
@dataclass
class RunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]

# ============================================================
# RunResult session_state 変換
# ============================================================
def run_result_to_dict(result: RunResult) -> dict:
    return {
        "ok": result.ok,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "cmd": result.cmd,
    }


def run_result_from_dict(value: object) -> Optional[RunResult]:
    if not isinstance(value, dict):
        return None

    try:
        return RunResult(
            ok=bool(value["ok"]),
            returncode=int(value["returncode"]),
            stdout=str(value.get("stdout", "")),
            stderr=str(value.get("stderr", "")),
            cmd=list(value.get("cmd", [])),
        )
    except Exception:
        return None

# ============================================================
# command helper（実行）
# ============================================================
def sh(cmd: list[str]) -> RunResult:
    env = dict(os.environ)
    env["LANG"] = "en_US.UTF-8"
    env["LC_ALL"] = "en_US.UTF-8"

    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    return RunResult(
        ok=(p.returncode == 0),
        returncode=p.returncode,
        stdout=p.stdout or "",
        stderr=p.stderr or "",
        cmd=cmd,
    )


# ============================================================
# command helper（表示用）
# ============================================================
def fmt_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(x) for x in cmd)


# ============================================================
# backup latest path
# ============================================================
def build_backup_latest_path(
    *,
    mount: Path,
    location: str,
    name: str,
) -> Path:
    return mount / "aisv_Backups" / str(location) / "backups" / str(name) / "latest"


# ============================================================
# rsync command（差分確認）
# ============================================================
def build_diff_cmd(
    *,
    restore_from: Path,
    restore_to: Path,
) -> list[str]:
    return [
        "rsync",
        "-a",
        "--8-bit-output",
        "--delete",
        "--dry-run",
        "--itemize-changes",
        f"{restore_from}/",
        f"{restore_to}/",
    ]


# ============================================================
# rsync command（復元実行）
# ============================================================
def build_restore_cmd(
    *,
    restore_from: Path,
    restore_to: Path,
) -> list[str]:
    return [
        "rsync",
        "-a",
        "--8-bit-output",
        "--delete",
        "--itemize-changes",
        f"{restore_from}/",
        f"{restore_to}/",
    ]


# ============================================================
# rsync 出力が空かどうか
# ============================================================
def has_no_diff(result: RunResult) -> bool:
    return result.ok and not result.stdout.strip() and not result.stderr.strip()


# ============================================================
# rsync itemize code 判定 helper
# ============================================================
def split_rsync_itemize_line(line: str) -> tuple[str, str]:
    s = str(line or "").strip()
    parts = s.split(maxsplit=1)

    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()

    if len(parts) == 1:
        return parts[0].strip(), ""

    return "", ""


# ============================================================
# rsync itemize code: 追加ファイル判定
# ============================================================
def is_rsync_added_file_code(code: str) -> bool:
    if len(code) < 3:
        return False

    if code[0] != ">":
        return False

    if code[1] != "f":
        return False

    tail = code[2:]

    if not tail:
        return False

    return all(ch == "+" for ch in tail)


# ============================================================
# rsync itemize code: 追加ディレクトリ判定
# ============================================================
def is_rsync_added_dir_code(code: str) -> bool:
    if len(code) < 3:
        return False

    if code[0] != "c":
        return False

    if code[1] != "d":
        return False

    tail = code[2:]

    if not tail:
        return False

    return all(ch == "+" for ch in tail)


# ============================================================
# rsync itemize code: 更新ファイル判定
# ============================================================
def is_rsync_updated_file_code(code: str) -> bool:
    if len(code) < 2:
        return False

    if code[0] != ">":
        return False

    if code[1] != "f":
        return False

    if is_rsync_added_file_code(code):
        return False

    return True


# ============================================================
# rsync dry-run 出力の分類
# ============================================================
def parse_rsync_diff(stdout: str) -> dict[str, list[str]]:
    deleting: list[str] = []
    adding_files: list[str] = []
    adding_dirs: list[str] = []
    updating: list[str] = []
    others: list[str] = []

    for line in (stdout or "").splitlines():
        s = line.strip()

        if not s:
            continue

        # ----------------------------------------------------
        # 削除
        # ----------------------------------------------------
        if s.startswith("*deleting "):
            deleting.append(s.replace("*deleting ", "", 1).strip())
            continue

        # ----------------------------------------------------
        # itemize code と path を分離
        # ----------------------------------------------------
        code, path = split_rsync_itemize_line(s)

        # ----------------------------------------------------
        # 追加ファイル
        # 例: >f+++++++++ path/to/file
        # 厳密条件:
        # - code[0] == ">"
        # - code[1] == "f"
        # - code[2:] がすべて "+"
        # ----------------------------------------------------
        if is_rsync_added_file_code(code):
            adding_files.append(path or s)
            continue

        # ----------------------------------------------------
        # 追加ディレクトリ
        # 例: cd+++++++++ path/to/dir
        # 厳密条件:
        # - code[0] == "c"
        # - code[1] == "d"
        # - code[2:] がすべて "+"
        # ----------------------------------------------------
        if is_rsync_added_dir_code(code):
            adding_dirs.append(path or s)
            continue

        # ----------------------------------------------------
        # 更新ファイル
        # 例: >f..t.... path/to/file
        # 追加ファイルは上で除外済み
        # ----------------------------------------------------
        if is_rsync_updated_file_code(code):
            updating.append(s)
            continue

        # ----------------------------------------------------
        # その他
        # 例: .d..t.... path/to/dir
        #     sending incremental file list
        # ----------------------------------------------------
        others.append(s)

    return {
        "deleting": deleting,
        "adding_files": adding_files,
        "adding_dirs": adding_dirs,
        "updating": updating,
        "others": others,
    }


# ============================================================
# 一覧表示 helper
# ============================================================
def render_limited_list(
    *,
    items: list[str],
    label: str,
) -> None:
    st.code(
        "\n".join(items[:DISPLAY_LIMIT]),
        language="text",
    )

    if len(items) > DISPLAY_LIMIT:
        st.caption(
            f"先頭{DISPLAY_LIMIT}件のみ表示しています。"
            f"残り {len(items) - DISPLAY_LIMIT} 件あります。"
        )


# ============================================================
# rsync dry-run 差分要約表示
# ============================================================
def render_rsync_diff_summary(result: RunResult) -> None:
    parsed = parse_rsync_diff(result.stdout)

    delete_count = len(parsed["deleting"])
    add_file_count = len(parsed["adding_files"])
    add_dir_count = len(parsed["adding_dirs"])
    update_count = len(parsed["updating"])
    other_count = len(parsed["others"])

    st.subheader("復元差分の要約")

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.metric("削除", f"{delete_count}件")

    with c2:
        st.metric("追加ファイル", f"{add_file_count}件")

    with c3:
        st.metric("追加ディレクトリ", f"{add_dir_count}件")

    with c4:
        st.metric("更新", f"{update_count}件")

    with c5:
        st.metric("その他", f"{other_count}件")

    if delete_count > 0:
        st.error(
            "この復元を実行すると、復元先の正本側から削除されるファイルがあります。"
        )
    elif add_file_count > 0 or add_dir_count > 0 or update_count > 0:
        st.warning(
            "この復元を実行すると、復元先の正本側に追加・更新が行われます。"
        )
    else:
        st.success("復元による変更予定はありません。")

    if parsed["deleting"]:
        with st.expander("削除", expanded=False):
            st.caption(
                "backup latest に存在しないため、復元先の正本側から削除される予定です。"
            )
            render_limited_list(items=parsed["deleting"], label="削除")

    if parsed["adding_files"]:
        with st.expander("追加ファイル", expanded=False):
            st.caption(
                "backup latest に存在し、復元先の正本側へ追加される予定のファイルです。"
            )
            render_limited_list(items=parsed["adding_files"], label="追加ファイル")

    if parsed["adding_dirs"]:
        with st.expander("追加ディレクトリ", expanded=False):
            st.caption(
                "backup latest に存在し、復元先の正本側へ追加される予定のディレクトリです。"
            )
            render_limited_list(items=parsed["adding_dirs"], label="追加ディレクトリ")

    if parsed["updating"]:
        with st.expander("更新", expanded=False):
            st.caption(
                "backup latest の内容で、復元先の正本側が更新される予定です。"
            )
            st.caption(
                "rsync の >f..t.... などの記号は、"
                "ファイル属性の変更内容を表しています。 "
                ">f+++++++++ は新規追加、"
                ">f..t.... は更新日時（timestamp）変更などを意味します。"
            )
            render_limited_list(items=parsed["updating"], label="更新")

    if parsed["others"]:
        with st.expander("その他", expanded=False):
            st.caption(
                "追加ファイル・追加ディレクトリ・更新・削除に分類しなかった rsync の行です。"
            )
            st.caption(
                "例：.d..t.... はディレクトリの timestamp 変更などを表すことがあります。"
            )
            render_limited_list(items=parsed["others"], label="その他")

    with st.expander("rsync 生ログ", expanded=False):
        st.code(result.stdout, language="text")


# ============================================================
# 差分結果テキスト作成
# ============================================================
def build_diff_download_text(
    *,
    result: RunResult,
    restore_from: Path,
    restore_to: Path,
    target_label: str,
) -> str:
    parsed = parse_rsync_diff(result.stdout)

    lines: list[str] = []

    lines.append("復元差分確認結果")
    lines.append("=" * 60)
    lines.append(f"復元対象: {target_label}")
    lines.append(f"復元元 latest: {restore_from}")
    lines.append(f"復元先 正本: {restore_to}")
    lines.append("")
    lines.append("実行コマンド")
    lines.append("-" * 60)
    lines.append(fmt_cmd(result.cmd))
    lines.append("")
    lines.append("要約")
    lines.append("-" * 60)
    lines.append(f"削除: {len(parsed['deleting'])}件")
    lines.append(f"追加ファイル: {len(parsed['adding_files'])}件")
    lines.append(f"追加ディレクトリ: {len(parsed['adding_dirs'])}件")
    lines.append(f"更新: {len(parsed['updating'])}件")
    lines.append(f"その他: {len(parsed['others'])}件")
    lines.append("")

    lines.append("削除")
    lines.append("-" * 60)
    lines.extend(parsed["deleting"] or ["なし"])
    lines.append("")

    lines.append("追加ファイル")
    lines.append("-" * 60)
    lines.extend(parsed["adding_files"] or ["なし"])
    lines.append("")

    lines.append("追加ディレクトリ")
    lines.append("-" * 60)
    lines.extend(parsed["adding_dirs"] or ["なし"])
    lines.append("")

    lines.append("更新")
    lines.append("-" * 60)
    lines.extend(parsed["updating"] or ["なし"])
    lines.append("")

    lines.append("その他")
    lines.append("-" * 60)
    lines.extend(parsed["others"] or ["なし"])
    lines.append("")

    lines.append("rsync stdout 生ログ")
    lines.append("-" * 60)
    lines.append(result.stdout or "")

    if result.stderr.strip():
        lines.append("")
        lines.append("rsync stderr")
        lines.append("-" * 60)
        lines.append(result.stderr)

    return "\n".join(lines)


# ============================================================
# rsync 出力表示
# ============================================================
def render_rsync_result(title: str, result: RunResult) -> None:
    st.write(f"#### {title}")
    st.caption("実行コマンド")
    st.code(fmt_cmd(result.cmd), language="bash")

    if result.ok:
        st.success(f"コマンドは正常終了しました。returncode={result.returncode}")
    else:
        st.error(f"コマンドが失敗しました。returncode={result.returncode}")

    if result.stdout.strip():
        st.caption("stdout")
        st.code(result.stdout, language="text")
    else:
        st.caption("stdout は空です。")

    if result.stderr.strip():
        st.caption("stderr")
        st.code(result.stderr, language="text")


# ============================================================
# バナー表示
# ============================================================
banner_key = get_ui_banner_key_from_app_settings(Path(__file__))
render_banner_line_by_key(banner_key)

# ============================================================
# ログイン + heartbeat
# ============================================================
sub_session = page_session_heartbeat(
    st,
    PROJECTS_ROOT,
    app_name=APP_NAME,
    page_name=PAGE_NAME,
)

# ============================================================
# admin gate
# ============================================================
if not sub_session:
    st.error("ログインしていません。ポータルからログインしてください。")
    st.stop()

if not authh.is_admin(sub_session):
    st.error("🚫 このページは管理者のみアクセスできます。")
    st.caption("ヒント：管理者ユーザーに追加されているか settings.toml（admin_users）を確認してください。")
    st.stop()

sub_admin = sub_session

# ============================================================
# location
# ============================================================
try:
    loc = get_location_from_command_station_secrets(PROJECTS_ROOT)
except Exception as e:
    st.error(f"location 取得失敗：{e}")
    st.stop()

# ============================================================
# 正本パス解決
# ============================================================
try:
    storages_dst = resolve_storages_root(PROJECTS_ROOT)
    auth_dst = resolve_auth_data_root(PROJECTS_ROOT)
    inbox_dst = resolve_inbox_root(PROJECTS_ROOT)
    archive_dst = resolve_storage_subdir_root_v2(PROJECTS_ROOT, subdir="Archive", role="main")
    db_dst = resolve_storage_subdir_root_v2(PROJECTS_ROOT, subdir="Databases", role="main")
except Exception as e:
    st.error(f"正本パス解決に失敗しました：{e}")
    st.stop()

# ============================================================
# 復元対象定義
# ============================================================
RESTORE_TARGETS = {
    "storages": {
        "label": "storages",
        "purpose": "storage",
        "dst": storages_dst,
        "caption": "Storages 正本へ復元します。",
    },
    "auth": {
        "label": "auth",
        "purpose": "storage",
        "dst": auth_dst,
        "caption": "認証データ正本へ復元します。",
    },
    "inbox": {
        "label": "inbox",
        "purpose": "inbox",
        "dst": inbox_dst,
        "caption": "InBoxStorages 正本へ復元します。",
    },
    "archive": {
        "label": "archive",
        "purpose": "archive",
        "dst": archive_dst,
        "caption": "Archive 正本へ復元します。",
    },
    "databases": {
        "label": "databases",
        "purpose": "databases",
        "dst": db_dst,
        "caption": "Databases 正本へ復元します。",
    },
}

# ============================================================
# UI header
# ============================================================
left, right = st.columns([2, 1])

with left:
    st.title("♻️ 復元（バックアップ latest から正本へ）")
    st.caption(
        f"`aisv_Backups/{loc}/backups/<name>/latest/` から、"
        "現在の正本ディレクトリへ復元します。"
    )

with right:
    st.success(f"✅ 管理者ログイン中: **{sub_admin}**")

subtitle("復元実行ページ")

# ============================================================
# 注意表示
# ============================================================
st.warning(
    "復元は --delete を使います。復元先にしか存在しないファイルは削除され、"
    "バックアップ latest と同じ状態になります。"
)

st.caption(f"location: {loc}")
st.caption(f"projects_root: {PROJECTS_ROOT}")

# ============================================================
# 復元対象選択
# ============================================================
st.divider()
st.subheader("① 復元対象を選択")

target_name = st.radio(
    "復元対象",
    options=list(RESTORE_TARGETS.keys()),
    format_func=lambda x: RESTORE_TARGETS[x]["label"],
    key=f"{PAGE_NAME}__target_name",
)

target = RESTORE_TARGETS[target_name]
target_label = str(target["label"])
purpose_key = str(target["purpose"])
restore_to = Path(target["dst"])

st.caption(str(target["caption"]))
st.write(f"- 復元対象: **{target_label}**")
st.write(f"- purpose: `{purpose_key}`")
st.write(f"- 復元先（正本）: `{restore_to}`")

if not restore_to.exists():
    st.error(f"復元先の正本ディレクトリが存在しません: {restore_to}")
    st.stop()

# ============================================================
# バックアップSSD検出
# ============================================================
st.divider()
st.subheader("② バックアップSSDを選択")

probe_list = probe_backup_mounts_by_purpose(
    PROJECTS_ROOT,
    purpose_key=purpose_key,
    roles=("backup", "backup2"),
)

enabled = [(r.role, r.path) for r in probe_list if r.path is not None]

for r in probe_list:
    if r.path:
        st.success(f"✅ role={r.role}: 接続中（{r.path}）")
    else:
        st.warning(f"⚠️ role={r.role}: {r.reason}")

if not enabled:
    st.error("接続中のバックアップSSDがありません。")
    st.stop()

role_options = [role for role, _mount in enabled]

selected_role = st.radio(
    "復元元バックアップSSD",
    options=role_options,
    key=f"{PAGE_NAME}__selected_role",
)

selected_mount: Optional[Path] = None

for role, mount in enabled:
    if role == selected_role:
        selected_mount = mount
        break

if selected_mount is None:
    st.error("復元元バックアップSSDを特定できません。")
    st.stop()

restore_from = build_backup_latest_path(
    mount=selected_mount,
    location=loc,
    name=target_label,
)

st.write(f"- 復元元 latest: `{restore_from}`")
st.write(f"- 復元先 正本: `{restore_to}`")

try:
    backup_dt = datetime.fromtimestamp(restore_from.stat().st_mtime)
    st.info(f"このバックアップ latest の最終更新日時: {backup_dt.strftime('%Y-%m-%d %H:%M:%S')}")
except Exception as e:
    st.warning(f"バックアップ日時を取得できませんでした: {e}")

if not restore_from.exists():
    st.error(f"復元元 latest が存在しません: {restore_from}")
    st.stop()

if not restore_from.is_dir():
    st.error(f"復元元 latest がディレクトリではありません: {restore_from}")
    st.stop()

# ============================================================
# session state keys
# ============================================================
KEY_DIFF_RESULT = f"{PAGE_NAME}__diff_result"
KEY_DIFF_SOURCE = f"{PAGE_NAME}__diff_source"
KEY_DIFF_DEST = f"{PAGE_NAME}__diff_dest"
KEY_DIFF_TARGET = f"{PAGE_NAME}__diff_target"

if KEY_DIFF_RESULT not in st.session_state:
    st.session_state[KEY_DIFF_RESULT] = None
if KEY_DIFF_SOURCE not in st.session_state:
    st.session_state[KEY_DIFF_SOURCE] = ""
if KEY_DIFF_DEST not in st.session_state:
    st.session_state[KEY_DIFF_DEST] = ""
if KEY_DIFF_TARGET not in st.session_state:
    st.session_state[KEY_DIFF_TARGET] = ""

# ============================================================
# 差分確認
# ============================================================
st.divider()
st.subheader("③ 差分を確認")

st.caption("まず dry-run で、復元すると何が変わるかを確認します。")
st.caption("この段階ではファイルは変更されません。")

if st.button(
    "差分を確認",
    type="primary",
    key=f"{PAGE_NAME}__run_diff",
):
    diff_cmd = build_diff_cmd(
        restore_from=restore_from,
        restore_to=restore_to,
    )
    diff_result = sh(diff_cmd)

    # st.session_state[KEY_DIFF_RESULT] = diff_result
    st.session_state[KEY_DIFF_RESULT] = run_result_to_dict(diff_result)
    st.session_state[KEY_DIFF_SOURCE] = str(restore_from)
    st.session_state[KEY_DIFF_DEST] = str(restore_to)
    st.session_state[KEY_DIFF_TARGET] = str(target_label)

# ============================================================
# 差分表示
# ============================================================
diff_result = run_result_from_dict(st.session_state.get(KEY_DIFF_RESULT))

if diff_result is not None:
    st.divider()
    st.subheader("④ 復元差分（正本側の変更予定）")

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
        st.error("差分確認に失敗しているため、復元は実行できません。")
        st.stop()

    if has_no_diff(diff_result):
        st.success("差分はありません。復元先は latest と同じ状態です。")
    else:
        render_rsync_diff_summary(diff_result)

        diff_text = build_diff_download_text(
            result=diff_result,
            restore_from=restore_from,
            restore_to=restore_to,
            target_label=target_label,
        )

        st.sidebar.download_button(
            label="復元差分テキストをダウンロード",
            data=diff_text.encode("utf-8"),
            file_name=f"restore_diff_{target_label}.txt",
            mime="text/plain",
            key=f"{PAGE_NAME}__download_restore_diff",
        )

# ============================================================
# 復元実行条件チェック
# ============================================================
can_restore = (
    diff_result is not None
    and diff_result.ok
    and st.session_state.get(KEY_DIFF_SOURCE) == str(restore_from)
    and st.session_state.get(KEY_DIFF_DEST) == str(restore_to)
    and st.session_state.get(KEY_DIFF_TARGET) == str(target_label)
)

# ============================================================
# 復元実行
# ============================================================
st.divider()
st.subheader("⑤ 確認後に復元")

if not can_restore:
    st.info("先に現在の復元元・復元先で「差分を確認」を実行してください。")
else:
    st.error(
        "復元を実行すると、復元先の正本ディレクトリはバックアップ latest と同じ状態になります。"
    )

    confirm_restore = st.checkbox(
        "差分を確認しました。正本をバックアップ latest の状態へ復元します。",
        value=False,
        key=f"{PAGE_NAME}__confirm_restore",
    )

    typed = st.text_input(
        "確認のため RESTORE と入力してください",
        value="",
        key=f"{PAGE_NAME}__typed_restore",
    )

    run_restore = st.button(
        "復元を実行",
        type="primary",
        disabled=not (confirm_restore and typed == "RESTORE"),
        key=f"{PAGE_NAME}__run_restore",
    )

    if run_restore:
        restore_cmd = build_restore_cmd(
            restore_from=restore_from,
            restore_to=restore_to,
        )

        result = sh(restore_cmd)

        st.divider()
        st.subheader("復元実行結果")

        render_rsync_result("復元結果", result)

        if result.ok:
            st.success("復元が完了しました。")
            st.session_state[KEY_DIFF_RESULT] = None
            st.session_state[KEY_DIFF_SOURCE] = ""
            st.session_state[KEY_DIFF_DEST] = ""
            st.session_state[KEY_DIFF_TARGET] = ""
        else:
            st.error("復元に失敗しました。stderr を確認してください。")

# ============================================================
# フッタ
# ============================================================
st.divider()
st.caption(
    f"復元元は aisv_Backups/{loc}/backups/<name>/latest/、"
    "復元先は resolver で解決した現在の正本ディレクトリです。"
)