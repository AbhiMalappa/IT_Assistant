"""
Claude API client — kept for backwards compatibility and utility use.
The main agentic loop and system prompt live in bot/agent.py.
"""
import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-sonnet-4-20250514"
