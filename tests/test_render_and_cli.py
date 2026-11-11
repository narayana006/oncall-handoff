import io
import json

import pytest

from conftest import NOW, utc
from oncall_handoff.analyze import analyze
from oncall_handoff.cli import run
from oncall_handoff.render import to_markdown, to_slack
from oncall_handoff.slack import MAX_TEXT, SlackError, build_payload, post_message
from oncall_handoff.sources import Shift


def cli(*argv, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    code = run(list(argv), stdout=out, stderr=err, **kwargs)
    return code, out.getvalue(), err.getvalue()


class FakeSlack:
    def __init__(self, reply=None, error=None):
        self.calls, self.reply, self.error = [], reply or {"ok": True, "ts": "1.2"}, error

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, json.loads(body)))
        if self.error:
            raise self.error
        return self.reply


def test_quiet_shift_note():
    note = to_markdown(analyze(Shift(), utc(2026, 3, 2, 9), utc(2026, 3, 3, 9)))
    assert "Quiet shift" in note and "## Still open" not in note


def test_markdown_note_from_examples(examples):
    code, out, _ = cli("--input", str(examples), "--since", "24h", "--now", NOW, "--title", "Payments handoff")
    assert code == 0
    assert out.startswith("# Payments handoff\n\nShift window: 2026-03-02 09:00 to 2026-03-03 09:00 UTC")
    assert "**7 pages** (5 high urgency), **2 still open**, **1 flaky alert**, **2 open tickets**." in out
    assert "carried over from before this shift" in out
    assert "fired 3 times between Mon 10:12 and Tue 02:31" in out and "likely flapping" in out
    assert "Do not fail over to it." in out
    assert "previous shift" not in out  # message outside the window
    assert "OPS-390" not in out  # ticket with no activity in the window
    for heading in ["Still open", "Flaky or noisy", "Watch", "Resolved this shift", "Tickets closed",
                    "Busiest threads", "Numbers"]:
        assert f"## {heading}" in out


def test_shorter_window_and_threshold_change_the_result(examples):
    _, out, _ = cli("--input", str(examples), "--since", "4h", "--now", NOW)
    assert "**2 pages**" in out and "## Flaky or noisy" not in out
    _, out, _ = cli("--input", str(examples), "--now", NOW, "--flaky-threshold", "4")
    assert "## Flaky or noisy" not in out


def test_individual_files_json_format_and_output_file(examples, tmp_path):
    target = tmp_path / "note.json"
    code, out, err = cli("--pages", str(examples / "pages.json"), "--now", NOW, "--format", "json", "-o", str(target))
    assert code == 0 and out == "" and "Wrote" in err
    data = json.loads(target.read_text())
    assert len(data["pages"]) == 7 and data["open_tickets"] == [] and data["start"] == "2026-03-02T09:00:00+00:00"
    assert data["flaky"][0]["count"] == 3


def test_to_slack_converts_markdown_subset():
    text = to_slack("# Title\n\n## Still open\n\n- **api**: [db down](https://x.example.com/1) (high)\n")
    assert text == "*Title*\n\n*Still open*\n\n• *api*: <https://x.example.com/1|db down> (high)\n"


def test_post_is_a_dry_run_unless_send_is_given(examples):
    fake = FakeSlack()
    code, out, err = cli("--input", str(examples), "--now", NOW, "--post", "#oncall",
                         transport=fake, env={"SLACK_BOT_TOKEN": "test-token"})
    assert code == 0 and fake.calls == []
    assert "Dry run" in err and out.startswith("*On-call handoff*")


def test_send_posts_once_with_token_and_channel(examples):
    fake = FakeSlack()
    code, out, err = cli("--input", str(examples), "--now", NOW, "--post", "#oncall", "--send",
                         transport=fake, env={"SLACK_BOT_TOKEN": "test-token"})
    assert code == 0 and "Posted handoff note to #oncall" in err
    ((url, headers, payload),) = fake.calls
    assert url == "https://slack.com/api/chat.postMessage"
    assert headers["Authorization"] == "Bearer test-token"
    assert payload["channel"] == "#oncall" and payload["text"].startswith("*On-call handoff*")


def test_send_failures_exit_1_without_traceback(examples):
    args = ("--input", str(examples), "--now", NOW, "--post", "#oncall", "--send")
    code, _, err = cli(*args, transport=FakeSlack(), env={})
    assert code == 1 and "SLACK_BOT_TOKEN" in err
    code, _, err = cli(*args, transport=FakeSlack(reply={"ok": False, "error": "channel_not_found"}),
                       env={"SLACK_BOT_TOKEN": "t"})
    assert code == 1 and "channel_not_found" in err
    code, _, err = cli(*args, transport=FakeSlack(error=OSError("network down")), env={"SLACK_BOT_TOKEN": "t"})
    assert code == 1 and "could not reach Slack" in err


def test_long_messages_are_truncated_for_slack():
    payload = build_payload("#c", "x" * (MAX_TEXT + 500))
    assert len(payload["text"]) < MAX_TEXT + 50 and payload["text"].endswith("(truncated)")
    with pytest.raises(SlackError):
        post_message("#c", "hi", "", FakeSlack())


def test_usage_and_input_errors(examples, tmp_path, capsys):
    with pytest.raises(SystemExit):
        cli()  # no input
    with pytest.raises(SystemExit):
        cli("--input", str(examples), "--send")  # --send without --post
    capsys.readouterr()
    code, _, err = cli("--input", str(examples), "--since", "soon")
    assert code == 2 and "invalid duration" in err
    code, _, err = cli("--pages", str(tmp_path / "missing.json"))
    assert code == 2 and "cannot read" in err
    code, _, err = cli("--input", str(examples), "--now", "noon")
    assert code == 2 and "unrecognised timestamp" in err
