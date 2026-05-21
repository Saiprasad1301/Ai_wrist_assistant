from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path


DB_PATH = Path(r"C:\Users\Dhruva\.n8n\database.sqlite")
WORKFLOW_ID = "cya4w5XS7Sk4XVnu"
WORKSPACE = Path(r"C:\n8n automation")
BACKUP_PATH = WORKSPACE / "voice-assistant-before-gemini-intent-patch.json"
EXPORT_PATH = WORKSPACE / "voice-assistant-gemini-intent-export.json"


OLD_RECIPIENT_BLOCK = """  const transcriptRecipient = extractEmailCandidateFromTranscript(transcript);
  const to = normalizeSpokenEmail(
    transcriptRecipient || toolInput.to || toolInput.email || toolInput.recipient || toolInput.sendTo
  );"""

NEW_RECIPIENT_BLOCK = """  const transcriptRecipient = extractEmailCandidateFromTranscript(transcript);
  const candidateRecipients = [
    transcriptRecipient,
    toolInput.to,
    toolInput.email,
    toolInput.recipient,
    toolInput.sendTo,
  ].map(normalizeSpokenEmail).filter(Boolean);
  const to =
    candidateRecipients.find((value) => isValidEmail(value) && !isPlaceholderEmail(value)) ||
    candidateRecipients[0] ||
    '';"""


def load_workflow(cursor: sqlite3.Cursor) -> sqlite3.Row:
    cursor.execute(
        """
        SELECT id, name, versionId, activeVersionId, nodes, connections
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
    saw_intent_node = False
    saw_parse_node = False

    for node in nodes:
        if node.get("name") == "Groq LLM - Process Intent":
            params = node.setdefault("parameters", {})
            params["method"] = "POST"
            params["url"] = "http://127.0.0.1:5003/intent"
            params["sendHeaders"] = True
            params["headerParameters"] = {
                "parameters": [
                    {"name": "Content-Type", "value": "application/json"},
                ]
            }
            params["sendBody"] = True
            params["specifyBody"] = "json"
            params["jsonBody"] = "={{ $json.groqBody }}"
            params["options"] = {}
            saw_intent_node = True

        if node.get("name") == "Parse Tool Choice":
            params = node.setdefault("parameters", {})
            code = params.get("jsCode", "")
            if OLD_RECIPIENT_BLOCK not in code:
                if NEW_RECIPIENT_BLOCK not in code:
                    raise RuntimeError("Could not find recipient selection block in Parse Tool Choice")
            else:
                code = code.replace(OLD_RECIPIENT_BLOCK, NEW_RECIPIENT_BLOCK)
                params["jsCode"] = code
            saw_parse_node = True

    if not saw_intent_node:
        raise RuntimeError("Missing expected node: Groq LLM - Process Intent")
    if not saw_parse_node:
        raise RuntimeError("Missing expected node: Parse Tool Choice")

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
                    "versionId": row["versionId"],
                    "activeVersionId": row["activeVersionId"],
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

    version_ids = [row["versionId"]]
    if row["activeVersionId"] and row["activeVersionId"] not in version_ids:
        version_ids.append(row["activeVersionId"])
    for version_id in version_ids:
        cursor.execute(
            """
            UPDATE workflow_history
            SET nodes = ?, updatedAt = ?
            WHERE workflowId = ? AND versionId = ?
            """,
            (nodes_json, timestamp, WORKFLOW_ID, version_id),
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
                    "nodes": patched_nodes,
                    "connections": original_connections,
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Backed up workflow to {BACKUP_PATH}")
    print("Patched intent HTTP node to local Gemini service")
    print("Patched email recipient selection to prefer validated addresses")
    print(f"Exported patched workflow to {EXPORT_PATH}")


if __name__ == "__main__":
    main()
