# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import streamlit as st

from lib.restore.rsync_utils import RunResult, fmt_cmd


DISPLAY_LIMIT = 500


def split_rsync_itemize_line(line: str) -> tuple[str, str]:
    s = str(line or "").strip()
    parts = s.split(maxsplit=1)

    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()

    if len(parts) == 1:
        return parts[0].strip(), ""

    return "", ""


def is_rsync_added_file_code(code: str) -> bool:
    if len(code) < 3:
        return False

    if code[0] != ">":
        return False

    if code[1] != "f":
        return False

    tail = code[2:]
    return bool(tail) and all(ch == "+" for ch in tail)


def is_rsync_added_dir_code(code: str) -> bool:
    if len(code) < 3:
        return False

    if code[0] != "c":
        return False

    if code[1] != "d":
        return False

    tail = code[2:]
    return bool(tail) and all(ch == "+" for ch in tail)


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

        if s.startswith("*deleting "):
            deleting.append(s.replace("*deleting ", "", 1).strip())
            continue

        code, path = split_rsync_itemize_line(s)

        if is_rsync_added_file_code(code):
            adding_files.append(path or s)
            continue

        if is_rsync_added_dir_code(code):
            adding_dirs.append(path or s)
            continue

        if is_rsync_updated_file_code(code):
            updating.append(s)
            continue

        others.append(s)

    return {
        "deleting": deleting,
        "adding_files": adding_files,
        "adding_dirs": adding_dirs,
        "updating": updating,
        "others": others,
    }


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
            render_limited_list(items=parsed["updating"], label="更新")

    if parsed["others"]:
        with st.expander("その他", expanded=False):
            st.caption(
                "追加ファイル・追加ディレクトリ・更新・削除に分類しなかった rsync の行です。"
            )
            render_limited_list(items=parsed["others"], label="その他")

    with st.expander("rsync 生ログ", expanded=False):
        st.code(result.stdout, language="text")


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