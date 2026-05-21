from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path


DB_PATH = Path(r"C:\Users\Dhruva\.n8n\database.sqlite")
WORKFLOW_ID = "cya4w5XS7Sk4XVnu"

OLD = "I heard an email request, but I still need ' + missing.join(' and ') + ' before I can send it."
NEW = "Please repeat the email address and message clearly."


def main() -> None:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT versionId, nodes FROM workflow_entity WHERE id = ?", (WORKFLOW_ID,))
    row = cur.fetchone()
    if row is None:
      raise RuntimeError("Workflow not found")

    nodes = json.loads(row["nodes"])
    changed = False
    for node in nodes:
        if node.get("name") != "Parse Tool Choice":
            continue
        params = node.setdefault("parameters", {})
        code = params.get("jsCode", "")
        if OLD in code:
            params["jsCode"] = code.replace(OLD, NEW)
            changed = True

    if not changed:
        raise RuntimeError("Expected Parse Tool Choice email error string not found")

    nodes_json = json.dumps(nodes, separators=(",", ":"))
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    cur.execute(
        "UPDATE workflow_entity SET nodes = ?, updatedAt = ? WHERE id = ?",
        (nodes_json, timestamp, WORKFLOW_ID),
    )
    cur.execute(
        "UPDATE workflow_history SET nodes = ?, updatedAt = ? WHERE versionId = ?",
        (nodes_json, timestamp, row["versionId"]),
    )
    con.commit()
    con.close()
    print("Patched Parse Tool Choice with shorter email error response.")


if __name__ == "__main__":
    main()
