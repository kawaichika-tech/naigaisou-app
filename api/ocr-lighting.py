# -*- coding: utf-8 -*-
"""
Vercel Functions：照明商品画像から「希望小売価格」「品番」を抽出。
POST /api/ocr-lighting に { "image": "data:image/...;base64,..." } を送る。

Cloud 環境ではサーバ側ファイル読込（imageFile）は対応せず、必ず data:URI 形式で送る。
ローカル開発用の OCRサーバ（ocr_server.py）と機能を揃えるため schema/prompt は同等。

環境変数:
  ANTHROPIC_API_KEY  必須
  OCR_MODEL          任意（既定: claude-opus-4-8）
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

MODEL = os.environ.get("OCR_MODEL", "claude-opus-4-8")

LIGHTING_SCHEMA = {
    "type": "object",
    "properties": {
        "price":  {"type": "integer", "description": "希望小売価格（税抜・円）。読み取れた数値のみ。例: 4500"},
        "hinban": {"type": "string",  "description": "品番。例: LGD1108VLE1。見当たらなければ空文字。"},
        "note":   {"type": "string",  "description": "価格の補足。税込/税抜の別など。読み取れなければ空文字。"}
    },
    "required": ["price", "hinban", "note"],
    "additionalProperties": False
}

LIGHTING_PROMPT = (
    "これは住宅向け照明器具のメーカー商品画像です。画像から以下を抽出してください：\n"
    "- price: 希望小売価格（税抜・円）の数値のみ。例『4,500円(税抜)』なら 4500。\n"
    "  税抜と税込の両方が写っている場合は税抜を優先。税込しかなければ税込の値で構いません。\n"
    "- hinban: 品番（例 LGD1108VLE1）。見当たらなければ空文字。\n"
    "- note: 税込／税抜の別や、価格の補足情報を短く（例『税抜』『税込』）。なければ空文字。\n"
    "価格が読み取れない場合は price は 0 を返してください。"
)


def _decode_image(data_url):
    m = re.match(r"data:(image/[^;]+);base64,(.+)$", data_url or "", re.S)
    if not m:
        raise ValueError("画像データが不正です（data URL 形式ではありません）。")
    return m.group(1), m.group(2)


def _ask_claude(media_type, b64):
    if Anthropic is None:
        raise RuntimeError("anthropic ライブラリの読み込みに失敗しました。Vercel の requirements.txt を確認してください。")
    client = Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        output_config={"format": {"type": "json_schema", "schema": LIGHTING_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": LIGHTING_PROMPT},
            ],
        }],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)


class handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        self._json(200, {"ok": True, "model": MODEL, "endpoint": "/api/ocr-lighting"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            # Cloud版では imageFile（サーバ側読込）は不可。data:URI のみ受け付ける。
            media_type, b64 = _decode_image(body.get("image", ""))
            result = _ask_claude(media_type, b64)
            self._json(200, result)
        except Exception as e:
            self._json(500, {"error": str(e)})

    def log_message(self, *args):
        pass
