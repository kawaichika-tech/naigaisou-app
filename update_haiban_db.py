# -*- coding: utf-8 -*-
"""
廃番DB 更新スクリプト
=================================================
3社のクロス／クッションフロア継廃情報を公式ソースから取得して
`廃番DB.json` を生成します。

ソース：
  - 東リ CFシート対照表（PDF）
  - リリカラ V-Wall BASE 継廃表（PDF）
  - リリカラ XR クロス 継廃表（PDF）
  - リリカラ LH（CF）品番対照表（PDF）
  - ルノン マークII Vol.26 品番対照表（HTML）

実行：
  python update_haiban_db.py
"""

import json
import re
import os
import sys
import urllib.request
from datetime import datetime

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "廃番DB.json")
SCRATCH  = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".haiban_cache")
os.makedirs(SCRATCH, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (Naigaisou Spec Sheet Maker)"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja-JP,ja;q=0.9"}

def download(url, local):
    """簡易ダウンロード（キャッシュあり）。失敗時はキャッシュがあれば再利用、無ければ例外。"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r, open(local, "wb") as f:
            f.write(r.read())
        print(f"  downloaded: {os.path.basename(local)} ({os.path.getsize(local)} bytes)")
    except Exception as e:
        if os.path.exists(local):
            print(f"  ⚠ download failed, using cache: {e}")
        else:
            print(f"  ✗ download failed and no cache: {e}")
            raise

# === 東リ CF ===
def parse_toli_cf(db):
    print("[東リ CFシート]")
    url = "https://www.toli.co.jp/oldandnew/pdf/sheet_cf_2024-2027.pdf"
    local = os.path.join(SCRATCH, "toli_cf.pdf")
    download(url, local)
    import fitz
    doc = fitz.open(local)
    text = "\n".join(p.get_text("text") for p in doc)
    # CF系トークンを順番通り抽出（CF\d+ or CF2M\d+ or "廃番"）
    tokens = re.findall(r'(CF2M\d+|CF\d+|廃番)', text)
    # ヘッダー類「旧品番」「新品番」はマッチしないので除外不要
    pairs = 0; haiban = 0; replaced = 0
    for i in range(0, len(tokens) - 1, 2):
        old, new = tokens[i], tokens[i+1]
        if old == "廃番":
            continue  # ヘッダー混入ケース、無視
        if new == "廃番":
            db["products"][old] = {"maker": "東リ", "series": "CFシート", "status": "discontinued", "successor": None}
            haiban += 1
        else:
            db["products"][old] = {"maker": "東リ", "series": "CFシート", "status": "discontinued", "successor": new}
            db["products"].setdefault(new, {"maker": "東リ", "series": "CFシート", "status": "active", "predecessor": old})
            replaced += 1
        pairs += 1
    print(f"  処理 {pairs} ペア（うち廃番 {haiban}、後継あり {replaced}）")
    db["sources"]["toli_cf"] = url

# === リリカラ系（共通） ===
def parse_lily_pdf(db, url, series_label, prefix_match):
    """リリカラの継廃表 PDF を解析。
    形式：旧品番が `prefix_match`（例 LB-9501）、続けて状態記号 ○/△/× が並ぶ。
    後続セルに後継品番（LB-/XB-/XR-）があれば successor として記録。"""
    print(f"[リリカラ {series_label}]")
    local = os.path.join(SCRATCH, os.path.basename(url))
    download(url, local)
    import fitz
    doc = fitz.open(local)
    text = "\n".join(p.get_text("text") for p in doc)
    # トークン化（品番 or ステータス記号）。後継品番は LB-/XB-/XR-/XL- のいずれか。
    pattern = r'((?:LB|XR|XB|XL)-\d+|[○△×])'
    tokens = re.findall(pattern, text)
    # 走査：旧品番（prefix_match）に出会ったら、次のステータスと後継品番をまとめる
    n = len(tokens)
    i = 0
    count = 0; discontinued = 0; active = 0
    while i < n:
        t = tokens[i]
        if re.fullmatch(prefix_match, t):
            old = t
            status_char = None
            successors = []
            j = i + 1
            # 状態記号と次の "(prefix)-XXX" 系列まで集める
            while j < n:
                tj = tokens[j]
                if tj in "○△×":
                    if status_char is None:
                        status_char = tj
                    j += 1
                    continue
                if re.fullmatch(prefix_match, tj):
                    break  # 次の旧品番
                # 後継品番（LB-/XB-/XR-/XL-）
                successors.append(tj)
                j += 1
                # 同じ列セットに3つ以上後続コードがあるとは限らない。3つで打ち切る。
                if len(successors) >= 3:
                    break
            if status_char == "×":
                db["products"][old] = {"maker": "リリカラ", "series": series_label, "status": "discontinued",
                                       "successor": successors[0] if successors else None}
                discontinued += 1
            elif status_char in ("○", "△"):
                db["products"][old] = {"maker": "リリカラ", "series": series_label,
                                       "status": "active" if status_char == "○" else "partial",
                                       "successor": successors[0] if successors else None}
                active += 1
            # 後継品番も新品番として登録
            for s in successors:
                db["products"].setdefault(s, {"maker": "リリカラ", "series": series_label, "status": "active",
                                              "predecessor": old})
            count += 1
            i = max(i+1, j)  # 進める
        else:
            i += 1
    print(f"  処理 {count} 件（廃番 {discontinued}、継続 {active}）")
    db["sources"][f"lily_{series_label}"] = url

def parse_lily_lb(db):
    parse_lily_pdf(db,
        "https://www.lilycolor.co.jp/interior/download/data/kei_24BAS.pdf",
        "V-Wall BASE", r"LB-\d+")

def parse_lily_xr(db):
    parse_lily_pdf(db,
        "https://www.lilycolor.co.jp/interior/download/data/kei_23XR.pdf",
        "XRクロス", r"XR-\d+")

def parse_lily_lh(db):
    # LHは番号のみ表記（"81389" のように LH- が省略されることが多い）
    print("[リリカラ LH（CF）]")
    url = "https://www.lilycolor.co.jp/interior/download/data/kei_22CF.pdf"
    local = os.path.join(SCRATCH, "kei_22CF.pdf")
    download(url, local)
    import fitz
    doc = fitz.open(local)
    text = "\n".join(p.get_text("text") for p in doc)
    # トークン化：5桁番号（81XXX 等）または × または LH-/LHM-/LHS-/LHP- 接頭辞
    # ペアは「旧番号 → 新番号(または ×)」の繰り返し
    tokens = re.findall(r'(\d{5}|×)', text)
    pairs = 0; haiban = 0; replaced = 0
    for i in range(0, len(tokens)-1, 2):
        old, new = tokens[i], tokens[i+1]
        if old == "×":
            continue
        old_code = f"LH-{old}"
        if new == "×":
            db["products"][old_code] = {"maker": "リリカラ", "series": "LH（CF）", "status": "discontinued", "successor": None}
            haiban += 1
        else:
            new_code = f"LH-{new}"
            db["products"][old_code] = {"maker": "リリカラ", "series": "LH（CF）", "status": "discontinued", "successor": new_code}
            db["products"].setdefault(new_code, {"maker": "リリカラ", "series": "LH（CF）", "status": "active", "predecessor": old_code})
            replaced += 1
        pairs += 1
    print(f"  処理 {pairs} ペア（廃番 {haiban}、後継 {replaced}）")
    db["sources"]["lily_LH"] = url

# === ルノン マークII ===
def parse_runon_mark2(db):
    print("[ルノン マークII]")
    url = "http://www.runon.co.jp/mark2/number/"
    local = os.path.join(SCRATCH, "runon_mark2.html")
    # SSL 問題を避け、http で取得
    download(url, local)
    with open(local, "r", encoding="utf-8") as f:
        html = f.read()
    # HTML テキスト化（タグ除去）
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>',  '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    # ルノン マークII Vol.26 の品番（RM-701〜790, RS-XXX, R-XXX, RD-XXX）を抽出
    # Vol.26 が現役、それ以外は旧 Vol → 後継 RM-XXX に置換された可能性
    # トークン化：RM-/RS-/R-/RD- + 数字
    tokens = re.findall(r'((?:RM|RS|RD|R)-\d+|×)', text)
    # ヘッダー以降の本文だけ拾う：「Vol.16」より後ろから
    # まずRM-で始まる最初の品番からスタート
    # Vol.26 の RM-XXX は最初の列にくる。後続が旧 Vol の品番（RS/R/RD/RM等）
    # ペアではなく行ベースで、最初のRMが現役品番、その後ろは旧品番群
    # 単純化：Vol.26 (RM-701〜790) はすべて現役として登録、他のコードは旧として記録
    vol26_codes = set()
    for m in re.finditer(r'RM-\d+', text):
        code = m.group(0)
        num = int(code.split("-")[1])
        if 700 < num < 800:  # Vol.26 範囲（おおむね）
            vol26_codes.add(code)
    # 旧品番（RS-, R-, RD-, それ以外の RM-）を抽出 → 後継不明だが旧扱い
    old_codes = set()
    for m in re.finditer(r'((?:RS|RD|R)-\d+)', text):
        old_codes.add(m.group(0))
    # 登録
    for c in vol26_codes:
        db["products"].setdefault(c, {"maker": "ルノン", "series": "マークII Vol.26", "status": "active"})
    for c in old_codes:
        # 旧品番として記録（successor は HTML 行から推測難しいため省略）
        db["products"].setdefault(c, {"maker": "ルノン", "series": "マークII 旧Vol", "status": "discontinued"})
    print(f"  Vol.26 現役 {len(vol26_codes)} 件、旧Vol {len(old_codes)} 件を登録")
    db["sources"]["runon_mark2"] = url

# === メイン ===
def main():
    db = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": 1,
        "sources": {},
        "products": {}
    }
    print("=" * 50)
    print("廃番DB 更新スクリプト")
    print("=" * 50)
    try:
        parse_toli_cf(db)
    except Exception as e:
        print(f"  ✗ 東リ失敗：{e}")
    try:
        parse_lily_lb(db)
    except Exception as e:
        print(f"  ✗ リリカラLB失敗：{e}")
    try:
        parse_lily_xr(db)
    except Exception as e:
        print(f"  ✗ リリカラXR失敗：{e}")
    try:
        parse_lily_lh(db)
    except Exception as e:
        print(f"  ✗ リリカラLH失敗：{e}")
    try:
        parse_runon_mark2(db)
    except Exception as e:
        print(f"  ✗ ルノン失敗：{e}")

    print()
    print(f"合計 {len(db['products'])} 品番を登録")
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"→ {OUT_PATH}")

if __name__ == "__main__":
    main()
