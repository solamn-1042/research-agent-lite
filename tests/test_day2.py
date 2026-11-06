"""Day 2回归：真实LangGraph、可控SDK/搜索/网页替身，无真实API费用。"""
import hashlib
import json
import unittest
from unittest.mock import MagicMock, patch

from openai import APIError
from openai.types.chat import ChatCompletion
from agent import run_turn, validate_report
from reader import MAX_BYTES, PinnedHTTPS, read_page
from tools import execute_tool

URL = "https://docs.docker.com/compose/"
SID = "WEB-" + hashlib.sha256(URL.encode()).hexdigest()[:8]
QUOTE = "演示资料说明可以使用配置文件管理多个服务"
BODY = (QUOTE + "。这是单元测试构造的页面内容，不是从真实网站抓取的文档。") * 4
SOURCE = {"id": SID, "title": "测试构造页面", "url": URL, "snippet": "仅定位摘要", "evidence_level": "search_snippet"}
PAGE = {**SOURCE, "text": BODY, "evidence_level": "page_excerpt", "fetched_at": "2026-10-22T01:00:00+00:00",
        "version": hashlib.sha256(BODY.encode()).hexdigest(), "truncated": False}
REPORT = {"title": "测试报告", "claims": [{"text": "演示资料描述了多服务配置管理。", "source_id": SID, "quote": QUOTE}],
          "limitations": "本报告由离线构造页面生成，只验证工程执行路径。"}


