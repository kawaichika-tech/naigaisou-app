# -*- coding: utf-8 -*-
"""
Vercel Functions：間取り図（平面図）から「黄色く塗られた部屋（＝クッションフロア）」を読み取る。
POST /api/check-cf に { "image": "data:image/...;base64,..." } を送る。

フロント側（クロス図面タブの判定ボタン）が、返ってきた yellow_rooms と
仕上げ仕様（床＝クッションフロアの部屋）を突き合わせて不一致を表示する。

ローカル開発用の OCRサーバ（ocr_server.py）と schema/prompt を揃えている。

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

_CF_ROOM_ITEM = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name":       {"type": "string", "description": "部屋名。図面のラベルを読む。例 トイレ / 脱衣室 / 洗面所 / LDK"},
            "confidence": {"type": "string", "description": "その色だと判断した確度。high / medium / low のいずれか"}
        },
        "required": ["name", "confidence"],
        "additionalProperties": False
    }
}

CF_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "yellow_rooms": dict(_CF_ROOM_ITEM, description="黄色く塗られた部屋（＝床のクッションフロア）"),
        "pink_rooms":   dict(_CF_ROOM_ITEM, description="ピンク（桃色）で塗られた部屋（＝壁のアクセントクロス）"),
        "purple_rooms": dict(_CF_ROOM_ITEM, description="紫（パープル）で塗られた部屋（＝天井のアクセントクロス）"),
        "note": {"type": "string", "description": "判断に迷った点などの補足。なければ空文字。"}
    },
    "required": ["yellow_rooms", "pink_rooms", "purple_rooms", "note"],
    "additionalProperties": False
}

CF_CHECK_PROMPT = (
    "これは住宅の間取り図（平面図）です。図面には内装仕上げを示す色マーキングがあります。"
    "次の3色で塗りつぶされた／範囲マーキングされたエリアを探し、それぞれ部屋名を読み取ってください：\n"
    "- 黄色 ＝ 床のクッションフロア → yellow_rooms\n"
    "- ピンク（桃色・赤みがかった色）＝ 壁のアクセントクロス → pink_rooms\n"
    "- 紫（パープル・青紫）＝ 天井のアクセントクロス → purple_rooms\n"
    "各配列の要素は name（部屋名。図面のラベル文字を読む。例：トイレ／脱衣室／LDK）と"
    " confidence（その色と判断した確度。high／medium／low）。\n"
    "重要：黄色・ピンク・紫を取り違えないこと。ピンクは赤みの桃色、紫は青みのパープルで別物。\n"
    "面（範囲）の塗りだけを対象にし、矢印・引き出し線・文字などの細い線や着色は対象外。\n"
    "非常に薄い着色やその他の色（水色・グレー等）も対象外。該当色が無ければその配列は空にする。無い色を無理にこじつけないこと。\n"
    "部屋名ラベルが読み取れないエリアは name に位置の説明（例：玄関横の小部屋）を入れる。\n"
    "note: 判断に迷った点があれば短く記載。なければ空文字。"
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
        output_config={"format": {"type": "json_schema", "schema": CF_CHECK_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": CF_CHECK_PROMPT},
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
        self._json(200, {"ok": True, "model": MODEL, "endpoint": "/api/check-cf"})

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
