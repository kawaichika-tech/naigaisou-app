# -*- coding: utf-8 -*-
"""
内外装仕様一覧表メーカー — Streamlit 版エントリポイント（ローカル／Cloud 両対応）

動作モード:
  - ローカル：subprocess で OCRサーバ＋静的サーバを起動し、iframe 経由で表示
  - Streamlit Cloud：subprocess は使えないので、HTML を直接埋め込み・画像は GitHub Raw URL
    （HTML 側の IMG_BASE 変数を <script> で注入することで全画像パスを自動でフル URL に）

APIキーは .streamlit/secrets.toml（Cloud）または .env（ローカル）から読み込み。

起動方法:
  streamlit run streamlit_app.py
"""
import os
import sys
import subprocess
import atexit
import urllib.parse
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

try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

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
# 動作モード判定：HOSTNAME / マウントパス で Cloud か判定
# ============================================================
STATIC_PORT = 8731
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/kawaichika-tech/naigaisou-app/main/"


def _is_streamlit_cloud():
    if os.environ.get("HOSTNAME", "").startswith("streamlit-"):
        return True
    if str(HERE).startswith("/mount/src/"):
        return True
    return False


IS_CLOUD = _is_streamlit_cloud()


# ============================================================
# ローカル時：subprocess で OCRサーバ＋静的サーバを起動
# ============================================================
def _try_start(args, cwd):
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.Popen(
            args, env=os.environ.copy(), cwd=str(cwd),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None


@st.cache_resource
def start_local_servers():
    ocr = _try_start([sys.executable, str(HERE / "ocr_server.py")], HERE)
    static = _try_start(
        [sys.executable, "-m", "http.server", str(STATIC_PORT), "--bind", "127.0.0.1"],
        HERE,
    )

    def _cleanup():
        for p in (ocr, static):
            if p is None:
                continue
            if p.poll() is None:
                try:
                    p.terminate(); p.wait(timeout=3)
                except Exception:
                    try: p.kill()
                    except Exception: pass

    atexit.register(_cleanup)
    return {"ocr": ocr, "static": static}


# ============================================================
# HTML 読み込み＋IMG_BASE 注入（Cloud時）
# ============================================================
HTML_PATH = HERE / "仕様一覧表メーカー.html"


def _inject_img_base(html: str, base_url: str) -> str:
    """HTML の <head> 直後に IMG_BASE を window.__IMG_BASE__ として設定する <script> を注入。
    HTML 側の `const IMG_BASE = window.__IMG_BASE__ || ''` でこの値が拾われる。"""
    script_tag = f'<script>window.__IMG_BASE__ = "{base_url}";</script>'
    # <head> タグの直後に挿入
    if "<head>" in html:
        return html.replace("<head>", "<head>" + script_tag, 1)
    # <head> がなければ HTML の先頭に
    return script_tag + html


# ============================================================
# 表示：Cloud＝直接埋め込み＋IMG_BASE注入、ローカル＝iframe（http.server経由）
# ============================================================
if IS_CLOUD:
    with open(HTML_PATH, encoding="utf-8") as f:
        html_content = f.read()
    html_content = _inject_img_base(html_content, GITHUB_RAW_BASE)

    st.info("☁ Streamlit Cloud モードで動作中（OCR機能は無効）。ローカルでは `streamlit run streamlit_app.py` で全機能が使えます。")
    components.html(html_content, height=2400, scrolling=True)

else:
    procs = start_local_servers()
    if procs.get("static") is None:
        # subprocess失敗時はフォールバックでHTML直接埋め込み
        with open(HTML_PATH, encoding="utf-8") as f:
            html_content = f.read()
        # ローカルで静的サーバが立たない場合は GitHub Raw URL を IMG_BASE に使う
        html_content = _inject_img_base(html_content, GITHUB_RAW_BASE)
        components.html(html_content, height=2400, scrolling=True)
    else:
        html_url = (
            f"http://localhost:{STATIC_PORT}/"
            + urllib.parse.quote("仕様一覧表メーカー.html")
        )
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
