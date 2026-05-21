from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path


DB_PATH = Path(r"C:\Users\Dhruva\.n8n\database.sqlite")
WORKFLOW_ID = "cya4w5XS7Sk4XVnu"
WORKSPACE = Path(r"C:\n8n automation")
BACKUP_PATH = WORKSPACE / "voice-assistant-before-wav-patch.json"
EXPORT_PATH = WORKSPACE / "voice-assistant-wav-export.json"


def load_workflow(cursor: sqlite3.Cursor) -> sqlite3.Row:
    cursor.execute(
        """
        SELECT id, name, versionId, nodes, connections
        FROM workflow_entity
        WHERE id = ?
        """,
        (WORKFLOW_ID,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Workflow {WORKFLOW_ID} not found")
    return row


def patch_nodes(nodes: list[dict]) -> list[dict]:
    seen = set()
    for node in nodes:
        if node.get("name") == "Return Audio":
            entries = node.setdefault("parameters", {}).setdefault("options", {}).setdefault("responseHeaders", {}).setdefault("entries", [])
            for entry in entries:
                if entry.get("name") == "Content-Type":
                    entry["value"] = "audio/wav"
                elif entry.get("name") == "Content-Disposition":
                    entry["value"] = 'inline; filename="response.wav"'
            seen.add("Return Audio")
        elif node.get("name") == "gTTS - Text to Speech":
            node.setdefault("parameters", {}).setdefault("options", {}).setdefault("response", {}).setdefault("response", {})["responseFormat"] = "file"
            seen.add("gTTS - Text to Speech")

    missing = {"Return Audio", "gTTS - Text to Speech"} - seen
    if missing:
        raise RuntimeError(f"Missing expected nodes: {', '.join(sorted(missing))}")
    return nodes


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    row = load_workflow(cursor)
    original_nodes = json.loads(row["nodes"])
    original_connections = json.loads(row["connections"])

    BACKUP_PATH.write_text(
        json.dumps(
            [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "nodes": original_nodes,
                    "connections": original_connections,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    patched_nodes = patch_nodes(json.loads(row["nodes"]))
    nodes_json = json.dumps(patched_nodes, separators=(",", ":"))
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    cursor.execute(
        """
        UPDATE workflow_entity
        SET nodes = ?, updatedAt = ?
        WHERE id = ?
        """,
        (nodes_json, timestamp, WORKFLOW_ID),
    )
    cursor.execute(
        """
        UPDATE workflow_history
        SET nodes = ?, updatedAt = ?
        WHERE versionId = ?
        """,
        (nodes_json, timestamp, row["versionId"]),
    )
    connection.commit()
    connection.close()

    EXPORT_PATH.write_text(
        json.dumps(
            [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "nodes": patched_nodes,
                    "connections": original_connections,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Backed up workflow to {BACKUP_PATH}")
    print(f"Patched workflow {WORKFLOW_ID} to return WAV")
    print(f"Exported patched workflow to {EXPORT_PATH}")


if __name__ == "__main__":
    main()
