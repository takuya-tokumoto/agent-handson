# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains a Japanese-language hands-on tutorial document (`04_03_ハンズオンシナリオ案.md`) for building an **internal Tech News auto-summary agent** using three technologies:

- **Claude Agent SDK** (`claude-agent-sdk`) — orchestrates the main article-generation agent
- **Playwright MCP** (`@playwright/mcp`) — web scraping via MCP stdio server (headless browser)
- **A2A Protocol** (`a2a-sdk`) — inter-agent communication for draft review

## Architecture

The tutorial produces a 3-file Python project (`agent-handson/`):

1. **`main.py`** — CLI entry point. Accepts a URL and free-form prompt, then runs a 3-step pipeline:
   - Draft generation (Claude Agent SDK + Playwright MCP for web reading)
   - A2A review (sends draft to the review agent server)
   - Final revision (Claude Agent SDK incorporates review feedback)
   - Outputs `output/draft_*.md` and `output/final_*.md`

2. **`ops_review_agent.py`** — A2A review server (Starlette/uvicorn on port 9999). Performs rule-based review checking for required sections (要約, 重要ポイント, 参考リンク, 次アクション), minimum length, and presence of URLs.

3. **`tools_action_manager.py`** — Utility module providing `save_markdown()` and `a2a_review()` (A2A client that calls the review server).

## Running the Tutorial Project

Prerequisites: Python 3.10+, Node.js 18+, `ANTHROPIC_API_KEY` env var set.

```bash
# Setup
mkdir -p agent-handson && cd agent-handson
python3 -m venv .venv && source .venv/bin/activate
pip install claude-agent-sdk a2a-sdk[http-server] httpx

# Terminal 1: Start review agent
python ops_review_agent.py
# Verify: curl http://localhost:9999/.well-known/agent-card.json

# Terminal 2: Run main agent
python main.py
```

## Key Details

- The tutorial targets **Windows + WSL2 Ubuntu 22.04** environments (sections 1.1–1.7 cover WSL/Docker/DNS setup)
- All agent output is in Japanese
- The review agent uses simple string-matching heuristics, not LLM-based review
- Playwright MCP runs as a stdio subprocess managed by Claude Agent SDK's `mcp_servers` config
