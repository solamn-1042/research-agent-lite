"""工具契约与执行器：搜索定位来源，read_web按本次来源ID读取正文。"""
import hashlib
import ipaddress
import json
from urllib.parse import urlsplit, urlunsplit

from ddgs import DDGS
from reader import read_page

TOOL_SCHEMAS = [{"type": "function", "function": {
    "name": "search_web",
    "description": "按研究问题搜索公开网页，返回最多3条标题、链接和搜索摘要。摘要不是网页全文，不能据此宣称读过原文。",
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "2至160字的搜索词；优先用site:限定官方来源"}},
        "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "read_web", "description": "按本次search_web返回的来源ID读取正文节选。摘要不能当作原文。",
        "parameters": {"type": "object", "properties": {"source_id": {"type": "string"}},
                       "required": ["source_id"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "ask_user", "description": "研究目标或范围不足时追问一个明确问题，暂停当前轮次。",
        "parameters": {"type": "object", "properties": {"question": {"type": "string"}},
                       "required": ["question"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "finish_report", "description": "证据充分后提交短报告；每条结论引用已读来源ID，quote逐字复制12至80字原文。",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "claims": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "source_id": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["text", "source_id", "quote"], "additionalProperties": False}},
            "limitations": {"type": "string"}},
            "required": ["title", "claims", "limitations"], "additionalProperties": False}}}]


def public_url(raw: str) -> str | None:
    """规范化可展示的公开HTTP链接；参数为原始URL，返回去片段URL或None。"""
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return None
        if "." not in host or host.endswith((".local", ".localhost", ".internal")):
            return None
        try:
            # 本日不抓取URL；仅筛掉明显的内网/IP链接，不能当作完整SSRF防护。
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except (ValueError, TypeError):
        return None


def execute_tool(name: str, arguments: str, timeout: float = 8, sources: dict | None = None) -> dict:
    """执行白名单搜索。参数：工具名、JSON字符串、单次超时；返回结构化结果。"""
    if name not in {"search_web", "read_web"}:
        return {"ok": False, "code": "TOOL_NOT_ALLOWED", "sources": []}
    try:
        args = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return {"ok": False, "code": "INVALID_JSON", "sources": []}
    field = "query" if name == "search_web" else "source_id"
    if not isinstance(args, dict) or set(args) != {field}:
        return {"ok": False, "code": "INVALID_FIELDS", "sources": []}
    if name == "read_web":
        source_id = args["source_id"]
        if not isinstance(source_id, str) or source_id not in (sources or {}):
            return {"ok": False, "code": "UNKNOWN_SOURCE", "sources": []}
        return read_page(sources[source_id], timeout=timeout)
    query = args["query"]
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 160:
        return {"ok": False, "code": "INVALID_QUERY", "sources": []}
    try:
        # 明确单一后端、结果上限和超时；保留证书校验，无密钥的公开搜索也可能限流。
        rows = DDGS(timeout=max(1, min(8, timeout))).text(
            query.strip(), max_results=3, backend="duckduckgo")
    except Exception as error:
        # 只在第三方边界兜底；异常类型可排障，原始错误可能带请求细节，不直接公开。
        return {"ok": False, "code": "SEARCH_UNAVAILABLE",
                "error_type": type(error).__name__, "sources": []}
    sources, seen = [], set()
    for row in rows[:3]:
        url = public_url(row.get("href", ""))
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append({"id": "WEB-" + hashlib.sha256(url.encode()).hexdigest()[:8],
                        "title": str(row.get("title", ""))[:180], "url": url,
                        "snippet": str(row.get("body", ""))[:500],
                        "evidence_level": "search_snippet"})
    return {"ok": bool(sources), "code": "OK" if sources else "NO_RESULTS",
            "query": query.strip(), "sources": sources}
