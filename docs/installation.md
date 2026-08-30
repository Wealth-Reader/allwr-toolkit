# Installation

Requires Python 3.11+ (tested on 3.11–3.14). No other runtime is needed.

```bash
pip install allwr-toolkit          # core + CLI (once published to PyPI)
pip install 'allwr-toolkit[mcp]'   # with the MCP server
```

From source:

```bash
git clone https://github.com/wealthreader/allwr-toolkit
cd allwr-toolkit
pip install '.[mcp]'
```

Development setup (venv, dev dependencies, pre-commit): `make setup`.
`uv` works fine for development but is never required.
