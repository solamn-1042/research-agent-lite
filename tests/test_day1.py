"""离线工程测试。搜索和模型采用可控替身，不冒充真实联网或模型评测。"""
import unittest
from unittest.mock import MagicMock, patch

from openai import APIError
from openai.types.chat import ChatCompletion
from agent import run_turn
from tools import execute_tool, public_url

ROWS = [{"title": "MCP官方文档", "href": "https://modelcontextprotocol.io/docs#intro", "body": "官方说明摘要"}]


def response(text=None, calls=None, finish="stop"):
    """将预置数据转换成真实SDK响应类型；不模拟模型的实际推理能力。"""
    message = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = [{"id": f"call_{i}", "type": "function", "function": {
            "name": name, "arguments": args}} for i, (name, args) in enumerate(calls)]
    return ChatCompletion.model_validate({"id": "offline", "object": "chat.completion",
        "created": 1, "model": "test", "choices": [{"index": 0, "finish_reason": finish, "message": message}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


def client_for(*responses):
    """注入客户端替身，使单元测试无需API密钥也不会产生费用。"""
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.side_effect = responses
    return client


class ToolTests(unittest.TestCase):
    @patch("tools.DDGS")
    def test_search_and_source_id(self, ddgs):
        ddgs.return_value.text.return_value = ROWS + ROWS
        result = execute_tool("search_web", '{"query":"MCP官方文档"}')
        self.assertEqual(result["code"], "OK")
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["url"], "https://modelcontextprotocol.io/docs")
        self.assertEqual(result["sources"][0]["evidence_level"], "search_snippet")
        self.assertEqual(ddgs.return_value.text.call_args.kwargs["max_results"], 3)

    @patch("tools.DDGS")
    def test_no_results(self, ddgs):
        ddgs.return_value.text.return_value = []
        self.assertEqual(execute_tool("search_web", '{"query":"不存在的内容"}')["code"], "NO_RESULTS")

    @patch("tools.DDGS")
    def test_search_error_is_explicit(self, ddgs):
        ddgs.return_value.text.side_effect = RuntimeError("PRIVATE_DETAIL")
        result = execute_tool("search_web", '{"query":"MCP官方文档"}')
        self.assertEqual(result["code"], "SEARCH_UNAVAILABLE")
        self.assertNotIn("PRIVATE_DETAIL", str(result))

    def test_unknown_tool(self):
        self.assertEqual(execute_tool("send_email", "{}")["code"], "TOOL_NOT_ALLOWED")

    def test_invalid_parameters(self):
        for args, code in [("{", "INVALID_JSON"), ("{}", "INVALID_FIELDS"), ("[]", "INVALID_FIELDS"),
                           ('{"query":3}', "INVALID_QUERY"), ('{"query":" "}', "INVALID_QUERY"),
                           ('{"query":"ok","path":"secret"}', "INVALID_FIELDS")]:
            with self.subTest(args=args):
                self.assertEqual(execute_tool("search_web", args)["code"], code)

    def test_nonpublic_or_unsafe_links(self):
        for url in ["file:///etc/passwd", "http://127.0.0.1/", "http://service.local/",
                    "http://localhost/", "https://u:p@example.com/", "javascript:alert(1)"]:
            self.assertIsNone(public_url(url))


class LoopTests(unittest.TestCase):
    @patch("tools.DDGS")
    def test_search_then_answer_protocol(self, ddgs):
        ddgs.return_value.text.return_value = ROWS
        client = client_for(response(calls=[("search_web", '{"query":"MCP官方文档"}')], finish="tool_calls"),
                            response("找到待阅读来源，仅搜索摘要，待阅读全文核实。"))
        result = run_turn("找MCP官方资料", [], client, "test")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["tokens"], 30)
        self.assertEqual([m["role"] for m in result["messages"]], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(result["messages"][2]["tool_call_id"], "call_0")
        self.assertEqual(len(result["sources"]), 1)
        self.assertNotIn("reasoning_content", str(result))

    def test_clarification_without_search(self):
        result = run_turn("研究AI", [], client_for(response("想研究模型、产品还是应用开发？")), "test")
        self.assertFalse(result["sources"])
        self.assertEqual(len(result["messages"]), 2)

    def test_tool_error_returned_to_model(self):
        client = client_for(response(calls=[("search_web", "{}")], finish="tool_calls"), response("请缩小研究范围。"))
        result = run_turn("查资料", [], client, "test")
        self.assertIn("INVALID_FIELDS", result["messages"][2]["content"])

    @patch("tools.DDGS")
    def test_repeated_search_stops(self, ddgs):
        ddgs.return_value.text.return_value = ROWS
        call = response(calls=[("search_web", '{"query":"MCP官方文档"}')], finish="tool_calls")
        result = run_turn("查资料", [], client_for(call, call), "test")
        self.assertEqual(result["status"], "NO_PROGRESS")
        self.assertFalse(result["messages"])
        self.assertEqual(ddgs.return_value.text.call_count, 1)

    def test_model_budget(self):
        # 无权限工具也消耗模型/工具预算，不能靠错误请求逃离限制。
        replies = [response(calls=[("blocked", '{"n":' + str(i) + '}')], finish="tool_calls") for i in range(4)]
        result = run_turn("查资料", [], client_for(*replies), "test")
        self.assertIn(result["status"], {"MODEL_BUDGET", "TOOL_BUDGET"})
        self.assertEqual(sum(e["kind"] == "model" for e in result["events"]), 4)

    def test_tool_budget(self):
        calls = [("blocked", '{"n":' + str(i) + '}') for i in range(4)]
        result = run_turn("查资料", [], client_for(response(calls=calls, finish="tool_calls")), "test")
        self.assertEqual(result["status"], "TOOL_BUDGET")
        self.assertEqual(sum(e["kind"] == "tool" for e in result["events"]), 3)

    def test_empty_never_calls_model(self):
        client = client_for()
        self.assertEqual(run_turn(" ", [], client, "test")["status"], "INVALID_INPUT")
        client.chat.completions.create.assert_not_called()

    def test_deadline(self):
        with patch("agent.time.monotonic", side_effect=[0, 61, 61]):
            self.assertEqual(run_turn("查资料", [], client_for(), "test")["status"], "DEADLINE")

    def test_api_error_does_not_leak(self):
        result = run_turn("查资料", [], client_for(APIError("PRIVATE_DETAIL", request=None, body=None)), "test")
        self.assertEqual(result["status"], "API_ERROR")
        self.assertNotIn("PRIVATE_DETAIL", str(result))

    def test_truncated_output_discarded(self):
        result = run_turn("查资料", [], client_for(response("截断", finish="length")), "test")
        self.assertEqual(result["status"], "OUTPUT_LIMIT")
        self.assertFalse(result["messages"])

    def test_history_keeps_whole_turns(self):
        turns = [[{"role": "user", "content": str(i)}, {"role": "assistant", "content": "ok"}] for i in range(6)]
        client = client_for(response("ok"))
        run_turn("查资料", turns, client, "test")
        sent = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(sent[1]["content"], "2")
        self.assertEqual(len(sent), 11)


if __name__ == "__main__":
    unittest.main()
