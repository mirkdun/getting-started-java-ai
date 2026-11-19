import argparse
import html
import json
import os
import socket
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_API_BASE_URL = "https://api.telegram.org"
DEFAULT_TIMEOUT_SECONDS = 10.0

STATUS_EMOJI = {
    "SUCCESS": "✅",
    "TESTS_FAILED": "❌",
    "BUILD_ERROR": "⚠️",
    "REPORT_ERROR": "⚠️",
    "FAILURE": "❌",
    "CANCELLED": "🚫",
}


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def classify_test_case(test_case):
    child_names = {local_name(child.tag) for child in test_case}
    if "error" in child_names:
        return "errors"
    if "failure" in child_names:
        return "failed"
    if "skipped" in child_names:
        return "skipped"
    return "passed"


def collect_junit_stats(junit_dir):
    directory = Path(junit_dir)
    if not directory.is_dir():
        return None, "missing"
    xml_files = sorted(path for path in directory.glob("*.xml") if path.is_file())
    if not xml_files:
        return None, "missing"

    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for xml_file in xml_files:
        try:
            root = ET.parse(xml_file).getroot()
        except (ET.ParseError, OSError):
            return None, "invalid"
        for element in root.iter():
            if local_name(element.tag) == "testcase":
                counts[classify_test_case(element)] += 1
    return counts, None


def escape_html(value):
    return html.escape(str(value), quote=True)


def build_message(project, ci, branch, commit, status, stats, stats_error, run_url):
    short_commit = commit[:7] if commit else "unknown"
    emoji = STATUS_EMOJI.get(status, "ℹ️")
    lines = [f"{emoji} UI tests: {escape_html(status)}"]
    lines.append(f"<b>Project:</b> {escape_html(project)}")
    lines.append(f"<b>CI:</b> {escape_html(ci)}")
    lines.append(f"<b>Branch:</b> {escape_html(branch)}")
    lines.append(f"<b>Commit:</b> <code>{escape_html(short_commit)}</code>")
    if stats is None:
        if stats_error == "invalid":
            lines.append("<b>Tests:</b> statistics unavailable (invalid JUnit XML)")
        else:
            lines.append("<b>Tests:</b> not run (no JUnit XML results)")
    else:
        lines.append(
            f"<b>Tests:</b> passed={stats['passed']} • failed={stats['failed']} • errors={stats['errors']} • skipped={stats['skipped']}"
        )
        if sum(stats.values()) == 0:
            lines.append("<i>JUnit XML contains 0 test cases</i>")
    if run_url:
        escaped_url = escape_html(run_url)
        lines.append(f'<b>Run:</b> <a href="{escaped_url}">{escaped_url}</a>')
    return "\n".join(lines)


def response_description(response):
    try:
        body = response.read()
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return ""
    if isinstance(data, dict) and isinstance(data.get("description"), str):
        return data["description"][:200]
    return ""


def redact_secrets(text, token, chat_id):
    for secret in (token, chat_id):
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def send_telegram_message(token, chat_id, text, api_base_url, timeout):
    url = f"{api_base_url.rstrip('/')}/bot{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = response.status
            body = response.read()
    except HTTPError as error:
        description = redact_secrets(response_description(error), token, chat_id)
        if description:
            return False, f"HTTP {error.code}: {description}"
        return False, f"HTTP {error.code}"
    except URLError as error:
        reason = getattr(error, "reason", error)
        if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
            return False, "timeout"
        return False, f"connection error ({reason})"
    except (TimeoutError, socket.timeout):
        return False, "timeout"
    except Exception:
        return False, "request failed"

    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, f"invalid JSON response (HTTP {status_code})"
    if not isinstance(result, dict) or result.get("ok") is not True:
        description = ""
        if isinstance(result, dict) and isinstance(result.get("description"), str):
            description = redact_secrets(result["description"][:200], token, chat_id)
        if description:
            return False, f"Telegram API ok=false (HTTP {status_code}): {description}"
        return False, f"Telegram API ok=false (HTTP {status_code})"
    return True, f"HTTP {status_code}, ok=true"


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Send a Telegram notification for CI test results")
    parser.add_argument("--project", default=os.environ.get("PROJECT_NAME", "unknown"))
    parser.add_argument("--ci", default=os.environ.get("CI_NAME", "unknown"))
    parser.add_argument("--branch", default=os.environ.get("BRANCH", "unknown"))
    parser.add_argument("--commit", default=os.environ.get("COMMIT_SHA", ""))
    parser.add_argument("--run-url", default=os.environ.get("RUN_URL", ""))
    parser.add_argument("--status", default=os.environ.get("NOTIFICATION_STATUS", "UNKNOWN"))
    parser.add_argument("--junit-dir", default=os.environ.get("JUNIT_DIR", "build/test-results/test"))
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("TELEGRAM_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    stats, stats_error = collect_junit_stats(args.junit_dir)
    message = build_message(
        project=args.project,
        ci=args.ci,
        branch=args.branch,
        commit=args.commit,
        status=args.status,
        stats=stats,
        stats_error=stats_error,
        run_url=args.run_url,
    )

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("::warning::Telegram secrets are not configured; notification skipped")
        return 0

    api_base_url = os.environ.get("TELEGRAM_API_BASE_URL", DEFAULT_API_BASE_URL)
    sent, detail = send_telegram_message(
        token=token,
        chat_id=chat_id,
        text=message,
        api_base_url=api_base_url,
        timeout=args.timeout,
    )
    if sent:
        print(f"Telegram notification sent ({detail})")
    else:
        print(f"::warning::Telegram notification failed: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
