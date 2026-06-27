# -*- coding: utf-8 -*-
"""
Vercel Functions：建具表「設計仕様詳細」画像から WD番号・種類・幅・高さ を抽出。
Claude Vision を使う。POST /api/ocr-tategu に { "image": "data:image/...;base64,..." } を送る。

環境変数:
  ANTHROPIC_API_KEY  必須（Vercel の Settings → Environment Variables で登録）
  OCR_MODEL          任意（既定: claude-opus-4-8）

CORS: Streamlit Cloud のドメインなど任意のフロントから fetch されるため *。
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None  # ランタイム外でのインポートエラー回避

MODEL = os.environ.get("OCR_MODEL", "claude-opus-4-8")

SCHEMA = {
    "type": "object",
    "properties": {
        "doors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "no":   {"type": "string", "description": "建具番号。例 WD101"},
                    "type": {"type": "string", "description": "種類。例 片引戸 / 片開きドア / 折戸"},
                    "room": {"type": "string", "description": "場所・部屋名（分かる場合のみ）"},
                    "w":    {"type": "string", "description": "幅Wの数値のみ。例 1324"},
                    "h":    {"type": "string", "description": "高さHの数値のみ。例 2035"}
                },
                "required": ["no", "w", "h", "type", "room"],
                "additionalProperties": False
            }
        }
    },
    "required": ["doors"],
    "additionalProperties": False
}

PROMPT = (
    "これは住宅の建具表（設計仕様詳細）の画像です。表に並ぶ建具を1つずつ読み取り、"
    "次の項目を抽出してください：建具番号(no, 例 WD101)、種類(type, 例 片引戸/片開きドア/折戸)、"
    "幅W(w, 数値のみ)、高さH(h, 数値のみ)、分かれば場所/部屋(room)。"
    "幅・高さは『W1324』『H2035』のような表記から数字部分だけを取り出してください。"
    "見当たらない項目は空文字にしてください。表にあるすべての建具を漏れなく返してください。"
)


def _decode_image(data_url):
    m = re.match(r"data:(image/[^;]+);base64,(.+)$", data_url or "", re.S)
    if not m:
        raise ValueError("画像データが不正です（data URL 形式ではありません）。")
    return m.group(1), m.group(2)


def _ask_claude(media_type, b64):
    if Anthropic is None:
        raise RuntimeError("anthropic ライブラリの読み込みに失敗しました。Vercel の requirements.txt を確認してください。")
    client = Anthropic()  # ANTHROPIC_API_KEY 環境変数を自動で使う
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": PROMPT},
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
        self._json(200, {"ok": True, "model": MODEL, "endpoint": "/api/ocr-tategu"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            media_type, b64 = _decode_image(body.get("image", ""))
            result = _ask_claude(media_type, b64)
            self._json(200, result)
        except Exception as e:
            self._json(500, {"error": str(e)})

    def log_message(self, *args):
        pass
