# -*- coding: utf-8 -*-
"""
最小テスト版：Streamlit Cloud の疎通確認用。
これが動けば Cloud側 OK、本体コードに戻して原因を絞り込む。
"""
import streamlit as st

st.set_page_config(
    page_title="内外装仕様一覧表メーカー",
    page_icon="🏠",
    layout="wide",
)

st.title("🏠 内外装仕様一覧表メーカー")
st.success("✅ Streamlit Cloud で正常に起動しました！")
st.write("テスト：このメッセージが見えれば、Cloud 側のデプロイは成功してます。")
st.write("次のステップで、HTML埋め込みと画像表示を順次組み込んでいきます。")

st.info("💡 ローカルで全機能を使うには、リポをcloneして `streamlit run streamlit_app.py` を実行してください。")
