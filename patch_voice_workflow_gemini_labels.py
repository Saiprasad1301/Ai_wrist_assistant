from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path


DB_PATH = Path(r"C:\Users\Dhruva\.n8n\database.sqlite")
WORKFLOW_ID = "cya4w5XS7Sk4XVnu"
WORKSPACE = Path(r"C:\n8n automation")
BACKUP_PATH = WORKSPACE / "voice-assistant-before-gemini-labels-patch.json"
EXPORT_PATH = WORKSPACE / "voice-assistant-gemini-labels-export.json"

RENAMES = {
    "Build Groq Request": "Build Gemini Intent Request",
    "Groq LLM - Process Intent": "Gemini 2.5 Flash - Process Intent",
}


def rename_connection_references(connections: dict) -> dict:
    renamed = {}
    for source_name, outputs in connections.items():
        new_source_name = RENAMES.get(source_name, source_name)
        for output_group in outputs.get("main", []):
            for connection in output_group:
                target_name = connection.get("node")
                if target_name in RENAMES:
                    connection["node"] = RENAMES[target_name]
        renamed[new_source_name] = outputs
    return renamed


def main() -> None:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()
    row = cursor.execute(
        """
        SELECT id, name, versionId, activeVersionId, nodes, connections
        FROM workflow_entity
        WHERE id = ?
        """,
        (WORKFLOW_ID,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Workflow {WORKFLOW_ID} not found")

    nodes = json.loads(row["nodes"])
    connections = json.loads(row["connections"])

    BACKUP_PATH.write_text(
        json.dumps(
            [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "versionId": row["versionId"],
                    "activeVersionId": row["activeVersionId"],
                    "nodes": nodes,
                    "connections": connections,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    seen = set()
    for node in nodes:
        old_name = node.get("name")
        if old_name in RENAMES:
            node["name"] = RENAMES[old_name]
            seen.add(old_name)

    missing = set(RENAMES) - seen
    if missing:
        raise RuntimeError(f"Missing nodes to rename: {sorted(missing)}")

    connections = rename_connection_references(connections)
    nodes_json = json.dumps(nodes, separators=(",", ":"))
    connections_json = json.dumps(connections, separators=(",", ":"))
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    cursor.execute(
        """
        UPDATE workflow_entity
        SET nodes = ?, connections = ?, updatedAt = ?
        WHERE id = ?
        """,
        (nodes_json, connections_json, timestamp, WORKFLOW_ID),
    )

    version_ids = [row["versionId"]]
    if row["activeVersionId"] and row["activeVersionId"] not in version_ids:
        version_ids.append(row["activeVersionId"])

    for version_id in version_ids:
        cursor.execute(
            """
            UPDATE workflow_history
            SET nodes = ?, connections = ?, updatedAt = ?
            WHERE workflowId = ? AND versionId = ?
            """,
            (nodes_json, connections_json, timestamp, WORKFLOW_ID, version_id),
        )

    connection.commit()
    connection.close()

    EXPORT_PATH.write_text(
        json.dumps(
            [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "versionId": row["versionId"],
                    "activeVersionId": row["activeVersionId"],
                    "nodes": nodes,
                    "connections": connections,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Renamed nodes: {RENAMES}")
    print(f"Backed up workflow to {BACKUP_PATH}")
    print(f"Exported patched workflow to {EXPORT_PATH}")


if __name__ == "__main__":
    main()
