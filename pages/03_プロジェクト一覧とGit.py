# pages/03_プロジェクト走査とGit操作.py
from __future__ import annotations
from pathlib import Path
import shlex
import streamlit as st
import pandas as pd

from config.path_config import PROJECT_ROOT
from lib.cmd_utils import (
    git, is_git_repo, git_branch, git_remote_first, git_status_short, git_changed_count
)

st.set_page_config(page_title="📁 走査＆Git操作", page_icon="📁", layout="wide")
st.title("📁 プロジェクト走査 ＋ 🔧 Git 操作")

st.caption(
    "- `settings.toml` の location から **project_root** を取得\n"
    "- `*_project/` 直下の `*_app/`（かつ `app.py` を含む）を検出\n"
    "- さらに `apps_portal/` も Git 対象に含める\n"
    "- 一覧で Git ステータスを表示 → 選択に対して一括操作（fetch/pull/push/commit）"
)

st.info(f"現在の project_root: `{PROJECT_ROOT}`")

# ------------------------------------------------------------
# 1) 走査: *_project / *_app / app.py
# ------------------------------------------------------------
def discover_app_repos(root: Path) -> list[dict]:
    rows: list[dict] = []
    for proj_dir in sorted([p for p in root.glob("*_project") if p.is_dir()]):
        for app_dir in sorted([a for a in proj_dir.glob("*_app") if a.is_dir()]):
            if (app_dir / "app.py").exists():
                rows.append({"name": app_dir.name, "path": app_dir})
    portal = root / "apps_portal"
    if portal.exists() and portal.is_dir():
        rows.append({"name": "apps_portal", "path": portal})
    return rows

repos = discover_app_repos(PROJECT_ROOT)
if not repos:
    st.warning("対象フォルダが見つかりませんでした。`*_project` / `*_app` / `apps_portal` を確認してください。")
    st.stop()

# Git メタデータ収集
records = []
for r in repos:
    path = str(r["path"])
    repo_flag = is_git_repo(path)
    branch = git_branch(path) if repo_flag else ""
    remote = git_remote_first(path) if repo_flag else ""
    changed = git_changed_count(path) if repo_flag else None
    status = git_status_short(path) if repo_flag else "(not a git repo)"
    records.append({
        "選択": False,
        "名前": r["name"],
        "パス": path,
        "Git": "Yes" if repo_flag else "No",
        "ブランチ": branch,
        "リモート": remote,
        "変更数": changed,
        "status": status,
    })

df = pd.DataFrame(records)
st.subheader("🔎 検出結果 & ステータス")
st.dataframe(df.drop(columns=["status"]), width="stretch")

with st.expander("各リポジトリの `git status -sb` 出力（詳細）", expanded=False):
    for rec in records:
        st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
        st.code(rec["status"], language="bash")

# ------------------------------------------------------------
# 2) 操作対象の選択
# ------------------------------------------------------------
st.divider()
st.subheader("✅ 操作対象を選ぶ")

sel = []
for i, rec in enumerate(records):
    c1, c2 = st.columns([1, 7])
    with c1:
        checked = st.checkbox("", key=f"sel_{i}")
    with c2:
        git_badge = "🟢 Git" if rec["Git"] == "Yes" else "⚪️ not Git"
        st.write(
            f"**{rec['名前']}** — `{rec['パス']}` | {git_badge} | "
            f"ブランチ: `{rec['ブランチ'] or '-'}` | 変更: {rec['変更数'] if rec['変更数'] is not None else '-'}"
        )
    if checked:
        sel.append(rec)

if not sel:
    st.info("少なくとも1つのフォルダを選択してください。")
else:
    st.success(f"{len(sel)} 件選択中。")

if sel:
    st.markdown("### 🧩 現在選択中の対象")
    for rec in sel:
        st.markdown(f"- **{rec['名前']}** — `{rec['パス']}` （Git: {rec['Git']}）")

# ------------------------------------------------------------
# 3) 一括Git操作（fetch / pull / push）
# ------------------------------------------------------------
st.divider()
st.subheader("🛠️ 一括 Git 操作")

git_targets = [r for r in sel if r["Git"] == "Yes"]
if sel and not git_targets:
    st.warning("選択に Git リポジトリが含まれていません。（fetch/pull/push は Git リポジトリのみ対象）")

