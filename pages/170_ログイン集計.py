# -*- coding: utf-8 -*-
"""
170_ログイン集計.py

管理者向け：
- 現在の同時ログイン数（ユーザー / セッション）
- app別の同時ログイン状況
- 時系列（1分粒度）
- 時間帯別・曜日別の利用傾向
- ユーザー別・app別の日次利用量

前提：
- 正本DB : projects/Storages/_admin/sessions/sessions.db
- 共通ロジック : common_lib.sessions
- 時刻 : JST 固定
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st

# ============================================================
# ページ設定
# ============================================================
st.set_page_config(
    page_title="📊 ログイン集計（管理）",
    page_icon="📊",
    layout="wide",
)

st.title("📊 ログイン集計（管理）")
st.caption("同時ログイン数・時間帯別/曜日別傾向・ユーザー別利用状況")

# ============================================================
# sys.path 調整（common_lib を import 可能に）
# ============================================================
_THIS = Path(__file__).resolve()
PROJECTS_ROOT = _THIS.parents[3]  # pages → command_station_app → command_station_project → projects
import sys
if str(PROJECTS_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECTS_ROOT))

# ============================================================
# 共通ライブラリ
# ============================================================
from common_lib.sessions import (
    SessionConfig,
    get_active_counts,
)
from common_lib.sessions.db import ensure_db

# ============================================================
# DB パス解決（確定事項）
# ============================================================
SESSIONS_DB = (
    PROJECTS_ROOT
    / "Storages"
    / "_admin"
    / "sessions"
    / "sessions.db"
)

cfg = SessionConfig()

# ============================================================
# DB 接続
# ============================================================
con = ensure_db(SESSIONS_DB)

# ============================================================
# ① 現在の同時ログイン数（全app合計）
# ============================================================
st.subheader("🟢 現在の同時ログイン状況")

current = get_active_counts(
    db_path=SESSIONS_DB,
    cfg=cfg,
)

c1, c2 = st.columns(2)
with c1:
    st.metric("同時ログイン人数", current["active_users"])
with c2:
    st.metric("同時セッション数", current["active_sessions"])

# ============================================================
# ② app別 同時ログイン数
# ============================================================
st.divider()
st.subheader("📦 app別 同時ログイン人数（現在）")

df_apps = pd.read_sql(
    """
    SELECT
      app_name,
      COUNT(DISTINCT user_sub) AS active_users,
      COUNT(*) AS active_sessions
    FROM session_state
    WHERE logout_at IS NULL
      AND last_seen >= datetime('now', 'localtime', printf('-%d seconds', ?))
    GROUP BY app_name
    ORDER BY active_users DESC
    """,
    con,
    params=(cfg.ttl_sec,),
)

if df_apps.empty:
    st.info("現在アクティブなログインはありません。")
else:
    st.dataframe(df_apps, width="stretch", hide_index=True)

# ============================================================
# ③ 時系列（直近24時間）
# ============================================================
st.divider()
st.subheader("📈 同時ログイン数の推移（直近24時間）")

df_ts = pd.read_sql(
    """
    SELECT
      bucket_ts,
      app_name,
      active_users,
      peak_users
    FROM active_samples
    WHERE bucket_ts >= datetime('now', 'localtime', '-24 hours')
    ORDER BY bucket_ts ASC
    """,
    con,
    parse_dates=["bucket_ts"],
)

if df_ts.empty:
    st.info("時系列データがまだありません。")
else:
    st.line_chart(
        df_ts.pivot(index="bucket_ts", columns="app_name", values="active_users"),
        height=300,
    )

# ============================================================
# ④ 時間帯別（平均・ピーク）
# ============================================================
st.divider()
st.subheader("⏰ 時間帯別 同時ログイン人数")

df_hour = pd.read_sql(
    """
    SELECT
      CAST(strftime('%H', bucket_ts) AS INTEGER) AS hour,
      app_name,
      AVG(active_users) AS avg_users,
      MAX(peak_users) AS peak_users
    FROM active_samples
    GROUP BY hour, app_name
    ORDER BY hour
    """,
    con,
)

if df_hour.empty:
    st.info("時間帯別データがまだありません。")
else:
    st.dataframe(df_hour, width="stretch", hide_index=True)

# ============================================================
# ⑤ 曜日別（平均・ピーク）
# ============================================================
st.divider()
st.subheader("📅 曜日別 同時ログイン人数")

df_weekday = pd.read_sql(
    """
    SELECT
      CAST(strftime('%w', bucket_ts) AS INTEGER) AS weekday,
      app_name,
      AVG(active_users) AS avg_users,
      MAX(peak_users) AS peak_users
    FROM active_samples
    GROUP BY weekday, app_name
    ORDER BY weekday
    """,
    con,
)

weekday_map = {
    0: "日",
    1: "月",
    2: "火",
    3: "水",
    4: "木",
    5: "金",
    6: "土",
}

if df_weekday.empty:
    st.info("曜日別データがまだありません。")
else:
    df_weekday["weekday"] = df_weekday["weekday"].map(weekday_map)
    st.dataframe(df_weekday, width="stretch", hide_index=True)

# ============================================================
# ⑥ ユーザー別 × app別 日次利用量
# ============================================================
st.divider()
st.subheader("👤 ユーザー別 × app別 利用量（日次）")

df_user = pd.read_sql(
    """
    SELECT
      date,
      user_sub,
      app_name,
      active_minutes
    FROM user_app_daily
    ORDER BY date DESC, active_minutes DESC
    LIMIT 500
    """,
    con,
)

if df_user.empty:
    st.info("ユーザー別集計データがまだありません。")
else:
    st.dataframe(df_user, width="stretch", hide_index=True)

# ============================================================
# クローズ
# ============================================================
con.close()

st.caption("※ 時刻はすべて JST。active_minutes は 1分粒度のサンプルに基づく値です。")
