# pages/03_プロジェクト走査とGit操作.py
from __future__ import annotations
from pathlib import Path
import shlex
import streamlit as st
import pandas as pd

from config.path_config import PROJECT_ROOT
from lib.cmd_utils import git
from lib.ui_utils import thick_divider
from lib.project_scan import apps_git_dataframe

# ------------------------------------------------------------
# ページ設定
# ------------------------------------------------------------
st.set_page_config(page_title="📁 走査＆Git操作", page_icon="📁", layout="wide")
st.title("📁 プロジェクト走査 ＋ 🔧 Git 操作")

st.warning("githubの内容との違いを調べるには，fetch --all --prune（一括Git操作）を先に行うこと")

st.caption(
    "- `settings.toml` の location から **project_root** を取得\n"
    "- `*_project/` 直下の `*_app/`（かつ `app.py` を含む）を検出\n"
    "- さらに `apps_portal/` も Git 対象に含める\n"
    "- 一覧で Git ステータスを表示 → 選択に対して一括操作（fetch/pull/push/commit/init）"
)

st.info(f"現在の project_root: `{PROJECT_ROOT}`")

# ------------------------------------------------------------
# 1) プロジェクト走査＋Git情報取得
# ------------------------------------------------------------
df = apps_git_dataframe(PROJECT_ROOT)

if df.empty:
    st.warning("対象フォルダが見つかりませんでした。`*_project` / `*_app` / `apps_portal` を確認してください。")
    st.stop()

st.subheader("🔎 検出結果 & ステータス")

df_display = df.rename(columns={
    "name": "名前",
    "path": "パス",
    "kind": "種別",
    "branch": "ブランチ",
    "dirty": "変更数",
    "ahead": "↑ ahead",
    "behind": "↓ behind",
    "is_repo": "Git管理",
})
st.dataframe(df_display.drop(columns=["short_status"]), width="stretch")

with st.expander("各リポジトリの `git status -sb` 出力（詳細）", expanded=False):
    for _, rec in df.iterrows():
        st.markdown(f"**{rec['name']}** — `{rec['path']}`")
        st.code(rec["short_status"], language="bash")

# ------------------------------------------------------------
# 💬 Git ステータス記号の意味（ヘルプ折りたたみ）
# ------------------------------------------------------------
with st.expander("💬 `git status -sb` の記号の意味（クリックで開く）", expanded=False):
    st.markdown(
        """
### 🧭 Git ステータスの略号解説

| 記号 | 意味 | 説明 |
|------|------|------|
| `M` | **Modified（変更あり）** | ファイルが修正された（まだ commit していない） |
| `A` | **Added（追加）** | 新規ファイルが `git add` 済み |
| `D` | **Deleted（削除）** | ファイルが削除された（ステージ済み or 未ステージ） |
| `R` | **Renamed（リネーム）** | ファイル名が変更された |
| `C` | **Copied（コピー）** | 既存ファイルを複製した変更 |
| `??` | **Untracked（未追跡）** | Git にまだ登録されていない新規ファイル（未 `add`） |
| `!!` | **Ignored（無視対象）** | `.gitignore` により追跡しない設定のファイル |
| `UU` | **Conflict（競合）** | マージ時に競合が発生しているファイル |
"""
    )

# ------------------------------------------------------------
# 2) 操作対象の選択
# ------------------------------------------------------------
st.divider()
st.subheader("✅ 操作対象を選ぶ")

sel = []
for i, row in df.iterrows():
    c1, c2 = st.columns([1, 7])
    with c1:
        checked = st.checkbox("", key=f"sel_{i}")
    with c2:
        git_badge = "🟢 Git" if row["is_repo"] else "⚪️ not Git"
        st.write(
            f"**{row['name']}** — `{row['path']}` | {git_badge} | "
            f"ブランチ: `{row['branch'] or '-'}` | 変更: {row['dirty']} | "
            f"ahead: {row['ahead']} | behind: {row['behind']}"
        )
    if checked:
        sel.append(row)

if not sel:
    st.info("少なくとも1つのフォルダを選択してください。")
else:
    st.success(f"{len(sel)} 件選択中。")

if sel:
    st.markdown("### 🧩 現在選択中の対象")
    for r in sel:
        st.markdown(f"- **{r['name']}** — `{r['path']}` （Git: {r['is_repo']}）")

git_targets = [r for r in sel if r["is_repo"]]

