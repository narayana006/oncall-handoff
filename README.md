# oncall-handoff

Summarize an on-call shift from exported pages, chat messages and tickets into a handoff note the next engineer can read in a minute.

**Status: first working version (0.1.0).** It reads JSON exports from files, builds the note with deterministic rules (what is still open, what was flaky, what to watch), and writes Markdown or JSON. Posting to Slack works but is a preview unless you add `--send`. It does **not** yet pull from PagerDuty, Slack or a ticket system itself, and there is no built-in scheduler; see [Limitations](#limitations).

## Install

```bash
pip install git+https://github.com/narayana006/oncall-handoff
```

Python 3.10 or newer, no third-party dependencies.

## Quick start

The repository includes a fictional shift in `examples/shift/`. `--now` pins the end of the shift so the output is reproducible; leave it out to use the current time.

```console
$ oncall-handoff --input examples/shift --since 24h --now 2026-03-03T09:00:00Z
# On-call handoff

Shift window: 2026-03-02 09:00 to 2026-03-03 09:00 UTC

**7 pages** (5 high urgency), **2 still open**, **1 flaky alert**, **2 open tickets**.

## Still open

- **orders-db**: [Replication lag above 30s on orders-db replica 2](https://pager.example.com/incidents/P1001) (high urgency, acknowledged, open 34.3 h, since Sun 22:40, carried over from before this shift)
- **edge-proxy**: [Certificate for api.example.com expires in 6 days](https://pager.example.com/incidents/P1007) (low urgency, triggered, open 3.0 h, since Tue 06:00)
- [OPS-412](https://tickets.example.com/OPS-412): Replay failed payment webhooks from 2 March 19:30-20:10 (Open, P1, assignee tomas)
- [OPS-409](https://tickets.example.com/OPS-409): Tune checkout-api latency alert threshold (In Progress, P3, unassigned)

## Flaky or noisy

- **checkout-api**: checkout-api p99 latency above 920ms (fired 3 times between Mon 10:12 and Tue 02:31; median time to clear 7 min; mostly self-clearing: likely flapping, consider tuning the threshold)

## Watch

- **email-worker**: [Queue depth above 10000 on email-worker](https://pager.example.com/incidents/P1008) was resolved at Tue 08:05, shortly before handoff. It may recur.
- priya in #incidents, Mon 20:15: Enabled the retry queue as a workaround. Failed webhooks from 19:30 to 20:10 still need to be replayed.
- priya in #incidents, Mon 21:15: Resolving. Follow-up: replay job is tracked in OPS-412.
- priya in #oncall, Tue 02:40: Heads up for next shift: orders-db replica 2 is still lagging, the DBA team is rebuilding it. Do not fail over to it.
- priya in #incidents, Tue 08:50: Queue drained. Workers are still at 8, someone needs to scale them back down tomorrow.

## Resolved this shift

- Mon 10:12 **checkout-api**: [checkout-api p99 latency above 800ms](https://pager.example.com/incidents/P1002) (resolved in 7 min)
- Mon 11:05 **search-indexer**: [Disk usage 91% on search-indexer-3](https://pager.example.com/incidents/P1003) (resolved in 1.5 h)
- Mon 14:48 **checkout-api**: [checkout-api p99 latency above 850ms](https://pager.example.com/incidents/P1004) (resolved in 5 min)
- Mon 19:30 **payments-gateway**: [Payment webhook failures above 5%](https://pager.example.com/incidents/P1005) (resolved in 1.7 h)
- Tue 02:31 **checkout-api**: [checkout-api p99 latency above 920ms](https://pager.example.com/incidents/P1006) (resolved in 8 min)
- Tue 07:20 **email-worker**: [Queue depth above 10000 on email-worker](https://pager.example.com/incidents/P1008) (resolved in 45 min)

## Tickets closed

- [OPS-405](https://tickets.example.com/OPS-405): Expand search-indexer-3 data volume (Done, P2, assignee lena)

## Busiest threads

- #incidents, Mon 19:35, 4 replies from 3 people: payments-gateway: webhook failures at 7%, looking now

## Numbers

- Pages by service: checkout-api 3, edge-proxy 1, email-worker 1, payments-gateway 1, search-indexer 1
- Median time to resolve: 26 min
```

## What goes into the note

| Section | Rule |
| --- | --- |
| Still open | Pages that are not resolved, including ones that fired before the window ("carried over"), high urgency first. Tickets created or updated in the window whose status is not a closed one. Urgent tickets (P0/P1, critical, high, ...) first. |
| Flaky or noisy | Pages for the same service whose titles match after numbers and ids are removed, so "latency above 800ms" and "latency above 920ms" are one alert. An alert that fired at least `--flaky-threshold` times (default 2) is listed; if most firings cleared within 10 minutes it is called out as flapping. |
| Watch | High-urgency pages resolved in the last 2 hours of the shift, and chat messages containing handoff phrases such as "heads up", "keep an eye", "workaround", "follow-up", "still failing", "silenced", "tomorrow", "next shift". |
| Resolved this shift | Every resolved page with its time to resolve. |
| Tickets closed | Tickets updated in the window that are now in a closed status. |
| Busiest threads | Up to three chat threads with at least two replies, by reply count. |
| Numbers | Pages per service and the median time to resolve. |

All times are shown in UTC.

## Input files

Pass a directory with `--input DIR` (it looks for `pages.json`, `slack.json` and `tickets.json`; each is optional) or name files individually with `--pages`, `--slack` and `--tickets`. Each file is a JSON list of objects, or an object wrapping the list.

| File | Wrapper keys | Fields read |
| --- | --- | --- |
| pages | `incidents`, `pages` | `id`/`incident_number`, `title`/`summary`, `service` (string or `{"summary": ...}`), `urgency`, `status` (`triggered`, `acknowledged`, `resolved`), `created_at` (required), `resolved_at`, `html_url` |
| slack | `messages` | `ts` (required), `user_name`/`user`, `text`, `channel`, `thread_ts`, `permalink` |
| tickets | `issues`, `tickets` | `key`/`id`, `title`/`summary`, `status`, `priority`, `assignee`, `created_at`/`created`, `updated_at`/`updated`, `url`; a nested `fields` object is flattened |

Timestamps may be ISO 8601 or epoch seconds (as Slack exports them). The page fields follow the shape of a PagerDuty incidents export and the ticket fields a Jira issue search, so those can usually be passed through unchanged.

## Options

```text
--since 12h|24h|7d     length of the shift window (default 24h)
--now TIME             end of the window, ISO 8601 (default: current time)
--format markdown|json output format (default markdown)
-o, --output FILE      write to a file instead of stdout
--title TEXT           note heading (default "On-call handoff")
--flaky-threshold N    firings needed to call an alert flaky (default 2)
--post CHANNEL         render for Slack; preview only unless --send
--send                 with --post, really post (reads SLACK_BOT_TOKEN)
```

Exit codes: `0` success, `1` Slack post failed, `2` bad input or usage.

## Posting to Slack

`--post` on its own is a dry run: it prints the Slack-formatted message and sends nothing.

```console
$ oncall-handoff --input examples/shift --now 2026-03-03T09:00:00Z --post '#oncall'
Dry run: would post the following to #oncall. Add --send to post it.

*On-call handoff*

Shift window: 2026-03-02 09:00 to 2026-03-03 09:00 UTC

*7 pages* (5 high urgency), *2 still open*, *1 flaky alert*, *2 open tickets*.

*Still open*
...
```

To send it, add `--send` and set `SLACK_BOT_TOKEN` to a bot token with the `chat:write` scope. The message goes through Slack's `chat.postMessage` API. This path is covered by tests using a fake transport; it has not been exercised against a real Slack workspace yet.

## Running at shift change

There is no built-in scheduler. Until there is, a cron entry does the job once your exports land in a directory:

```cron
0 9 * * * oncall-handoff --input /var/lib/oncall/export --since 24h -o /var/lib/oncall/handoff.md
```

## Features

- [x] Read pages, chat threads and tickets for a time window (from JSON export files)
- [x] Summarize open issues, flaky systems and things to watch
- [x] Write Markdown or JSON; post to Slack behind an explicit `--send`
- [ ] Pull directly from the PagerDuty, Slack and ticket-system APIs
- [ ] Scheduled run at shift change
- [ ] Per-team configuration (watch phrases, closed statuses, time zone)

## Limitations

- Input is files only. You have to export the pages, messages and tickets yourself; the live API adapters are not written.
- The summary is rule-based. "Watch" items come from a fixed phrase list, so a note worded unusually is missed and an unrelated message containing "watch" is included. The phrase list is not configurable yet.
- Alerts are grouped by service and title text. Two different titles for the same underlying problem are not linked, and pages are not correlated with tickets or threads.
- All times are UTC; there is no time zone option.
- Slack user ids are shown as they appear in the export; they are not resolved to names.
- The real Slack call has only been tested with a fake transport.

## Development

```bash
git clone https://github.com/narayana006/oncall-handoff
cd oncall-handoff
pip install -e ".[test]"
pytest
```

## Contributing

Issues and pull requests are welcome, especially sample exports (with anything private removed) that the loaders do not handle, and handoff phrases the "Watch" rule misses.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
