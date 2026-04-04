## Token Efficiency

- Prefer targeted file reads (specific line ranges) over full-file reads.
- Run `pytest tests/ -q` by default. Use `-v` only when investigating failures.
- Use Glob/Grep with specific patterns — avoid broad exploratory searches.
- Don't re-read files already in context.
