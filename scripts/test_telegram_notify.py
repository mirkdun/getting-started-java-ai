import contextlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest import mock
from unittest.mock import patch
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram_notify as tn


class TelegramHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = None
        self.server.requests.append({"path": self.path, "body": payload})
        if self.server.delay:
            time.sleep(self.server.delay)
        response_body = json.dumps(self.server.response_body).encode("utf-8")
        try:
            self.send_response(self.server.response_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        except OSError:
            pass

    def log_message(self, format, *args):
        pass


@contextlib.contextmanager
def mock_telegram(status=200, response_body=None, delay=0):
    server = ThreadingHTTPServer(("127.0.0.1", 0), TelegramHandler)
    server.daemon_threads = True
    server.requests = []
    server.response_status = status
    server.response_body = {"ok": True, "result": {}} if response_body is None else response_body
    server.delay = delay
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


class TelegramNotifyTests(unittest.TestCase):
    def base_args(self, junit_dir, status):
        return [
            "--project", "demo/project",
            "--ci", "GitHub Actions",
            "--branch", "master",
            "--commit", "abcdef1234567890",
            "--run-url", "https://example.test/run/1",
            "--status", status,
            "--junit-dir", str(junit_dir),
        ]

    def env_for(self, base_url, timeout="5"):
        return {
            "TELEGRAM_BOT_TOKEN": "123:fake-token",
            "TELEGRAM_CHAT_ID": "-100123",
            "TELEGRAM_API_BASE_URL": base_url,
            "TELEGRAM_TIMEOUT": timeout,
        }

    def run_main(self, args, env):
        stdout = StringIO()
        with patch.dict(os.environ, env, clear=False):
            with redirect_stdout(stdout):
                code = tn.main(args)
        return code, stdout.getvalue()

    def test_success_counts_junit_testcases_without_duplicating_nested_suites(self):
        with tempfile.TemporaryDirectory() as tmp:
            junit_dir = Path(tmp)
            (junit_dir / "TEST-a.xml").write_text(
                """<testsuites>
  <testsuite name="outer" tests="3" failures="1" errors="0" skipped="1">
    <testcase name="failed"><failure message="boom"/></testcase>
    <testcase name="skipped"><skipped/></testcase>
    <testsuite name="inner" tests="1" failures="0" errors="0" skipped="0">
      <testcase name="passed"/>
    </testsuite>
  </testsuite>
</testsuites>""",
                encoding="utf-8",
            )
            (junit_dir / "TEST-b.xml").write_text(
                """<testsuite name="error-suite" tests="1" failures="0" errors="1" skipped="0">
  <testcase name="error"><error message="err"/></testcase>
</testsuite>""",
                encoding="utf-8",
            )
            with mock_telegram() as (base_url, requests):
                code, output = self.run_main(self.base_args(junit_dir, "SUCCESS"), self.env_for(base_url))

        self.assertEqual(code, 0)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["path"], "/bot123:fake-token/sendMessage")
        message = requests[0]["body"]["text"]
        self.assertEqual(requests[0]["body"]["parse_mode"], "HTML")
        self.assertIn("✅ UI tests: SUCCESS", message)
        self.assertIn("<b>Project:</b> demo/project", message)
        self.assertIn("<b>CI:</b> GitHub Actions", message)
        self.assertIn("<b>Branch:</b> master", message)
        self.assertIn("<b>Commit:</b> <code>abcdef1</code>", message)
        self.assertIn("<b>Tests:</b> passed=1 • failed=1 • errors=1 • skipped=1", message)
        self.assertIn('<b>Run:</b> <a href="https://example.test/run/1">https://example.test/run/1</a>', message)
        self.assertIn("Telegram notification sent", output)

    def test_missing_junit_results_report_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            junit_dir = Path(tmp) / "absent"
            with mock_telegram() as (base_url, requests):
                code, _ = self.run_main(self.base_args(junit_dir, "BUILD_ERROR"), self.env_for(base_url))

        self.assertEqual(code, 0)
        self.assertEqual(len(requests), 1)
        message = requests[0]["body"]["text"]
        self.assertIn("⚠️ UI tests: BUILD_ERROR", message)
        self.assertIn("<b>Tests:</b> not run (no JUnit XML results)", message)

    def test_invalid_junit_xml_reports_statistics_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            junit_dir = Path(tmp)
            (junit_dir / "TEST-bad.xml").write_text("<testsuite><testcase", encoding="utf-8")
            with mock_telegram() as (base_url, requests):
                code, _ = self.run_main(self.base_args(junit_dir, "TESTS_FAILED"), self.env_for(base_url))

        self.assertEqual(code, 0)
        self.assertEqual(len(requests), 1)
        message = requests[0]["body"]["text"]
        self.assertIn("❌ UI tests: TESTS_FAILED", message)
        self.assertIn("<b>Tests:</b> statistics unavailable (invalid JUnit XML)", message)

    def test_build_message_escapes_html_in_dynamic_values(self):
        message = tn.build_message(
            project="a<b>&",
            ci="GitHub Actions",
            branch="x<y",
            commit="abcdef123",
            status="SUCCESS",
            stats={"passed": 1, "failed": 0, "errors": 0, "skipped": 0},
            stats_error=None,
            run_url="https://example.test/?a=1&b=<x>",
        )
        self.assertIn("a&lt;b&gt;&amp;", message)
        self.assertIn("<b>Branch:</b> x&lt;y", message)
        self.assertIn("https://example.test/?a=1&amp;b=&lt;x&gt;", message)
        self.assertIn('href="https://example.test/?a=1&amp;b=&lt;x&gt;"', message)

    def test_missing_secrets_skip_without_http_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.env_for("http://127.0.0.1:1")
            env["TELEGRAM_BOT_TOKEN"] = ""
            env["TELEGRAM_CHAT_ID"] = ""
            with mock_telegram() as (base_url, requests):
                env["TELEGRAM_API_BASE_URL"] = base_url
                code, output = self.run_main(self.base_args(Path(tmp), "SUCCESS"), env)

        self.assertEqual(code, 0)
        self.assertEqual(requests, [])
        self.assertIn("::warning::Telegram secrets are not configured; notification skipped", output)

    def test_http_error_is_warning_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock_telegram(status=500, response_body={"ok": False, "description": "err"}) as (base_url, requests):
                code, output = self.run_main(self.base_args(Path(tmp), "TESTS_FAILED"), self.env_for(base_url))

        self.assertEqual(code, 0)
        self.assertEqual(len(requests), 1)
        self.assertIn("::warning::Telegram notification failed: HTTP 500", output)

    def test_ok_false_is_warning_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock_telegram(status=200, response_body={"ok": False, "description": "bad request"}) as (base_url, requests):
                code, output = self.run_main(self.base_args(Path(tmp), "TESTS_FAILED"), self.env_for(base_url))

        self.assertEqual(code, 0)
        self.assertEqual(len(requests), 1)
        self.assertIn("::warning::Telegram notification failed: Telegram API ok=false (HTTP 200)", output)

    def test_timeout_is_warning_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock_telegram(delay=2) as (base_url, requests):
                code, output = self.run_main(
                    self.base_args(Path(tmp), "TESTS_FAILED"),
                    self.env_for(base_url, timeout="0.2"),
                )

        self.assertEqual(code, 0)
        self.assertIn("::warning::Telegram notification failed: timeout", output)


if __name__ == "__main__":
    unittest.main()