col = st.columns(3)
if git_targets:
    with col[0]:
        if st.button("🌿 fetch --all --prune（選択分）", key="btn_fetch_main"):
            for rec in git_targets:
                code, out, err = git("fetch --all --prune", cwd=rec["パス"])
                st.markdown(f"**{rec['名前']}**")
                st.code(out or err or "(no output)", language="bash")
    with col[1]:
        if st.button("⬇️ pull（選択分）", key="btn_pull_main"):
            for rec in git_targets:
                code, out, err = git("pull", cwd=rec["パス"])
                st.markdown(f"**{rec['名前']}**")
                st.code(out or err or "(no output)", language="bash")
    with col[2]:
        if st.button("⬆️ push（選択分）", key="btn_push_main"):
            for rec in git_targets:
                code, out, err = git("push", cwd=rec["パス"])
                st.markdown(f"**{rec['名前']}**")
                st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 💡 ヘルプセクション
# ------------------------------------------------------------
with st.expander("💡 一括 Git 操作の使い方（ヘルプを開く）", expanded=False):
    st.markdown("""
### 🧭 使い方概要
このページでは、選択した複数リポジトリに対して Git 操作を一括実行できます。

| ボタン | コマンド | 説明 |
|--------|-----------|------|
| 🌿 fetch | git fetch --all --prune | リモート情報更新 |
| ⬇️ pull | git pull | 最新のリモート反映 |
| ⬆️ push | git push | ローカルコミットを反映 |

下段フォームで add / commit / push もまとめて行えます。
""")

# ------------------------------------------------------------
# 4) add / commit / push
# ------------------------------------------------------------
st.subheader("✍️ add / commit / push（選択分）")
with st.form("commit_form", clear_on_submit=False):
    add_pattern = st.text_input("add 対象", ".", key="txt_add_pattern")
    commit_msg = st.text_input("コミットメッセージ", "", key="txt_commit_msg")
    do_push = st.checkbox("コミット後に push する", value=False, key="chk_do_push")
    submitted = st.form_submit_button("実行", key="btn_commit_submit")

if submitted:
    if not git_targets:
        st.error("選択に Git リポジトリが含まれていません。")
    elif not commit_msg.strip():
        st.error("コミットメッセージが空です。")
    else:
        for rec in git_targets:
            st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
            code, out, err = git(f"add {add_pattern}", cwd=rec["パス"])
            st.code(out or err or "(no output)", language="bash")
            code, out, err = git("diff --cached --name-only", cwd=rec["パス"])
            if not out.strip():
                st.info("ステージされた変更がありません。commit をスキップ。")
                continue
            safe_msg = shlex.quote(commit_msg)
            code, out, err = git(f"commit -m {safe_msg}", cwd=rec["パス"])
            st.code(out or err or "(no output)", language="bash")
            if do_push:
                code, out, err = git("push", cwd=rec["パス"])
                st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 5) ステータス再読み込み
# ------------------------------------------------------------
st.divider()
if st.button("🔁 ステータス再読み込み", key="btn_reload_status"):
    st.rerun()

# ------------------------------------------------------------
# 6) 直近ログプレビュー
# ------------------------------------------------------------
st.subheader("📜 直近ログプレビュー（選択分）")
log_n = st.number_input("表示するコミット数 (-n)", min_value=1, max_value=100, value=10, step=1, key="num_log_count")
if sel and st.button("ログを表示", key="btn_show_logs"):
    for rec in sel:
        st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
        code, out, err = git(f"log --oneline -n {int(log_n)}", cwd=rec["パス"])
        st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 7) pull --rebase
# ------------------------------------------------------------
st.subheader("⬇️ pull --rebase（選択分）")
st.caption("マージコミットを作らずに履歴を整える場合はこちら。")
if sel and st.button("pull --rebase を実行", key="btn_pull_rebase"):
    for rec in sel:
        st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
        code, out, err = git("pull --rebase", cwd=rec["パス"])
        st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 8) 💣 強制リセット
# ------------------------------------------------------------
st.subheader("💣 強制リセット（選択分）")
st.caption("fetch origin → reset --hard origin/<branch>")
col_reset = st.columns([2, 2, 3])
with col_reset[0]:
    really = st.checkbox("実行内容を理解した", key="chk_really_reset")
