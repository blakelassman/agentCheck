"""Vercel's ASGI entrypoint."""
from agentcheck.hosted import create_app

app = create_app()
