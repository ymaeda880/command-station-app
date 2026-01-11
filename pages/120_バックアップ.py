# -*- coding: utf-8 -*-
# command_station_app/pages/73_バックアップ.py
"""
Storage / 認証データ バックアップ用 Streamlit ページ

本ページは、PREC AI / command_station_app において、
プロジェクト配下の重要データを外付け SSD に rsync で安全にバックアップするための
管理者向けユーティリティである。

────────────────────────────────────────────
【バックアップ対象（論理単位）】
- storages:
    <project_root>/Storages
- auth:
    <project_root>/auth_portal_project/auth_portal_app/data

※ 両者は完全に分離したディレクトリとして保存される

────────────────────────────────────────────
【バックアップ先構造】
<SSD_MOUNT>/aisv_Backups/backups/
  ├─ storages/
  │   ├─ latest/        （常に最新状態：--delete 付きで完全同期）
  │   ├─ daily/
  │   │   └─ YYYY-MM-DD_HHMMSS/ （日次スナップショット）
  │   └─ logs/
  └─ auth/
      ├─ latest/
      ├─ daily/
      └─ logs/

────────────────────────────────────────────
【latest / daily の意味】
- latest:
    rsync --delete により「完全ミラー」を維持
    → 不要ファイルは削除される（不可逆）

- daily:
    スナップショット保存
    --link-dest=latest を使用することで
    実体は差分のみ（ハードリンク）となり容量を節約可能

────────────────────────────────────────────
【設定ファイル要件】

1. secrets.toml（必須）
    [env]
    location = "xxx"

2. settings.toml（必須）
    [locations.<location>]
    project_root = "/absolute/path/to/projects"

    [app]
    ssd1 = "VolumeName_or_/absolute/path"
    ssd2 = "VolumeName_or_/absolute/path"   # 任意

※ project_root / ssd 設定が欠けている場合は即停止する
※ 暗黙のデフォルト値は一切使用しない設計

────────────────────────────────────────────
【SSD 判定ロジック】
- "/Volumes/<label>" または 絶対パス をマウント先として解釈
- 接続中 SSD のみ実行ボタンを有効化
- 複数 SSD が設定されている場合、個別に実行可能

────────────────────────────────────────────
【安全設計】
- 実行前に明示的な確認チェックを要求
- Dry-run モードあり（rsync --dry-run）
- latest / daily 失敗時は即中断
- 失敗・成功ログを JSON で保存
- 同時実行防止（session_state["backup_running"]）

────────────────────────────────────────────
【注意】
- latest は --delete を伴うため不可逆操作である
- 誤った SSD を選択すると内容が上書きされる
- 本ページは管理者・運用者専用を前提とする

────────────────────────────────────────────
【依存要件】
- Python 3.11 以上（tomllib 使用）
- rsync コマンドが利用可能であること
- Streamlit 実行環境

"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import shlex
import subprocess

import streamlit as st

from lib.backup.explanation import render_backup_explanation

# -----------------------------
# TOML reader (py3.11+: tomllib)
# -----------------------------
try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None


# ============================
# 固定パス
# ============================
APP_DIR = Path(__file__).resolve().parents[1]
STREAMLIT_DIR = APP_DIR / ".streamlit"
SETTINGS_TOML = STREAMLIT_DIR / "settings.toml"


# ============================
# 共通ユーティリティ
# ============================
@dataclass
class RunResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]


def load_toml_required(path: Path) -> dict:
    if tomllib is None:
        raise RuntimeError("tomllib が利用できません（Python 3.11+ 必須）")
    if not path.exists():
        raise FileNotFoundError(f"{path} が存在しません")
    return tomllib.loads(path.read_text(encoding="utf-8"))


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


def mounted_volume_path(v: str) -> Path:
    return Path(v) if v.startswith("/") else (Path("/Volumes") / v)


def is_connected_mount(p: Path) -> bool:
    return p.exists() and p.is_dir()


# ============================
# UI
# ============================
st.set_page_config(page_title="Storageバックアップ", page_icon="💾", layout="centered")
st.title("💾 Storageバックアップ（latest + daily）")

# 表示したい位置で
render_backup_explanation()

st.caption("SSD内 aisv_Backups/backups/ に storages / auth を分離して保存します。")

# --- secrets.toml
loc = st.secrets.get("env", {}).get("location")
if not loc:
    st.error('secrets.toml の [env].location が未設定です')
    st.stop()

st.write(f"- location: **{loc}**")

# --- settings.toml
try:
    settings = load_toml_required(SETTINGS_TOML)
except Exception as e:
    st.error(f"settings.toml 読み込み失敗：{e}")
    st.stop()

loc_cfg = settings.get("locations", {}).get(loc)
if not isinstance(loc_cfg, dict):
    st.error(f"settings.toml に [locations.{loc}] がありません")
    st.stop()

project_root = loc_cfg.get("project_root")
if not project_root:
    st.error(f"locations.{loc}.project_root が未設定です")
    st.stop()

project_root = Path(project_root)
st.write(f"- project_root: `{project_root}`")

# ============================
# バックアップ対象（論理単位）
# ============================
BACKUP_SETS = [
    {
        "name": "storages",
        "src": project_root / "Storages",
    },
    {
        "name": "auth",
        "src": project_root / "auth_portal_project" / "auth_portal_app" / "data",
    },
]

# 事前存在チェック
for s in BACKUP_SETS:
    if not s["src"].exists():
        st.error(f"バックアップ元が存在しません: {s['src']}")
        st.stop()

# ============================
# SSD 設定（共通・必須）
# ============================
backup_cfg = settings.get("backup", {})
ssd_cfg = backup_cfg.get("ssd", {})

ssd1 = ssd_cfg.get("ssd1")
ssd2 = ssd_cfg.get("ssd2")

if not ssd1 and not ssd2:
    st.error("settings.toml の [app] に ssd1 / ssd2 を設定してください")
    st.stop()

ssd_items: list[tuple[str, Path | None]] = []
for label in (ssd1, ssd2):
    if not label:
        continue
    mount = mounted_volume_path(str(label))
    ssd_items.append((str(label), mount if is_connected_mount(mount) else None))

st.divider()
st.write("### バックアップ先SSD")

for label, mount in ssd_items:
    if mount:
        st.success(f"✅ {label}：接続中（{mount}）")
    else:
        st.warning(f"⚠️ {label}：未接続（期待: {mounted_volume_path(label)}）")

# ============================
# オプション
# ============================
st.divider()
use_link_dest = st.checkbox("daily は差分（--link-dest）で節約", value=True)
dry_run = st.checkbox("Dry-run（コピーせず表示のみ）", value=False)
confirm = st.checkbox(
    "確認：選択したSSDに latest（--delete）と daily を作成します（不可逆）",
    value=False
)

if "backup_running" not in st.session_state:
    st.session_state["backup_running"] = False

# ============================
# 実行
# ============================
st.divider()
cols = st.columns(len(ssd_items))
clicked: Path | None = None

for i, (label, mount) in enumerate(ssd_items):
    with cols[i]:
        disabled = (mount is None) or st.session_state["backup_running"]
        if st.button(f"{label} へバックアップ", disabled=disabled, type="primary"):
            clicked = mount


def backup_all(mount: Path) -> None:
    st.session_state["backup_running"] = True
    try:
        root = mount / "aisv_Backups" / "backups"
        ensure_dir(root)

        rsync_base = ["rsync", "-a"]
        if dry_run:
            rsync_base.append("--dry-run")

        for s in BACKUP_SETS:
            name = s["name"]
            src = s["src"]

            base = root / name
            latest = base / "latest"
            daily = base / "daily" / now_stamp()
            logs = base / "logs"

            ensure_dir(latest)
            ensure_dir(daily)
            ensure_dir(logs)

            # latest
            cmd_latest = rsync_base + ["--delete", str(src) + "/", str(latest) + "/"]
            st.write(f"#### {name} / latest")
            st.code(fmt_cmd(cmd_latest), language="bash")
            r1 = sh(cmd_latest)

            if not r1.ok:
                logp = logs / f"{now_stamp()}_latest_failed.json"
                logp.write_text(json.dumps({
                    "cmd": r1.cmd,
                    "stderr": r1.stderr,
                }, ensure_ascii=False, indent=2))
                st.error(f"{name}: latest 失敗")
                return

            # daily
            cmd_daily = rsync_base.copy()
            if use_link_dest:
                cmd_daily += ["--link-dest", str(latest)]
            cmd_daily += [str(src) + "/", str(daily) + "/"]

            st.write(f"#### {name} / daily")
            st.code(fmt_cmd(cmd_daily), language="bash")
            r2 = sh(cmd_daily)

            logp = logs / f"{now_stamp()}_backup.json"
            logp.write_text(json.dumps({
                "cmd_latest": r1.cmd,
                "cmd_daily": r2.cmd,
                "ok": r1.ok and r2.ok,
            }, ensure_ascii=False, indent=2))

            if not r2.ok:
                st.error(f"{name}: daily 失敗")
                return

        st.success("すべてのバックアップが完了しました")

    finally:
        st.session_state["backup_running"] = False


if clicked:
    if not confirm:
        st.error("確認チェックをオンにしてください")
    else:
        backup_all(clicked)

st.caption("※ storages / auth は完全に分離して保存されます")
