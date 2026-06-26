# -*- coding: utf-8 -*-
"""
内外装仕様一覧表メーカー — Streamlit 版エントリポイント

役割:
  - 既存の「仕様一覧表メーカー.html」をブラウザに表示
  - OCRサーバー（ocr_server.py）をバックグラウンドで自動起動（黒い画面なし）
  - APIキーは .streamlit/secrets.toml から読み込み（安全管理）

起動方法:
  streamlit run streamlit_app.py
"""
import os
import sys
import subprocess
import atexit
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ============================================================
# ページ設定
# ============================================================
st.set_page_config(
    page_title="内外装仕様一覧表メーカー",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Streamlitの上下余白とメニューを最小化（HTMLを画面いっぱいに）
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 0rem;
        padding-bottom: 0rem;
        padding-left: 0.5rem;
        padding-right: 0.5rem;
        max-width: 100%;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    iframe {border: none;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# APIキー: st.secrets と .env の両方をサポート
# ============================================================
HERE = Path(__file__).parent.resolve()

# 1) Streamlit Cloud などで secrets.toml がある場合
try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    # secrets.toml が無い場合は黙ってスキップ（ローカル開発では .env を使う）
    pass

# 2) ローカル開発時のフォールバック：.env からも読む
if "ANTHROPIC_API_KEY" not in os.environ and (HERE / ".env").exists():
    with open(HERE / ".env", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if k.strip() not in os.environ:
                os.environ[k.strip()] = v


# ============================================================
# OCRサーバーをバックグラウンドで起動（初回のみ）
# ============================================================
@st.cache_resource
def start_ocr_server():
    """ocr_server.py を別プロセスで起動。Windowsでは黒画面を出さない。"""
    creationflags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW: 子プロセスのコンソールウィンドウを表示しない
        creationflags = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(
        [sys.executable, str(HERE / "ocr_server.py")],
        env=os.environ.copy(),
        cwd=str(HERE),
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Streamlitアプリ終了時に OCRサーバーも止める
    def _cleanup():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    atexit.register(_cleanup)
    return proc


ocr_proc = start_ocr_server()


# ============================================================
# 静的ファイルサーバーをバックグラウンドで起動
# （HTMLと画像・CSS・JSの相対パスを正しく解決させるため）
# ============================================================
STATIC_PORT = 8731


@st.cache_resource
def start_static_server():
    """画像・HTMLを配信するための http.server を別プロセスで起動（黒画面なし）。"""
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(STATIC_PORT), "--bind", "127.0.0.1"],
        cwd=str(HERE),
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def _cleanup():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    atexit.register(_cleanup)
    return proc


static_proc = start_static_server()


# ============================================================
# 既存HTMLを iframe 経由で表示（画像も含めて静的サーバーから配信）
# ============================================================
import urllib.parse

html_url = f"http://localhost:{STATIC_PORT}/" + urllib.parse.quote("仕様一覧表メーカー.html")

# iframeで全画面表示
components.html(
    f"""
    <iframe
        src="{html_url}"
        style="width:100%; height:100vh; min-height:2400px; border:none;"
    ></iframe>
    """,
    height=2400,
    scrolling=True,
)
