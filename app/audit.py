import json
import time


def audit_log(event: str, **fields: object) -> None:
    payload = {
        "ts": int(time.time()),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, sort_keys=True), flush=True)
