# lib/app_manager.py
# ============================================================
# アプリの起動・停止ユーティリティ
# - lsof/kill を用いた複数 PID 安全停止
# - <app>_project/<app>_app 規約に基づく app_spec_list
# - Streamlit を baseUrlPath/port 指定で nohup 起動
# ============================================================

from __future__ import annotations
from pathlib import Path
from typing import List, Tuple
import subprocess
import textwrap
import time
import os
import re
import signal

# ---------- サブプロセス ----------
def run(cmd: str | list[str], shell: bool = False) -> tuple[int, str]:
    """サブプロセス実行（stdout+stderr を結合して返す）"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, shell=shell)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except Exception as e:
        return 1, f"[Exception] {e}"

# ---------- 共通ユーティリティ ----------
def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def is_pid_running(pid: int) -> bool:
    """PID が生存しているか（signal=0 で存在確認）"""
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def parse_pids(pid_txt: str) -> List[int]:
    """'1393\\n2604\\n2629' のような文字列から PID(int) の配列を返す。空白・非数は除去。"""
    if not pid_txt:
        return []
    return [int(t) for t in re.findall(r"\d+", pid_txt)]

def kill_pids(pids: List[int], grace_sec: float = 3.0) -> Tuple[bool, str]:
    """複数 PID を安全停止（SIGTERM→待機→必要なら SIGKILL）"""
    if not pids:
        return False, "PIDが見つかりませんでした。"

    # SIGTERM
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            return False, f"SIGTERM送信中に例外: pid={pid} err={e}"

    time.sleep(grace_sec)

    # 生存チェック → SIGKILL
    still = []
    for pid in pids:
        try:
            os.kill(pid, 0)
            still.append(pid)
        except ProcessLookupError:
            pass

    for pid in still:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception as e:
            return False, f"SIGKILL送信中に例外: pid={pid} err={e}"

    return True, f"停止OK: term={pids}" + (f", kill={still}" if still else "")

def find_pids_by_port(port: int) -> list[int]:
    """lsof -ti tcp:<port> の結果（複数行可）を配列で返す。見つからない場合は空配列。"""
    code, out = run(f"lsof -ti tcp:{int(port)} || true", shell=True)
    return parse_pids(out)

# ---------- スペック生成 ----------
def app_spec_list(settings: dict, app_map: dict) -> list[dict]:
    """
    nginx.toml の enabled=true のアプリを配列で返す。
    規約: <project_root>/<app>_project/<app>_app/ に app.py と .venv/ が存在。
    """
    loc = settings["env"]["location"]
    project_root = Path(settings["locations"][loc]["project_root"])
    specs = []
    for name, cfg in app_map.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", True):
            continue
        port = int(cfg.get("port", 0))
        if not port:
            continue

        app_dir = project_root / f"{name}_project" / f"{name}_app"
        venv_activate = app_dir / ".venv" / "bin" / "activate"
        app_py = app_dir / "app.py"
        pid_dir = app_dir / ".run"
        pid_file = pid_dir / f"{name}.pid"
        log_dir = app_dir / "logs"
        log_file = log_dir / f"{name}.log"

        specs.append(dict(
            name=name, port=port,
            app_dir=app_dir, venv_activate=venv_activate, app_py=app_py,
            pid_dir=pid_dir, pid_file=pid_file, log_dir=log_dir, log_file=log_file
        ))
    return specs

# ---------- 起動/停止 ----------
def start_one_app(spec: dict) -> tuple[bool, str]:
    """
    仮想環境を有効化し、Streamlit を baseUrlPath/port 指定で起動（nohup バックグラウンド）
    成功時: (True, メッセージ)
    """
    app_dir: Path = spec["app_dir"]
    venv_activate: Path = spec["venv_activate"]
    app_py: Path = spec["app_py"]
    pid_dir: Path = spec["pid_dir"]
    pid_file: Path = spec["pid_file"]
    log_dir: Path = spec["log_dir"]
    log_file: Path = spec["log_file"]
    name: str = spec["name"]
    port: int = spec["port"]

    if not app_dir.exists():
        return False, f"[{name}] app_dir が見つかりません: {app_dir}"
    if not venv_activate.exists():
        return False, f"[{name}] 仮想環境が見つかりません: {venv_activate}"
    if not app_py.exists():
        return False, f"[{name}] エントリファイルが見つかりません: {app_py}"

    ensure_dir(pid_dir)
    ensure_dir(log_dir)

    # 既存の PID で動いていればスキップ
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            if is_pid_running(old_pid):
                return True, f"[{name}] 既に起動中 (pid={old_pid})"
        except Exception:
            pass

    # 既にポートで動いているプロセスがあれば、それもスキップ扱い
    existing_pids = find_pids_by_port(port)
    if existing_pids:
        return True, f"[{name}] port {port} ですでにプロセス稼働中 (pid={existing_pids})"

    # nohup 起動（baseUrlPath は name を利用）
    cmd = textwrap.dedent(f"""
        set -e
        cd "{app_dir}"
        . "{venv_activate}"
        nohup python -m streamlit run "{app_py.name}" \
          --server.baseUrlPath="{name}" \
          --server.port={port} \
          --server.headless=true \
          > "{log_file}" 2>&1 < /dev/null &
        echo $! > "{pid_file}"
    """).strip()

    code, out = run(["bash", "-lc", cmd])
    if code == 0:
        time.sleep(1.2)  # 少し待って PID 確認
        pid_txt = pid_file.read_text().strip() if pid_file.exists() else "?"
        return True, f"[{name}] 起動開始 OK (pid={pid_txt})\n  log: {log_file}"
    else:
        return False, f"[{name}] 起動失敗\n{out}"

def stop_one_app(spec: dict) -> tuple[bool, str]:
    """PID ファイル優先で停止。なければ port からも停止を試みる（複数PID対応）"""
    name: str = spec["name"]
    pid_file: Path = spec["pid_file"]
    port: int = spec["port"]

    # 1) PIDファイル優先
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
        except Exception:
            pid = None
        if pid and is_pid_running(pid):
            ok, msg = kill_pids([pid])
            if ok:
                try:
                    pid_file.unlink(missing_ok=True)
                except Exception:
                    pass
                return True, f"[{name}] 停止 OK (pid={pid})"
            else:
                return False, f"[{name}] 停止失敗 (pid={pid})\n{msg}"
        else:
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass

    # 2) ポートから検出（複数PID対応）
    pids = find_pids_by_port(port)
    if pids:
        ok, msg = kill_pids(pids)
        if ok:
            return True, f"[{name}] 停止 OK (port={port}, pid={pids})"
        else:
            return False, f"[{name}] 停止失敗 (port={port})\n{msg}"

    return True, f"[{name}] 稼働プロセスなし（何もしませんでした）"
