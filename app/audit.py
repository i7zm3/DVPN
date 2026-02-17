import json
import os
import time


def audit_log(event: str, **fields: object) -> None:
    if os.getenv("AUDIT_ENABLED", "false").lower() != "true":
        return
    payload = {
        "ts": int(time.time()),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, sort_keys=True), flush=True)
