"""Streamlit网页入口；密钥来自.env，API开关默认关闭。"""
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
from agent import run_turn

load_dotenv(Path(__file__).resolve().parent / ".env")
st.set_page_config(page_title="资料调研 Agent", page_icon="🔎")
st.title("资料调研 Agent · Day 2")
st.caption("明确范围、搜索、阅读正文与有限补查，生成带原文定位的短报告。")
allow_api = st.sidebar.checkbox("允许调用DeepSeek（按Token计费）", value=False)
st.sidebar.caption("每次研究最多3次搜索（含2次补查）、3次正文读取、9次模型调用。")
if "turns" not in st.session_state:
    st.session_state.turns = []
    st.session_state.display = []
if st.sidebar.button("清空本次研究"):
    st.session_state.turns = []
    st.session_state.display = []
    st.rerun()
for item in st.session_state.display:
    with st.chat_message(item["role"]):
        st.write(item["content"])
        if item.get("sources"):
            st.caption("实际来源：search_snippet为搜索摘要，page_excerpt为已读正文节选")
            for source in item["sources"]:
                # 独立显示执行器返回的来源，便于发现模型是否编造了其他链接。
                st.write(source["id"], source["title"], source["url"], source["evidence_level"])
                if source.get("text"):
                    with st.expander("查看正文节选与版本"):
                        st.write(source["text"])
                        st.caption(f"抓取：{source['fetched_at']}｜版本：{source['version'][:12]}｜截断：{source['truncated']}")
        if item.get("trace"):
            with st.expander("查看搜索与执行记录"):
                st.json(item["trace"])
question = st.chat_input("例如：帮我找3份MCP工具调用的官方入门资料", max_chars=500)
if question:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not allow_api:
        st.warning("请先勾选左侧API开关，再发送研究问题。")
        st.stop()
    if not api_key or api_key == "请替换为你自己的密钥":
        st.error("请在项目根目录的.env填写DEEPSEEK_API_KEY。")
        st.stop()
    with st.spinner("正在搜索、阅读或补查资料……"):
        with OpenAI(api_key=api_key, base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                    timeout=20, max_retries=0) as client:
            result = run_turn(question, st.session_state.turns, client,
                              os.getenv("DEEPSEEK_MODEL", "deepseek-flash"))
    if result["status"] in {"COMPLETED", "NEEDS_INPUT"}:
        st.session_state.turns = (st.session_state.turns + [result["messages"]])[-4:]
    st.session_state.display.extend([
        {"role": "user", "content": question},
        {"role": "assistant", "content": result["answer"], "sources": result["sources"], "trace": {
            key: result[key] for key in ["run_id", "status", "elapsed_ms", "tokens", "events", "state"] if key in result}},
    ])
    st.rerun()
