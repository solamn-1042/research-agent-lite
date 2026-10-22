"""Streamlit网页入口；密钥来自.env，API开关默认关闭。"""
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
from agent import run_turn

load_dotenv(Path(__file__).resolve().parent / ".env")
st.set_page_config(page_title="资料调研 Agent", page_icon="🔎")
st.title("资料调研 Agent · Day 1")
st.caption("提出问题 → 动态搜索 → 待阅读来源清单；今天只定位来源，后续加入正文阅读与报告。")
allow_api = st.sidebar.checkbox("允许调用DeepSeek（按Token计费）", value=False)
st.sidebar.caption("每轮最多4次模型调用、3次搜索；网页只在本机127.0.0.1提供服务。")
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
            st.caption("工具实际返回的来源｜仅搜索摘要，待阅读全文核实")
            for source in item["sources"]:
                # 独立显示执行器返回的来源，便于发现模型是否编造了其他链接。
                st.write(source["id"], source["title"], source["url"])
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
    with st.spinner("正在定位研究资料……"):
        with OpenAI(api_key=api_key, base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                    timeout=20, max_retries=0) as client:
            result = run_turn(question, st.session_state.turns, client,
                              os.getenv("DEEPSEEK_MODEL", "deepseek-flash"))
    if result["status"] == "COMPLETED":
        st.session_state.turns = (st.session_state.turns + [result["messages"]])[-4:]
    st.session_state.display.extend([
        {"role": "user", "content": question},
        {"role": "assistant", "content": result["answer"], "sources": result["sources"], "trace": {
            key: result[key] for key in ["run_id", "status", "elapsed_ms", "tokens", "events"]}},
    ])
    st.rerun()
