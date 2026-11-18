"""ディスク状態ページ専用。読取専用の設定解決・容量計測（Streamlit 非依存）。"""
from __future__ import annotations

import io
import os
import platform
import plistlib
import re
import shutil
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def now_jst() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")


def human_size(value: int | float | None) -> str:
    if value is None:
        return "未計測"
    for unit, divisor in [("TiB", 1024**4), ("GiB", 1024**3), ("MiB", 1024**2)]:
        if value >= divisor:
            return f"{value / divisor:,.2f} {unit}"
    return f"{value / 1024:,.1f} KiB"


def judge(percent: float | None) -> tuple[str, str]:
    if percent is None:
        return "確認できません", "unknown"
    if percent >= 90:
        return "要対応", "error"
    if percent >= 80:
        return "注意", "warning"
    return "余裕あり", "success"


def run_command(args: list[str], timeout: int = 15) -> tuple[int, bytes, str]:
    try:
        result = subprocess.run(
            args, capture_output=True, check=False, timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
        return result.returncode, result.stdout, result.stderr.decode("utf-8", "replace").strip()
    except subprocess.TimeoutExpired:
        return 124, b"", f"{timeout}秒で時間切れになりました。"
    except OSError as exc:
        return 1, b"", str(exc)


def _read_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def read_targets(projects_root: Path) -> tuple[str, list[dict]]:
    """保存処理用 resolver の st.stop を呼ばず、同じ正本を監視用に読む。

    誤設定時の代替保存先は作らない。各対象のエラーとして表示を継続する。
    """
    projects_root = projects_root.resolve()
    targets = [{"name": "projects", "path": str(projects_root), "mode": "projects", "error": ""}]
    config_root = projects_root / "command_station_project/command_station_app/.streamlit"
    config_error = ""
    location = "設定未確認"
    try:
        secrets = _read_toml(config_root / "secrets.toml")
        location = secrets["env"]["location"]
        if not isinstance(location, str) or not location.strip():
            raise ValueError("[env].location が未設定です。")
        location = location.strip()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        secrets = {}
        config_error = f"secrets.toml の確認が必要です：{exc}"

    for name, key in [("Storages", "storages"), ("InBoxStorages", "inbox"), ("Archive", "archive"), ("Databases", "databases")]:
        row = {"name": name, "path": "", "mode": "", "error": config_error}
        if not config_error:
            try:
                mode = secrets[key]["mode"]
                if mode not in ("internal", "external"):
                    raise ValueError(f"[{key}].mode は internal / external を指定してください。")
                row["mode"] = mode
                if mode == "internal":
                    path = projects_root / name
                else:
                    config = _read_toml(config_root / "storage.toml")
                    value = config[key]["storage"]["external"][location]["root"]
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(f"{name} の外部保存先が未設定です。")
                    path = Path(value.strip())
                    if not path.is_absolute():
                        raise ValueError(f"{name} の保存先を絶対パスで指定してください。")
                row["path"] = str(path)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                row["error"] = f"{name} の設定を確認してください：{exc}"
        targets.append(row)
    for target in targets:
        target["error"] = target["error"] or target_error(target)
    return location, targets


def read_monitor_routes(projects_root: Path, location: str, targets: list[dict]) -> list[dict]:
    """現在の環境で使用する main と、PAIS の backup / backup2 / sync のみ。"""
    routes = [{**row, "kind": "main"} for row in targets]
    path = projects_root / "command_station_project/command_station_app/.streamlit/storage.toml"
    try:
        config = _read_toml(path)
    except (OSError, ValueError) as exc:
        routes.append({"name": "バックアップ・同期先の設定", "kind": "config", "path": "", "error": str(exc)})
        return routes
    for key, name in [("storage", "Storages"), ("inbox", "InBoxStorages"), ("archive", "Archive"), ("databases", "Databases")]:
        for role in ("backup", "backup2", "sync"):
            table = config.get(key, {}).get(role, {}).get(location)
            if table is None:
                continue
            value = table.get("root") if isinstance(table, dict) else None
            row = {"name": f"{name}（{role}）", "path": "", "kind": role, "error": ""}
            if not isinstance(value, str) or not value.strip() or not Path(value.strip()).is_absolute():
                row["error"] = f"[{key}.{role}.{location}].root を絶対パスで指定してください。"
            else:
                row["path"] = value.strip()
                row["error"] = target_error(row)
            routes.append(row)
    return routes


def target_error(target: dict) -> str:
    if target.get("error"):
        return target["error"]
    if not target.get("path"):
        return "保存先が未設定です。"
    path = Path(target["path"])
    try:
        if path.parts[:2] == ("/", "Volumes") and len(path.parts) >= 3:
            volume = Path(*path.parts[:3])
            if not os.path.ismount(volume):
                return f"未接続：{volume} がマウントされていません。"
        if not path.is_dir():
            return "フォルダーが見つかりません（未接続・未作成の可能性）。"
    except OSError as exc:
        return str(exc)
    return ""


def parse_df(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines()[1:]:
        # POSIX df -kP。マウント先に空白を含む場合も維持する。
        match = re.match(r"^(.*?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)%\s+(.+)$", line)
        if match:
            fs, total, used, free, percent, mount = match.groups()
            rows.append({"filesystem": fs, "mount": mount, "total": int(total) * 1024})
    return rows


def disk_usage(path: Path) -> dict:
    total, _used, free = shutil.disk_usage(path)
    if total <= 0 or free < 0 or free > total:
        raise ValueError("容量を正しく取得できませんでした。")
    # APFS のボリューム単独の Used ではなく、全容量から空きを引く。
    used = total - free
    percent = used / total * 100
    status, level = judge(percent)
    return {"total": total, "used": used, "free": free, "percent": percent,
            "status": status, "level": level}


def collect_disks(routes: tuple[tuple[str, str], ...] = ()) -> dict:
    measured_at = now_jst()
    code, raw, error = run_command(["df", "-kP"], 15)
    text = raw.decode("utf-8", "replace")
    diagnostic = [f"df：{error or '取得失敗'}"] if code else []
    parsed = parse_df(text)
    if not code and not parsed:
        code = 1
        diagnostic.append("df の一覧を読み取れませんでした。")
    candidates = [{"mount": "/", "filesystem": "", "total": 0}]
    # 接続されているだけの無関係なディスクを表示・総合判定へ混ぜない。
    route_devices = {}
    for label, path in routes:
        if path and not target_error({"path": path}):
            try:
                device = Path(path).resolve().stat().st_dev
                route_devices.setdefault(device, []).append(label)
            except (OSError, RuntimeError):
                pass
    for row in parsed:
        mount = row["mount"]
        if platform.system() == "Darwin":
            include = mount.startswith("/Volumes/")
        else:
            include = mount.startswith(("/mnt/", "/media/", "/Volumes/"))
        if include and row["total"] > 0:
            try:
                if Path(mount).stat().st_dev in route_devices:
                    candidates.append(row)
            except OSError:
                pass
    disks = []
    groups = {}
    for candidate in candidates:
        mount = candidate["mount"]
        is_main = mount == "/"
        sample = Path("/System/Volumes/Data") if is_main and platform.system() == "Darwin" else Path(mount)
        if not sample.is_dir():
            sample = Path(mount)
        row = {"name": "本体SSD" if is_main else Path(mount).name, "mounts": [mount],
               "sample_path": str(sample), "device_ids": [], "is_main": is_main,
               "error": "", "measured_at": measured_at, "purposes": []}
        try:
            row.update(disk_usage(sample))
            row["device_ids"] = list({sample.stat().st_dev, Path(mount).stat().st_dev})
            row["purposes"] = sorted({label for device in row["device_ids"] for label in route_devices.get(device, [])})
            group = f"device:{sample.stat().st_dev}"
            if platform.system() == "Darwin":
                rc, data, err = run_command(["diskutil", "info", "-plist", str(sample)], 4)
                if rc == 0:
                    try:
                        info = plistlib.loads(data)
                        container = info.get("APFSContainerReference")
                        if container:
                            group = f"apfs:{container}"
                    except (ValueError, plistlib.InvalidFileException):
                        diagnostic.append(f"{mount}：APFS情報を解析できませんでした。")
                else:
                    diagnostic.append(f"{mount}：APFS共有領域の確認を省略（{err}）。")
            if group in groups:
                existing = groups[group]
                existing["mounts"].append(mount)
                existing["device_ids"] = sorted(set(existing["device_ids"] + row["device_ids"]))
                existing["purposes"] = sorted(set(existing["purposes"] + row["purposes"]))
                if not existing["is_main"]:
                    existing["name"] += " / " + row["name"]
                continue
            row["id"] = group
            groups[group] = row
        except (OSError, ValueError) as exc:
            row.update({"id": mount, "error": str(exc), "percent": None,
                        "status": "確認できません", "level": "unknown"})
        disks.append(row)
    mounts = {mount for row in disks for mount in row["mounts"]} | {"/System/Volumes/Data"}
    scoped_lines = text.splitlines()[:1]
    for line in text.splitlines()[1:]:
        parsed_line = parse_df("header\n" + line)
        if parsed_line and parsed_line[0]["mount"] in mounts:
            scoped_lines.append(line)
    return {"disks": disks, "measured_at": measured_at, "errors": diagnostic,
            "enumeration_error": bool(code), "df_raw": "\n".join(scoped_lines)}


def scan_folder(path: Path, depth: int, timeout: int) -> dict:
    result = {"path": str(path), "total": None, "rows": {}, "ok": False,
              "error": "", "device": None, "measured_at": now_jst()}
    try:
        path = path.resolve()
        result["path"] = str(path)
        problem = target_error({"path": str(path)})
        if problem:
            result["error"] = problem
            return result
        device = path.stat().st_dev
        result["device"] = device
        # 別ディスクへは跨がず、子シンボリックリンクの先も辿らない。
        args = ["du", "-k", "-P", "-x"]
        args += ["-d", str(depth)] if platform.system() == "Darwin" else [f"--max-depth={depth}"]
        code, raw, error = run_command(args + [str(path)], timeout)
        for line in raw.decode("utf-8", "replace").splitlines():
            fields = line.split("\t", 1)
            if len(fields) != 2 or not fields[0].isdigit():
                continue
            entry = Path(fields[1])
            try:
                entry.relative_to(path)
            except ValueError:
                continue
            result["rows"][str(entry)] = int(fields[0]) * 1024
        result["total"] = result["rows"].get(str(path))
        if code or result["total"] is None:
            result["error"] = error or "合計容量を取得できませんでした。"
        elif path.stat().st_dev != device:
            result["error"] = "計測中に保存先の接続が変わりました。再計測してください。"
        else:
            result["ok"] = True
    except (OSError, ValueError, RuntimeError) as exc:
        result["error"] = str(exc)
    result["measured_at"] = now_jst()
    return result


def scan_overview(targets: list[dict], timeout: int, progress=None) -> dict:
    results = {}
    for index, target in enumerate(targets):
        if progress:
            progress(index, len(targets), target["name"])
        problem = target_error(target)
        if problem:
            results[target["name"]] = {"path": target["path"], "total": None, "rows": {},
                "device": None, "ok": False, "error": problem, "measured_at": now_jst()}
            continue
        try:
            path = Path(target["path"]).resolve()
            device = path.stat().st_dev
        except (OSError, RuntimeError) as exc:
            results[target["name"]] = {"path": target["path"], "total": None, "rows": {},
                "device": None, "ok": False, "error": str(exc), "measured_at": now_jst()}
            continue
        # projects の走査で得られた直下フォルダーは再走査しない。
        source = next((r for r in results.values() if r["ok"] and
                       str(path) in r["rows"] and r["device"] == device), None)
        if source is not None:
            results[target["name"]] = {**source, "path": str(path),
                "total": source["rows"][str(path)], "rows": {str(path): source["rows"][str(path)]}}
        else:
            results[target["name"]] = scan_folder(path, 1 if target["name"] == "projects" else 0, timeout)
    return results


def exclusive_parts(results: dict) -> tuple[list[dict], str]:
    """計測済み対象を入れ子分だけ差し引き、二重計上しない表示用内訳へ。"""
    groups = {}
    for name, row in results.items():
        if row.get("ok"):
            key = (row["path"], row["device"])
            if key not in groups:
                groups[key] = {"names": [], "path": row["path"], "device": row["device"], "bytes": row["total"]}
            groups[key]["names"].append(name)
    parts = []
    for key, item in groups.items():
        parent = Path(item["path"])
        children = [child for child in groups.values() if child["device"] == item["device"]
                    and Path(child["path"]) != parent and parent in Path(child["path"]).parents]
        direct = [child for child in children if not any(
            other is not child and Path(other["path"]) in Path(child["path"]).parents for other in children)]
        amount = item["bytes"] - sum(child["bytes"] for child in direct)
        if amount < 0:
            return [], "計測時刻の差や共有ファイルの影響で内訳が合計を超えています。再計測してください。"
        parts.append({**item, "bytes": amount, "label": " / ".join(item["names"]) + ("（他の表示項目を除く）" if direct else "")})
    return parts, ""


def breakdown(result: dict) -> tuple[list[dict], list[dict]]:
    """depth=2 の du 結果を直下ユーザー、ユーザー直下の分類へ分解。"""
    if not result or not result.get("ok"):
        return [], []
    root = Path(result["path"])
    users, children = [], []
    for value, size in result["rows"].items():
        relative = Path(value).relative_to(root)
        if len(relative.parts) == 1:
            name = relative.parts[0]
            common = name.startswith(("_", ".")) or name == "logs"
            users.append({"user": name, "kind": "共通・管理" if common else "ユーザー", "bytes": size})
        elif len(relative.parts) == 2:
            children.append({"user": relative.parts[0], "category": relative.parts[1], "bytes": size})
    root_files = max(0, result["total"] - sum(r["bytes"] for r in users))
    if root_files:
        users.append({"user": "（直下ファイル等）", "kind": "共通・管理", "bytes": root_files})
    for user in users:
        if user["user"] == "（直下ファイル等）":
            continue
        remainder = max(0, user["bytes"] - sum(r["bytes"] for r in children if r["user"] == user["user"]))
        if remainder:
            children.append({"user": user["user"], "category": "（直下ファイル等）", "bytes": remainder})
    return sorted(users, key=lambda r: -r["bytes"]), children


def aggregate_children(children: list[dict], user: str | None = None) -> list[dict]:
    totals = {}
    for row in children:
        if user is None or row["user"] == user:
            totals[row["category"]] = totals.get(row["category"], 0) + row["bytes"]
    return [{"category": name, "bytes": size} for name, size in sorted(totals.items(), key=lambda item: -item[1])]


def excel_bytes(sheets: dict[str, list[dict]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        if not rows:
            sheet.append(["未計測、または対象なし"])
            continue
        columns = list(dict.fromkeys(key for row in rows for key in row))
        sheet.append(columns)
        for row in rows:
            sheet.append([row.get(key) for key in columns])
        # フォルダー名などが Excel の数式として実行されないようにする。
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="334155")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for index, column in enumerate(sheet.columns, 1):
            sheet.column_dimensions[get_column_letter(index)].width = min(72, max(16, max(len(str(c.value or "")) for c in column) + 2))
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()
