import io
import json
import os
import sys
import unittest
import urllib.error
from types import SimpleNamespace
from unittest import mock

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.bias.runner import get_bias_result_dir
from src.pipelines.evaluator_backend import call_vllm_backend


def _ok_response(content="{}"):
    body = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
    return io.BytesIO(body)


def _bad_request(message=""):
    body = json.dumps({"error": {"message": message}}).encode("utf-8")
    return urllib.error.HTTPError("http://x", 400, "Bad Request", {}, io.BytesIO(body))


class TestVllmThinkingSwitch(unittest.TestCase):

    def setUp(self):
        self.evaluator = SimpleNamespace(vllm_url="http://127.0.0.1:1/v1", model_name="m", mock=False)
        self.sent = []

    def _urlopen(self, *responses):
        responses = list(responses)

        def fake(req, timeout=None):
            self.sent.append(json.loads(req.data.decode("utf-8")))
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return fake

    def test_thinking_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VLLM_ENABLE_THINKING", None)
            with mock.patch("urllib.request.urlopen", self._urlopen(_ok_response())):
                call_vllm_backend(self.evaluator, "technical_skills", [])
        self.assertEqual(self.sent[0]["chat_template_kwargs"], {"enable_thinking": False})

    def test_thinking_enabled_by_env(self):
        with mock.patch.dict(os.environ, {"VLLM_ENABLE_THINKING": "1"}):
            with mock.patch("urllib.request.urlopen", self._urlopen(_ok_response())):
                call_vllm_backend(self.evaluator, "technical_skills", [])
        self.assertEqual(self.sent[0]["chat_template_kwargs"], {"enable_thinking": True})

    def test_bad_request_drops_response_format_before_chat_template_kwargs(self):
        with mock.patch("urllib.request.urlopen", self._urlopen(_bad_request(), _ok_response("ok"))):
            out = call_vllm_backend(self.evaluator, "technical_skills", [])
        self.assertEqual(out, "ok")
        self.assertNotIn("response_format", self.sent[1])
        self.assertIn("chat_template_kwargs", self.sent[1])

    def test_repeated_bad_request_drops_chat_template_kwargs(self):
        with mock.patch("urllib.request.urlopen", self._urlopen(_bad_request(), _bad_request(), _ok_response("ok"))):
            out = call_vllm_backend(self.evaluator, "technical_skills", [])
        self.assertEqual(out, "ok")
        self.assertNotIn("response_format", self.sent[2])
        self.assertNotIn("chat_template_kwargs", self.sent[2])

    def test_bad_request_naming_chat_template_kwargs_keeps_json_mode(self):
        err = _bad_request("chat_template_kwargs: unexpected keyword 'enable_thinking'")
        with mock.patch("urllib.request.urlopen", self._urlopen(err, _ok_response("ok"))):
            call_vllm_backend(self.evaluator, "technical_skills", [])
        self.assertIn("response_format", self.sent[1])
        self.assertNotIn("chat_template_kwargs", self.sent[1])

    def test_context_length_error_is_not_retried(self):
        err = _bad_request("This model's maximum context length is 20000 tokens. However, you requested 21000 tokens")
        with mock.patch("urllib.request.urlopen", self._urlopen(err, _ok_response("ok"))):
            with self.assertRaises(RuntimeError):
                call_vllm_backend(self.evaluator, "technical_skills", [])
        self.assertEqual(len(self.sent), 1)


class TestBiasResultDir(unittest.TestCase):

    def test_legacy_path_without_model_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MODEL_KEY", None)
            self.assertEqual(get_bias_result_dir("/root"), os.path.join("/root", "bias-result"))

    def test_per_model_subdirectory(self):
        with mock.patch.dict(os.environ, {"MODEL_KEY": "glm4.7-flash"}):
            self.assertEqual(get_bias_result_dir("/root"), os.path.join("/root", "bias-result", "glm4.7-flash"))


if __name__ == "__main__":
    unittest.main()
