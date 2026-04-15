# Contributing to claude-cortex

Thanks for your interest in contributing. This project is young and contributions are welcome.

## Quick start

```bash
git clone https://github.com/rudymartinezai/claude-cortex.git
cd claude-cortex
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cortex init
```

## Development workflow

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run tests: `python -m pytest tests/`
5. Commit with a clear message
6. Open a PR

## What we're looking for

- Bug fixes
- New storage backends (PostgreSQL, DuckDB, etc.)
- Improved cluster classification (ML-based instead of keyword matching)
- Better secret scrubbing patterns
- Documentation improvements
- Test coverage

## Code style

- Python 3.9+ compatible
- No external linter enforced yet — just keep it readable
- Docstrings on public functions
- Type hints where they help

## Security

If you find a security vulnerability, please report it privately via [GitHub Security Advisories](https://github.com/rudymartinezai/claude-cortex/security/advisories) instead of opening a public issue.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
