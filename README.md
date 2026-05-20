# oncall-handoff

> Summarize an on-call shift from pages, Slack and tickets into a clear handoff note.

**Status:** 🚧 Early stage — design and roadmap published, implementation in progress. Stars, issues and ideas welcome.

## Why

Context is lost between on-call shifts and the next engineer rediscovers the same problems.

## Planned features

- [ ] Pull pages, Slack threads and tickets for a time window
- [ ] Summarize open issues, flaky systems and things to watch
- [ ] Post to Slack or write Markdown
- [ ] Scheduled run at shift change

## Intended usage

```
oncall-handoff --since 24h --post '#oncall'
```

_The interface above is the target design and may change._

## Roadmap

1. Core implementation of the first feature set
2. Examples and tests
3. CI and first tagged release
4. Docs and integrations

## Contributing

Contributions are welcome. Open an issue to discuss an idea or pick an unchecked item from the feature list.

## License

[MIT](LICENSE)