def decision(name, args, count=1):
    """构造真实SDK类型的工具调用；不把脚本预设动作当成模型效果。"""
    calls = [{"id": f"call_{i}", "type": "function", "function": {"name": name,
              "arguments": json.dumps(args, ensure_ascii=False)}} for i in range(count)]
    return ChatCompletion.model_validate({"id": "offline", "object": "chat.completion", "created": 1, "model": "test",
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "tool_calls": calls}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


def scripted(*responses):
    """创建可控客户端，记录模型节点收到的真实消息列表。"""
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = responses
    return client


def result(source=SOURCE):
    return {"ok": True, "code": "OK", "sources": [source]}


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch("reader.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]).start()
        self.connection = patch("reader.PinnedHTTPS").start()
        self.addCleanup(patch.stopall)
        self.response = self.connection.return_value.getresponse.return_value
        self.response.status = 200
        self.headers = {"Content-Type": "text/html; charset=utf-8", "Content-Encoding": "identity"}
        self.response.getheader.side_effect = lambda name, default=None: self.headers.get(name, default)
        self.response.read.return_value = ("<html><nav>不要保留导航</nav><main>" + BODY + "</main><script>evil()</script></html>").encode()

    def test_extraction_version_and_pinned_address(self):
        got = read_page(SOURCE)
        self.assertTrue(got["ok"])
        source = got["sources"][0]
        self.assertEqual(source["text"], BODY)
        self.assertEqual(source["version"], hashlib.sha256(BODY.encode()).hexdigest())
        self.assertEqual(source["evidence_level"], "page_excerpt")
        self.assertEqual(self.connection.call_args.args[:2], ("docs.docker.com", "93.184.216.34"))
        self.connection.return_value.close.assert_called_once()

    def test_unknown_host_scheme_port_and_credentials(self):
        for url in ["http://docs.docker.com/", "https://docs.docker.com.evil.example/", "https://127.0.0.1/",
                    "https://docs.docker.com:8443/", "https://u:p@docs.docker.com/", "file:///etc/passwd"]:
            with self.subTest(url=url):
                self.assertEqual(read_page({**SOURCE, "url": url})["code"], "URL_BLOCKED")
        self.connection.assert_not_called()

    def test_mixed_dns_is_blocked(self):
        self.dns.return_value += [(2, 1, 6, "", ("127.0.0.1", 443))]
        self.assertEqual(read_page(SOURCE)["code"], "ADDRESS_BLOCKED")
        self.connection.assert_not_called()

    def test_redirect_never_followed(self):
        self.response.status = 302
        self.headers["Location"] = "http://169.254.169.254/"
        self.assertEqual(read_page(SOURCE)["code"], "REDIRECT_BLOCKED")
        self.assertEqual(self.connection.return_value.request.call_count, 1)

    def test_type_and_encoding_limits(self):
        self.headers["Content-Type"] = "application/pdf"
        self.assertEqual(read_page(SOURCE)["code"], "CONTENT_TYPE_BLOCKED")
        self.headers.update({"Content-Type": "text/html", "Content-Encoding": "gzip"})
        self.assertEqual(read_page(SOURCE)["code"], "ENCODING_BLOCKED")

    def test_page_size_and_excerpt_limits(self):
        self.response.read.return_value = b"x" * (MAX_BYTES + 1)
        self.assertEqual(read_page(SOURCE)["code"], "PAGE_TOO_LARGE")
        self.response.read.return_value = b"x" * 7000
        self.headers["Content-Type"] = "text/plain"
        got = read_page(SOURCE)["sources"][0]
        self.assertEqual(len(got["text"]), 6000)
        self.assertTrue(got["truncated"])

    def test_empty_and_network_failure(self):
        self.response.read.return_value = b"empty"
        self.assertEqual(read_page(SOURCE)["code"], "EMPTY_PAGE")
        self.connection.return_value.request.side_effect = TimeoutError()
        self.assertEqual(read_page(SOURCE)["code"], "READ_UNAVAILABLE")

    def test_unknown_source_does_not_fetch(self):
        self.assertEqual(execute_tool("read_web", '{"source_id":"MADE-UP"}', sources={})["code"], "UNKNOWN_SOURCE")
        self.connection.assert_not_called()


class PinnedConnectionTests(unittest.TestCase):
    @patch("reader.ssl.create_default_context")
    @patch("reader.socket.create_connection")
    def test_original_hostname_used_for_certificate(self, connect, context):
        conn = PinnedHTTPS("docs.docker.com", "93.184.216.34", 4)
        conn.connect()
        connect.assert_called_once_with(("93.184.216.34", 443), timeout=4)
        context.return_value.wrap_socket.assert_called_once_with(connect.return_value, server_hostname="docs.docker.com")


class CitationTests(unittest.TestCase):
    def test_valid_report(self):
        valid, text = validate_report(REPORT, {SID: PAGE})
        self.assertTrue(valid)
        self.assertIn(URL, text)

    def test_unread_and_fake_id_rejected(self):
        self.assertEqual(validate_report(REPORT, {SID: SOURCE})[1], "UNREAD_CITATION")
        self.assertEqual(validate_report(REPORT, {})[1], "UNREAD_CITATION")

    def test_quote_must_exist(self):
        report = {**REPORT, "claims": [{**REPORT["claims"][0], "quote": "这段文字没有出现在任何已经读取过的正文中"}]}
        self.assertEqual(validate_report(report, {SID: PAGE})[1], "QUOTE_NOT_IN_EVIDENCE")

    def test_invalid_structure(self):
        for value in [None, [], {}, {**REPORT, "claims": []}, {**REPORT, "title": 123}]:
            self.assertFalse(validate_report(value, {SID: PAGE})[0])


class GraphTests(unittest.TestCase):
    @patch("agent.execute_tool", side_effect=[result(), result(PAGE)])
    def test_search_read_report(self, execute):
        client = scripted(decision("search_web", {"query": "Compose官方资料"}),
                          decision("read_web", {"source_id": SID}), decision("finish_report", REPORT))
        got = run_turn("调研Compose配置管理", [], client, "test")
        self.assertEqual(got["status"], "COMPLETED")
        self.assertEqual(got["state"]["search_count"], 1)
        self.assertEqual(got["state"]["read_count"], 1)
        self.assertEqual(got["tokens"], 45)
        self.assertEqual([e["name"] for e in got["events"] if e["kind"] == "tool"], ["search_web", "read_web", "finish_report"])
        self.assertIn("page_excerpt", str(client.chat.completions.create.call_args.kwargs["messages"]))

    @patch("agent.execute_tool", side_effect=[{"ok": False, "code": "NO_RESULTS", "sources": []}, result(), result(PAGE)])
    def test_failed_search_changes_query(self, execute):
        client = scripted(decision("search_web", {"query": "不合适的词"}),
                          decision("search_web", {"query": "site:docs.docker.com compose"}),
                          decision("read_web", {"source_id": SID}), decision("finish_report", REPORT))
        got = run_turn("研究配置管理", [], client, "test")
        self.assertEqual(got["status"], "COMPLETED")
        self.assertEqual(got["state"]["search_count"], 2)
        self.assertEqual(got["events"][1]["code"], "NO_RESULTS")

    def test_clarify_stops_without_network(self):
        got = run_turn("研究AI", [], scripted(decision("ask_user", {"question": "想研究哪个具体方向？"})), "test")
        self.assertEqual(got["status"], "NEEDS_INPUT")
        self.assertEqual(got["state"]["search_count"], 0)
        self.assertEqual(len(got["messages"]), 2)

    @patch("agent.execute_tool", side_effect=[result(), result(PAGE)])
    def test_report_before_reading_is_rejected_then_repaired(self, execute):
        client = scripted(decision("search_web", {"query": "Compose"}), decision("finish_report", REPORT),
                          decision("read_web", {"source_id": SID}), decision("finish_report", REPORT))
        got = run_turn("研究Compose", [], client, "test")
        self.assertEqual(got["status"], "COMPLETED")
        # 正文证据已改变：同一报告此时可以通过，不能被旧动作指纹误拦截。
        self.assertIn("UNREAD_CITATION", str(got["events"]))

    @patch("agent.execute_tool", return_value={"ok": False, "code": "NO_RESULTS", "sources": []})
    def test_only_two_supplementary_searches(self, execute):
        client = scripted(*[decision("search_web", {"query": f"搜索词{i}"}) for i in range(4)],
                          decision("ask_user", {"question": "资料不足，请缩小范围。"}))
        got = run_turn("研究Compose", [], client, "test")
        self.assertEqual(execute.call_count, 3)
        self.assertEqual(got["state"]["search_count"], 3)
        self.assertIn("SEARCH_BUDGET", str(got["events"]))

    def test_identical_action_stops(self):
        client = scripted(decision("read_web", {"source_id": "missing"}), decision("read_web", {"source_id": "missing"}))
        self.assertEqual(run_turn("研究Compose", [], client, "test")["status"], "NO_PROGRESS")

    def test_sdk_error_and_empty_input(self):
        error = APIError("PRIVATE_DETAIL", request=None, body=None)
        got = run_turn("研究Compose", [], scripted(error), "test")
        self.assertEqual(got["status"], "API_ERROR")
        self.assertNotIn("PRIVATE_DETAIL", str(got))
        self.assertEqual(run_turn(" ", [], scripted(), "test")["status"], "INVALID_INPUT")

    def test_model_budget_and_multi_call_protocol(self):
        client = scripted(*[decision("ask_user", {"question": "范围？"}, count=2) for _ in range(9)])
        got = run_turn("研究Compose", [], client, "test")
        self.assertEqual(got["status"], "BUDGET_EXCEEDED")
        self.assertEqual(client.chat.completions.create.call_count, 9)
        sent = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertIn("ONE_ACTION_PER_STEP", str(sent))


if __name__ == "__main__":
    unittest.main()
