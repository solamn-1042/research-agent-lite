"""受限HTTPS读取：官方允许域、固定已校验IP、禁止重定向，返回有版本的正文节选。"""
import hashlib
import http.client
import ipaddress
import os
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

DEFAULT_HOSTS = "docs.docker.com,docs.langchain.com,modelcontextprotocol.io,api-docs.deepseek.com,docs.python.org"
MAX_BYTES, MAX_CHARS = 512_000, 6_000


def allowed_hosts() -> set[str]:
    """返回服务端配置的精确域名；模型无权修改。"""
    return {h.strip().lower() for h in os.getenv("RESEARCH_ALLOWED_HOSTS", DEFAULT_HOSTS).split(",") if h.strip()}


class PinnedHTTPS(http.client.HTTPSConnection):
    """连接已校验IP，仍以原域名执行TLS证书检查与SNI。"""
    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        """固定目标IP，避免DNS校验后连接时再次解析；握手失败时释放套接字。"""
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def read_page(source: dict, timeout: float = 8) -> dict:
    """读取已发现来源。参数：来源记录和网络超时；返回正文节选或明确错误码。"""
    def fail(code):
        return {"ok": False, "code": code, "sources": []}
    try:
        parsed = urlsplit(source["url"])
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or host not in allowed_hosts() or parsed.username
                or parsed.password or parsed.port not in {None, 443}):
            return fail("URL_BLOCKED")
        # 核对全部解析结果；只要混入私网、回环或链路本地地址就拒绝。
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            return fail("ADDRESS_BLOCKED")
        conn = PinnedHTTPS(host, sorted(addresses)[0], max(1, min(8, timeout)))
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            conn.request("GET", path, headers={"User-Agent": "ResearchAgentLite/0.2",
                         "Accept": "text/html,text/plain", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            if 300 <= response.status < 400:
                return fail("REDIRECT_BLOCKED")
            if response.status != 200:
                return fail("HTTP_ERROR")
            content_type = response.getheader("Content-Type", "").lower()
            if content_type.split(";", 1)[0].strip() not in {"text/html", "text/plain"}:
                return fail("CONTENT_TYPE_BLOCKED")
            if response.getheader("Content-Encoding", "identity").lower() not in {"", "identity"}:
                return fail("ENCODING_BLOCKED")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return fail("PAGE_TOO_LARGE")
        finally:
            conn.close()
        text = data.decode("utf-8", errors="replace")
        if content_type.startswith("text/html"):
            soup = BeautifulSoup(text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
                tag.decompose()
            main = soup.select_one("main, article") or soup
            text = main.get_text(" ", strip=True)
        text = " ".join(text.split())
        if len(text) < 80:
            return fail("EMPTY_PAGE")
        excerpt = text[:MAX_CHARS]
        record = {**source, "text": excerpt, "evidence_level": "page_excerpt",
                  "fetched_at": datetime.now(timezone.utc).isoformat(),
                  "version": hashlib.sha256(excerpt.encode()).hexdigest(), "truncated": len(text) > MAX_CHARS}
        return {"ok": True, "code": "OK", "sources": [record]}
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return fail("READ_UNAVAILABLE")