with col_reset[1]:
    confirm_text = st.text_input("確認のため `RESET` と入力", "", key="txt_reset_confirm")
with col_reset[2]:
    st.write("手順: fetch origin → reset --hard origin/<branch>")

if sel and st.button("💥 強制リセットを実行", key="btn_force_reset"):
    if not really or confirm_text.strip().upper() != "RESET":
        st.error("確認が未完了です。チェックと `RESET` 入力を確認してください。")
    else:
        for rec in sel:
            st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
            git("fetch origin", cwd=rec["パス"])
            branch = rec.get("ブランチ") or "main"
            git(f"reset --hard origin/{branch}", cwd=rec["パス"])
            st.success(f"{rec['名前']} → リセット完了")

# ------------------------------------------------------------
# 9) 新規リポジトリ初期化（git init）
# ------------------------------------------------------------
st.divider()
st.subheader("🆕 新規 Git リポジトリ初期化（選択分）")

col_init = st.columns([1, 2, 2])
with col_init[0]:
    confirm_init = st.checkbox("実行を許可する", value=False, key="chk_confirm_init")
with col_init[1]:
    remote_url = st.text_input(
        "（任意）初期リモートURL",
        placeholder="例：https://github.com/user/repo.git",
        key="txt_remote_url"
    )
with col_init[2]:
    auto_commit = st.checkbox("初回 commit も行う", value=False, key="chk_auto_commit")

if st.button("🚀 git init を実行（選択分）", use_container_width=True, key="btn_git_init"):
    init_targets = [r for r in sel if r["Git"] == "No"]
    if not sel:
        st.error("対象フォルダが選択されていません。")
    elif not init_targets:
        st.warning("選択の中に Git 未初期化フォルダがありません。")
    elif not confirm_init:
        st.error("実行を許可するチェックをオンにしてください。")
    else:
        for rec in init_targets:
            repo_path = Path(rec["パス"])
            st.markdown(f"**{rec['名前']}** — `{repo_path}`")
            code, out, err = git("init", cwd=repo_path)
            st.code(out or err or "(no output)", language="bash")
            if remote_url.strip():
                git(f"remote add origin {shlex.quote(remote_url)}", cwd=repo_path)
            if auto_commit:
                git("add .", cwd=repo_path)
                git("commit -m 'Initial commit'", cwd=repo_path)
            st.success("✅ git init 完了")

        st.info("必要に応じてリモート設定や push を行ってください。")

# ------------------------------------------------------------
# 10) 初回 push（upstream 設定）
# ------------------------------------------------------------
st.divider()
st.subheader("🚀 初回 push（上流ブランチを設定）")

col_up = st.columns([2, 2, 3])
with col_up[0]:
    remote_name = st.text_input("リモート名", "origin", key="txt_remote_name")
with col_up[1]:
    use_head = st.checkbox("現在のブランチ（HEAD）にpush", value=True, key="chk_use_head")
with col_up[2]:
    st.caption("※ 初回のみ `-u/--set-upstream` を付けて上流設定します")

if st.button("初回 push を実行（選択分）", key="btn_first_push"):
    git_targets = [r for r in sel if r["Git"] == "Yes"]
    if not git_targets:
        st.error("Git リポジトリが選択されていません。")
    else:
        for rec in git_targets:
            st.markdown(f"**{rec['名前']}** — `{rec['パス']}`")
            # 追跡ブランチが未設定なら push -u を実行
            # すでに設定済みか軽くチェック（未設定だと失敗するコマンド）
            code, _, _ = git("rev-parse --abbrev-ref --symbolic-full-name @{u}", cwd=rec["パス"])
            if code == 0:
                st.info("すでに上流ブランチが設定されています（通常の push を利用してください）。")
                continue

            if use_head:
                cmd = f"push -u {shlex.quote(remote_name)} HEAD"
            else:
                current_branch = rec.get("ブランチ") or "main"
                cmd = f"push -u {shlex.quote(remote_name)} {shlex.quote(current_branch)}"
            code, out, err = git(cmd, cwd=rec["パス"])
            st.code(out or err or "(no output)", language="bash")

