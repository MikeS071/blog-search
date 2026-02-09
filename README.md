# AI Engram

Semantic search and persistent conversation memory for markdown workspaces — built as an [MCP](https://modelcontextprotocol.io/) server.

AI Engram gives your AI assistant long-term memory and deep search over your markdown content. It combines BM25 keyword search with sentence-transformer semantic search, plus a persistent memory system that stores decisions, preferences, and context across conversations.

## Features

- **BM25 + Semantic hybrid search** across markdown files
- **Persistent conversation memory** — remember decisions, preferences, insights, tasks
- **Semantic recall** — find relevant memories by meaning, not just keywords
- **Cross-search** — query both memory and blog content in a single call
- **File watcher** — auto-reindexes when markdown files change
- **Collection filtering** — search across posts, outlines, prompts, or knowledge base

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_blog` | BM25 keyword search across markdown files |
| `semantic_search_blog` | Meaning-based search using sentence-transformers |
| `build_index` | Build or refresh the semantic search index |
| `list_blog_files` | Browse all markdown files by collection |
| `blog_stats` | File counts and word totals across collections |
| `read_blog_file` | Read full content of a markdown file |
| `remember` | Store a memory (decision, insight, preference, task, context, note) |
| `recall` | Semantic search across conversation memories |
| `recall_all` | Cross-search memories AND blog content together |
| `list_memories` | Browse stored memories with optional category filter |
| `forget` | Delete a specific memory by ID |
| `memory_stats` | Memory counts by category and storage size |
| `get_system_prompt` | Load the memory protocol instructions |

## Repository Structure

This repo contains only the AI Engram source code and configuration. Blog content (posts, outlines, prompts, knowledge base) is excluded via `.gitignore` and lives locally in the workspace.

```
aiengram_mcp.py          # MCP server — all tools, search engines, memory store
aiengram.py              # Standalone search module
pyproject.toml           # Project metadata and dependencies
.github/                 # GitHub config (Copilot instructions)
README.md                # This file
```

## Requirements

- Python >= 3.10
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

## Installation

```bash
uv pip install -e ".[mcp]"
```

## Usage

Run the MCP server:

```bash
uv run aiengram_mcp.py
```

Or add to your MCP client configuration (e.g. VS Code `settings.json`):

```json
{
  "mcp": {
    "servers": {
      "aiengram": {
        "command": "uv",
        "args": ["run", "aiengram_mcp.py"],
        "cwd": "/path/to/your/markdown/workspace"
      }
    }
  }
}
```

Point `cwd` at any directory containing markdown files. AI Engram auto-discovers content in `Blog Posts/`, `Post Outlines/`, `Prompts/`, and knowledge base files.

## Roadmap

- [ ] **Single installation script** — one-command setup that installs all dependencies, builds the index, and configures the MCP server
- [ ] **Docker deployment** — containerized deployment with all relevant services (MCP server, embedding model, file watcher) available out of the box
- [ ] **Memory search improvements** — full-text search across memories, tag-based filtering, and date-range queries
- [ ] **Cross-conversation summaries** — auto-summarize clusters of related memories into condensed session summaries to reduce noise over time

## License

MIT
