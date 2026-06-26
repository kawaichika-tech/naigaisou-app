# -*- coding: utf-8 -*-
"""
内外装仕様一覧表メーカー — Streamlit 版エントリポイント（ローカル／Cloud 両対応）

動作モード:
  - ローカル：subprocess で OCRサーバ＋静的サーバを起動し、iframe 経由で表示
  - Streamlit Cloud：subprocess は使えないので、HTML を直接埋め込み・画像は GitHub Raw URL

APIキーは .streamlit/secrets.toml（Cloud）または .env（ローカル）から読み込み。

起動方法:
  streamlit run streamlit_app.py
"""
import os
import re
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
# 動作モード判定：subprocess が動くか試す → 動けばローカル、ダメならCloudモード
# ============================================================
STATIC_PORT = 8731
OCR_PORT = 8788


def _try_start(args, cwd):
    """subprocess を起動。失敗したら None を返す（Cloud等で動かない場合用）。"""
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.Popen(
            args,
            env=os.environ.copy(),
            cwd=str(cwd),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None


@st.cache_resource
def start_local_servers():
    """OCRサーバと静的サーバをローカルで起動。Cloud 環境では None を返す。"""
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
                    p.terminate()
                    p.wait(timeout=3)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass

    atexit.register(_cleanup)
    return {"ocr": ocr, "static": static}


def _is_streamlit_cloud():
    """Streamlit Cloud で動いてるかの判定（複数のシグナルから）。"""
    # 1) 環境変数で判定（HOSTNAME が streamlit cloud 系）
    if os.environ.get("HOSTNAME", "").startswith("streamlit-"):
        return True
    # 2) Streamlit Cloud 標準のパスにマウントされてる
    if str(HERE).startswith("/mount/src/"):
        return True
    return False


IS_CLOUD = _is_streamlit_cloud()


# ============================================================
# HTML 読み込み＋画像参照を環境に応じて書き換え
# ============================================================
HTML_PATH = HERE / "仕様一覧表メーカー.html"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/kawaichika-tech/naigaisou-app/main/"


def _replace_image_paths(html: str) -> str:
    """HTML 内の画像相対パスを GitHub Raw URL に書き換える（Cloud用）。
    対象は HTML の img src / CSS background-url / JS 内文字列の `建具/...jpg`等。
    既に http(s):// や data: で始まるものはスキップ。"""
    folder_prefixes = ("建具/", "クロス/", "床/", "畳/", "照明/")
    file_prefixes = ("EW7531H_C_200", "EW7532H_C_200", "EW7533H_C_200",
                     "EW7534H_C_200", "EW7535H_C_200", "EW7536H_C_200",
                     "genkan_black", "genkan_white")

    def encode_path(p: str) -> str:
        # 各パスセグメントを URL エンコード（日本語・全角カッコ対応）
        return "/".join(urllib.parse.quote(seg) for seg in p.split("/"))

    # img src="..." / src='...' （http(s)/data 以外）
    def repl_src(m):
        path = m.group(2)
        if path.startswith(("http://", "https://", "data:", "//")):
            return m.group(0)
        if not (path.startswith(folder_prefixes) or path.startswith(file_prefixes)):
            return m.group(0)
        return f'{m.group(1)}"{GITHUB_RAW_BASE}{encode_path(path)}"'

    html = re.sub(r'(\bsrc=)"([^"]+)"', repl_src, html)

    # url("...") / url('...') / url(...) （CSS）
    def repl_url(m):
        path = m.group(1).strip().strip('"').strip("'")
        if path.startswith(("http://", "https://", "data:", "//")):
            return m.group(0)
        if not (path.startswith(folder_prefixes) or path.startswith(file_prefixes)):
            return m.group(0)
        return f'url("{GITHUB_RAW_BASE}{encode_path(path)}")'

    html = re.sub(r'url\(\s*([^)]+?)\s*\)', repl_url, html)

    # JS オブジェクトリテラル内の "建具/..." "クロス/..." 等
    # 例：{img:"建具/CL（…）/SH型.jpg"} や img:'建具/...'
    def repl_js_literal(m):
        path = m.group(2)
        if path.startswith(("http://", "https://", "data:", "//")):
            return m.group(0)
        if not (path.startswith(folder_prefixes) or path.startswith(file_prefixes)):
            return m.group(0)
        return f'{m.group(1)}"{GITHUB_RAW_BASE}{encode_path(path)}"'

    # 二重引用符バージョン
    html = re.sub(
        r'(\b(?:img|hinban_img|src|image|path)\s*:\s*)"([^"]+)"',
        repl_js_literal,
        html,
    )

    return html


# ============================================================
# 表示：ローカル＝iframe、Cloud＝直接埋め込み
# ============================================================
if IS_CLOUD:
    # Cloud：HTMLを直接埋め込み、画像参照は GitHub Raw URL に
    with open(HTML_PATH, encoding="utf-8") as f:
        html_content = f.read()
    html_content = _replace_image_paths(html_content)

    st.info("☁ Streamlit Cloud モードで動作中（OCR機能は無効）。ローカル版では `streamlit run streamlit_app.py` で全機能が使えます。")
    components.html(html_content, height=2400, scrolling=True)

else:
    # ローカル：subprocessでOCR/静的サーバを起動し、iframe で表示
    procs = start_local_servers()
    if procs.get("static") is None:
        # 念のためフォールバック（subprocess失敗時はCloud相当に切替）
        with open(HTML_PATH, encoding="utf-8") as f:
            html_content = f.read()
        html_content = _replace_image_paths(html_content)
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
