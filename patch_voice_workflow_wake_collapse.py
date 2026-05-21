from __future__ import annotations

import datetime as dt
import json
import sqlite3
import textwrap
from pathlib import Path


DB_PATH = Path(r"C:\Users\Dhruva\.n8n\database.sqlite")
WORKFLOW_ID = "cya4w5XS7Sk4XVnu"
WORKSPACE = Path(r"C:\n8n automation")
BACKUP_PATH = WORKSPACE / "voice-assistant-before-wake-collapse-patch.json"
EXPORT_PATH = WORKSPACE / "voice-assistant-wake-collapse-export.json"

DETECT_WAKE_WORD_CODE = textwrap.dedent(
    """
    const transcript = String($json.text ?? '');
    const body = $('Webhook - Receive Audio').item.json.body ?? {};
    const wakeWord = String(body.wake_word ?? 'assistant');

    function normalize(value) {
      return String(value)
        .toLowerCase()
        .replace(/[^a-z0-9\\s]/g, ' ')
        .replace(/\\s+/g, ' ')
        .trim();
    }

    const normalizedTranscript = normalize(transcript);
    const normalizedWakeWord = normalize(wakeWord);
    const transcriptTokens = normalizedTranscript ? normalizedTranscript.split(' ') : [];
    const wakeTokens = normalizedWakeWord ? normalizedWakeWord.split(' ') : [];

    let responseTranscript = transcript;
    if (wakeTokens.length === 1 && transcriptTokens.length > 0 && transcriptTokens.every(token => token === wakeTokens[0])) {
      responseTranscript = wakeWord;
    }

    const detected = normalizedWakeWord.length > 0 && normalize(responseTranscript).includes(normalizedWakeWord);

    return {
      detected,
      wake_word: wakeWord,
      transcript: responseTranscript,
      mode: 'wake_check'
    };
    """
).strip()


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
    seen = False
    for node in nodes:
        if node.get("name") == "Detect Wake Word":
            node.setdefault("parameters", {})["jsCode"] = DETECT_WAKE_WORD_CODE
            seen = True
            break

    if not seen:
        raise RuntimeError("Missing expected node: Detect Wake Word")
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
    print(f"Patched workflow {WORKFLOW_ID} to collapse repeated wake-word transcripts")
    print(f"Exported patched workflow to {EXPORT_PATH}")


if __name__ == "__main__":
    main()
