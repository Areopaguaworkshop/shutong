#!/usr/bin/env python3
"""Export Shutong's MCP tool definitions for the TypeScript server.

Run from the package root:

    PYTHONPATH=../shutong-backend ../shutong-backend/.venv/bin/python \
      scripts/generate-tools.py > tools.generated.json
"""
from __future__ import annotations

import json

from shutong_backend.mcp_server import TOOL_DEFINITIONS

print(json.dumps(TOOL_DEFINITIONS, ensure_ascii=False, indent=2, sort_keys=True))
