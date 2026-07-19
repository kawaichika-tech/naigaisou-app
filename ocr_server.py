# -*- coding: utf-8 -*-
"""
建具表「設計仕様詳細」画像から WD番号・種類・幅・高さ を読み取るローカルAPIサーバー。
Claude のビジョン（画像認識）を使う。

使い方:
  1) pip install anthropic
  2) このフォルダの .env に ANTHROPIC_API_KEY を設定（.env.example を参照）
  3) python ocr_server.py   （または OCR起動.bat をダブルクリック）
  4) ブラウザの建具表アプリで「📐 画像から W・H を自動入力」を押す

セキュリティ:
  - APIキーはコードに書かない。.env（環境変数）から読み込む。
  - .env は他人に渡さない・GitHub等に上げないこと。
"""
import os
import re
import json
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---- .env を環境変数に読み込む（簡易ローダー。キーはここに書かない） ----
def load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)

load_env()

try:
    import anthropic
except ImportError:
    raise SystemExit("anthropic ライブラリが必要です。先に  pip install anthropic  を実行してください。")

MODEL = os.environ.get("OCR_MODEL", "claude-opus-4-8")
PORT = int(os.environ.get("OCR_PORT", "8788"))

# 構造化出力スキーマ（必ずこの形のJSONで返させる）
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

# ============================================================
# 照明商品画像から「希望小売価格」を抽出
# ============================================================
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


# ============================================================
# 間取り図から「黄色く塗られた部屋（＝クッションフロア）」を読み取る
# ============================================================
CF_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "yellow_rooms": {
            "type": "array",
            "description": "黄色く塗りつぶされている（マーキングされている）部屋のリスト",
            "items": {
                "type": "object",
                "properties": {
                    "name":       {"type": "string", "description": "部屋名。図面のラベルを読む。例 トイレ / 脱衣室 / 洗面所"},
                    "confidence": {"type": "string", "description": "黄色と判断した確度。high / medium / low のいずれか"}
                },
                "required": ["name", "confidence"],
                "additionalProperties": False
            }
        },
        "note": {"type": "string", "description": "判断に迷った点などの補足。なければ空文字。"}
    },
    "required": ["yellow_rooms", "note"],
    "additionalProperties": False
}

CF_CHECK_PROMPT = (
    "これは住宅の間取り図（平面図）です。図面内で『黄色く塗りつぶされている／黄色でマーキングされているエリア』を"
    "探して、その部屋名を読み取ってください。黄色は床仕上げがクッションフロアであることを示すマーキングです。\n"
    "- yellow_rooms: 黄色く塗られている各部屋について、name（部屋名。図面のラベル文字を読む。例：トイレ／脱衣室／洗面所）と"
    " confidence（黄色だと判断した確度。high／medium／low）を返す。\n"
    "- 明確に黄色いエリアだけを対象にする。ピンク・水色・グレー等の他の色や、非常に薄い着色は対象外。\n"
    "- 黄色いエリアの部屋名ラベルが読み取れない場合は、name に位置の説明（例：玄関横の小部屋）を入れる。\n"
    "- 黄色いエリアが1つも無ければ yellow_rooms は空配列にする。無い色を無理にこじつけないこと。\n"
    "- note: 判断に迷った点があれば短く記載。なければ空文字。"
)


def _decode_image(data_url):
    m = re.match(r"data:(image/[^;]+);base64,(.+)$", data_url or "", re.S)
    if not m:
        raise ValueError("画像データが不正です（data URL 形式ではありません）。")
    return m.group(1), m.group(2)

def _ask_claude(media_type, b64, schema, prompt):
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)

def extract(data_url):
    """建具表用：従来通り doors リストを返す"""
    media_type, b64 = _decode_image(data_url)
    return _ask_claude(media_type, b64, SCHEMA, PROMPT)

def extract_lighting(data_url):
    """照明用：価格・品番を返す（data:URI 入力）"""
    media_type, b64 = _decode_image(data_url)
    return _ask_claude(media_type, b64, LIGHTING_SCHEMA, LIGHTING_PROMPT)

def check_cf(data_url):
    """クロス図面用：間取り図から黄色く塗られた部屋（＝クッションフロア）を読み取る"""
    media_type, b64 = _decode_image(data_url)
    return _ask_claude(media_type, b64, CF_CHECK_SCHEMA, CF_CHECK_PROMPT)

def _read_local_image(rel_path):
    """サーバーと同じフォルダの相対パスからファイル読込 → (media_type, base64) を返す。
       ブラウザの tainted canvas / CORS 制約を回避するため、サーバー側で直接読む。"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 安全のためパストラバーサル防止：'..' を含む or 絶対パスは拒否
    if not rel_path or '..' in rel_path.replace('\\', '/').split('/') or os.path.isabs(rel_path):
        raise ValueError(f"不正なパスです: {rel_path}")
    abs_path = os.path.join(base_dir, rel_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"画像が見つかりません: {rel_path}")
    ext = os.path.splitext(rel_path)[1].lower()
    media_type = {
        '.jpg':'image/jpeg', '.jpeg':'image/jpeg',
        '.png':'image/png', '.webp':'image/webp', '.gif':'image/gif'
    }.get(ext, 'image/jpeg')
    with open(abs_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    return media_type, b64

def extract_lighting_file(rel_path):
    """照明用：サーバー側でファイルを直接読んで価格・品番を抽出"""
    media_type, b64 = _read_local_image(rel_path)
    return _ask_claude(media_type, b64, LIGHTING_SCHEMA, LIGHTING_PROMPT)


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

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
        # 動作確認（ヘルスチェック）
        self._json(200, {"ok": True, "model": MODEL, "endpoints": ["/api/ocr-tategu", "/api/ocr-lighting", "/api/check-cf"]})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            path = (self.path or "").rstrip("/")
            if path.endswith("/api/check-cf"):
                result = check_cf(body.get("image", ""))
            elif path.endswith("/api/ocr-lighting"):
                # imageFile（サーバー側読込）優先 → image（data:URI）にフォールバック
                if body.get("imageFile"):
                    result = extract_lighting_file(body["imageFile"])
                else:
                    result = extract_lighting(body.get("image", ""))
            else:
                # 既定は建具表（後方互換）
                result = extract(body.get("image", ""))
            self._json(200, result)
        except Exception as e:
            self._json(500, {"error": str(e)})

    def log_message(self, *args):
        pass  # アクセスログは静かに


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠ ANTHROPIC_API_KEY が未設定です。.env に設定してください（.env.example を参照）。")
    print(f"建具OCRサーバー起動： http://127.0.0.1:{PORT}  （モデル: {MODEL}）")
    print("停止するにはこのウィンドウで Ctrl + C を押してください。")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
