#!/usr/bin/env python3
"""Minimal stdio MCP server used by real-transport tests.

Speaks a subset of the JSON-RPC MCP protocol: initialize handshake,
notifications/initialized, tools/list, tools/call. Exposes a single
tool ``echo`` that returns its arguments.

Not a general-purpose implementation — the shape here is only enough
to exercise the client's stdio path end-to-end.
"""

from __future__ import annotations

import json
import sys


def _reply(msg_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method")
        msg_id = msg.get("id")

        if method == "initialize":
            _reply(msg_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo-server", "version": "1.0.0"},
            })
        elif method == "notifications/initialized":
            # Notifications carry no id — no reply required.
            continue
        elif method == "tools/list":
            _reply(msg_id, {
                "tools": [{
                    "name": "echo",
                    "description": "Return the arguments as a string.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                    },
                }],
            })
        elif method == "tools/call":
            params = msg.get("params", {})
            args = params.get("arguments", {})
            text = args.get("text", "")
            _reply(msg_id, {"content": [{"type": "text", "text": f"echo: {text}"}]})
        elif method == "shutdown":
            _reply(msg_id, {})
            return
        else:
            _reply(msg_id, error={"code": -32601, "message": f"unknown method: {method}"})


if __name__ == "__main__":
    main()
