# oncall-handoff

Summarize an on-call shift from pages, Slack and tickets into a clear handoff note.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A command-line tool.

**The problem it solves:** Context is lost between on-call shifts and the next engineer rediscovers the same problems.

## Who it is for

Engineers handing over an on-call shift.

## How it will work

1. The tool collects the shift's pages, incident chat threads and tickets.
2. It summarises what is still open, what was flaky and what the next person should watch.
3. It posts the note to a chat channel or saves it as Markdown.

## Planned features

Unticked items are not built yet.

- [ ] Pull pages, Slack threads and tickets for a time window
- [ ] Summarize open issues, flaky systems and things to watch
- [ ] Post to Slack or write Markdown
- [ ] Scheduled run at shift change

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```bash
oncall-handoff --since 24h --post '#oncall'
```

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## License

[MIT](LICENSE)