# ------------------------------------------------------------
# 3) add / commit / push
# ------------------------------------------------------------
thick_divider("#007ACC", 4)
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
            with st.expander(f"🧾 {rec['name']} の結果", expanded=False):
                st.markdown(f"**{rec['name']}** — `{rec['path']}`")
                code, out, err = git(f"add {add_pattern}", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")
                code, out, err = git("diff --cached --name-only", cwd=rec["path"])
                if not out.strip():
                    st.info("ステージされた変更がありません。commit をスキップ。")
                    continue
                safe_msg = shlex.quote(commit_msg)
                code, out, err = git(f"commit -m {safe_msg}", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")
                if do_push:
                    code, out, err = git("push", cwd=rec["path"])
                    st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 4) 一括Git操作（fetch / pull / push）
# ------------------------------------------------------------
thick_divider("#007ACC", 4)
st.subheader("🛠️ 一括 Git 操作")

col = st.columns(3)

# 🌿 fetch
with col[0]:
    if st.button("🌿 fetch --all --prune（選択分）", key="btn_fetch_main"):
        if not git_targets:
            st.warning("⚠️ Git リポジトリが選択されていません。")
        else:
            for rec in git_targets:
                st.markdown(f"**{rec['name']}**")
                code, out, err = git("fetch --all --prune", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")

# ⬇️ pull
with col[1]:
    if st.button("⬇️ pull（選択分）", key="btn_pull_main"):
        if not git_targets:
            st.warning("⚠️ Git リポジトリが選択されていません。")
        else:
            for rec in git_targets:
                st.markdown(f"**{rec['name']}**")
                code, out, err = git("pull", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")

# ⬆️ push
with col[2]:
    if st.button("⬆️ push（選択分）", key="btn_push_main"):
        if not git_targets:
            st.warning("⚠️ Git リポジトリが選択されていません。")
        else:
            for rec in git_targets:
                st.markdown(f"**{rec['name']}**")
                code, out, err = git("push", cwd=rec["path"])
                st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 5) ステータス再読み込み
# ------------------------------------------------------------
thick_divider("#007ACC", 4)
st.caption("Gitの変更を反映させます．いつでも実行できます．")
if st.button("🔁 Git ステータスを更新", key="btn_reload_status"):
    st.rerun()

# ------------------------------------------------------------
# 6) git clone（新規取得）
# ------------------------------------------------------------
thick_divider("#007ACC", 4)
st.subheader("🧲 git clone（新規取得）")

with st.form("clone_form", clear_on_submit=False):
    clone_url = st.text_input("リポジトリURL", placeholder="https://github.com/user/repo.git", key="txt_clone_url")
    dest_parent = st.text_input("保存先フォルダ（親）", value=str(PROJECT_ROOT), key="txt_clone_parent")
    folder_name = st.text_input("作成するフォルダ名（任意。空なら自動）", value="", key="txt_clone_dir")
    shallow = st.checkbox("--depth 1（浅い履歴）", value=False, key="chk_clone_depth")
    submodules = st.checkbox("--recurse-submodules", value=False, key="chk_clone_sub")
    run_clone = st.form_submit_button("🧲 clone を実行")

if run_clone:
    if not clone_url.strip():
        st.error("リポジトリURLを入力してください。")
    else:
        parent = Path(dest_parent).expanduser()
        if not parent.exists():
            st.error("保存先フォルダ（親）が存在しません。")
        else:
            extra = []
            if shallow:
                extra += ["--depth", "1", "--no-single-branch"]
            if submodules:
                extra += ["--recurse-submodules"]

            if folder_name.strip():
                target_dir = parent / folder_name.strip()
                if target_dir.exists():
                    st.error(f"作成先が既に存在します: {target_dir}")
                else:
                    cmd = " ".join(["clone"] + extra + [shlex.quote(clone_url), shlex.quote(str(target_dir))])
                    code, out, err = git(cmd, cwd=parent)
                    st.code(out or err or "(no output)", language="bash")
                    st.success(f"✅ clone 完了: {target_dir}") if code == 0 else st.error("❌ clone に失敗しました。")
            else:
                # フォルダ名未指定：git に任せて自動作成
                cmd = " ".join(["clone"] + extra + [shlex.quote(clone_url)])
                code, out, err = git(cmd, cwd=parent)
                st.code(out or err or "(no output)", language="bash")
                st.success("✅ clone 完了") if code == 0 else st.error("❌ clone に失敗しました。")

# ------------------------------------------------------------
# 7) 新規リポジトリ初期化
# ------------------------------------------------------------
thick_divider("#007ACC", 4)
st.subheader("🆕 新規 Git リポジトリ初期化 ➜ 初回push")
st.markdown("#### 🆕 新規 Git リポジトリ初期化（選択分）")

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
    init_targets = [r for r in sel if not r["is_repo"]]
    if not sel:
        st.error("対象フォルダが選択されていません。")
    elif not init_targets:
        st.warning("選択の中に Git 未初期化フォルダがありません。")
    elif not confirm_init:
        st.error("実行を許可するチェックをオンにしてください。")
    else:
        for rec in init_targets:
            repo_path = Path(rec["path"])
            st.markdown(f"**{rec['name']}** — `{repo_path}`")
            code, out, err = git("init", cwd=repo_path)
            st.code(out or err or "(no output)", language="bash")

            # .gitignore 自動作成
            gitignore_path = repo_path / ".gitignore"
            if not gitignore_path.exists():
                gitignore_path.write_text(".venv/\n__pycache__/\n.DS_Store\n")
                st.info(".gitignore を自動作成しました。")

            if remote_url.strip():
                git(f"remote add origin {shlex.quote(remote_url)}", cwd=repo_path)
            if auto_commit:
                git("add .", cwd=repo_path)
                git("commit -m 'Initial commit'", cwd=repo_path)
            st.success("✅ git init 完了")

        st.info("必要に応じてリモート設定や push を行ってください。")

# ------------------------------------------------------------
# 8) 初回 push（upstream 設定）
# ------------------------------------------------------------
st.divider()
st.markdown("#### 🚀 初回 push（上流ブランチを設定）")

col_up = st.columns([2, 2, 3])
with col_up[0]:
    remote_name = st.text_input("リモート名", "origin", key="txt_remote_name")
with col_up[1]:
    use_head = st.checkbox("現在のブランチ（HEAD）にpush", value=True, key="chk_use_head")
with col_up[2]:
    st.caption("※ 初回のみ `-u/--set-upstream` を付けて上流設定します")

if st.button("初回 push を実行（選択分）", key="btn_first_push"):
    if not git_targets:
        st.error("Git リポジトリが選択されていません。")
    else:
        for rec in git_targets:
            st.markdown(f"**{rec['name']}** — `{rec['path']}`")
            code, _, _ = git("rev-parse --abbrev-ref --symbolic-full-name @{u}", cwd=rec["path"])
            if code == 0:
                st.info("すでに上流ブランチが設定されています。通常の push を利用してください。")
                continue
            else:
                st.caption("上流ブランチが未設定 → push -u を実行します。")

            if use_head:
                cmd = f"push -u {shlex.quote(remote_name)} HEAD"
            else:
                current_branch = rec["branch"] or "main"
                cmd = f"push -u {shlex.quote(remote_name)} {shlex.quote(current_branch)}"
            code, out, err = git(cmd, cwd=rec["path"])
            st.code(out or err or "(no output)", language="bash")

# ------------------------------------------------------------
# 9) 💣 強制リセット（選択分）
# ------------------------------------------------------------
thick_divider("#ff4d4f", 3)
st.subheader("💣 強制リセット（選択分）")
st.caption(
    "各リポジトリを **リモートの最新状態に完全一致** させます。"
    " ローカルの未コミット変更や push していないコミットは失われます。"
    " 実行前に本当に問題ないか、必ず確認してください。"
)

col_reset = st.columns([2, 2, 3])
with col_reset[0]:
    really = st.checkbox("実行内容を理解した", key="chk_really_reset")
with col_reset[1]:
    confirm_text = st.text_input("確認のため `RESET` と入力", "", key="txt_reset_confirm")
with col_reset[2]:
    st.write("手順: `git fetch origin` → `git reset --hard origin/<branch>`")
    st.caption("※ ブランチは各リポジトリの現在ブランチ（なければ main）を自動使用")

if st.button("💥 強制リセットを実行（選択分）", key="btn_force_reset"):
    if not git_targets:
        st.warning("⚠️ Git リポジトリが選択されていません。")
    elif not really or confirm_text.strip().upper() != "RESET":
        st.error("確認が未完了です。『実行内容を理解した』にチェックし、`RESET` と入力してください。")
    else:
        for rec in git_targets:
            repo_path = rec["path"]
            repo_name = rec["name"]
            st.markdown(f"**{repo_name}** — `{repo_path}`")

            # origin 設定確認
            code_r, out_r, err_r = git("remote", cwd=repo_path)
            if code_r != 0 or "origin" not in (out_r or ""):
                st.error("origin が設定されていないためスキップ（`git remote add origin ...` が必要）")
                continue

            # fetch → reset --hard
            code1, out1, err1 = git("fetch origin", cwd=repo_path)
            st.code(out1 or err1 or "(no output)", language="bash")

            branch = (rec.get("branch") or "main")
            remote_ref = shlex.quote(f"origin/{branch}")
            code2, out2, err2 = git(f"reset --hard {remote_ref}", cwd=repo_path)
            st.code(out2 or err2 or "(no output)", language="bash")

            if code1 == 0 and code2 == 0:
                st.success(f"✅ {repo_name}: origin/{branch} に強制同期しました。")
            else:
                st.error(f"❌ {repo_name}: リセットに失敗しました。ログを確認してください。")

        st.info("🔁 必要なら『ステータス再読み込み』ボタンで最新状態を反映してください。")
