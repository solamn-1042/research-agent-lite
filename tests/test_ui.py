"""验证网页操作与API开关；不发起真实模型或搜索请求。"""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


class UiTests(unittest.TestCase):
    def test_api_is_off_by_default(self):
        with patch("agent.run_turn") as run:
            app = AppTest.from_file(APP).run(timeout=15)
            self.assertFalse(app.exception)
            self.assertFalse(app.checkbox[0].value)
            app.chat_input[0].set_value("找MCP资料").run()
            self.assertTrue(app.warning)
            run.assert_not_called()

    def test_completed_turn_and_clear(self):
        result = {"answer": "待阅读来源已找到。", "status": "COMPLETED", "run_id": "offline",
                  "elapsed_ms": 1, "tokens": 30, "events": [], "sources": [],
                  "messages": [{"role": "user", "content": "找MCP资料"},
                               {"role": "assistant", "content": "待阅读来源已找到。"}]}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "offline_test_key"}), patch("openai.OpenAI"), patch("agent.run_turn", return_value=result) as run:
            app = AppTest.from_file(APP).run(timeout=15)
            app.checkbox[0].set_value(True).run()
            app.chat_input[0].set_value("找MCP资料").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_message), 2)
            self.assertEqual(len(app.session_state["turns"]), 1)
            run.assert_called_once()
            app.button[0].click().run()
            self.assertEqual(len(app.chat_message), 0)
            self.assertEqual(app.session_state["turns"], [])


if __name__ == "__main__":
    unittest.main()
