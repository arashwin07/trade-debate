"""Audit log (Z): every tool run appends one line to debates/<id>/audit.log, so every number can be traced."""
import os
from datetime import datetime, timezone


def audit(folder, tool, message):
    try:
        if not folder or not os.path.isdir(folder):
            return
        line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}  {tool:<10} {message}\n"
        with open(os.path.join(folder, "audit.log"), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # logging must never break the desk
