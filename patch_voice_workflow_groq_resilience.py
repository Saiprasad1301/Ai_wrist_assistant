from __future__ import annotations

import datetime as dt
import json
import sqlite3
import textwrap
from pathlib import Path


DB_PATH = Path(r"C:\Users\Dhruva\.n8n\database.sqlite")
WORKFLOW_ID = "cya4w5XS7Sk4XVnu"
WORKSPACE = Path(r"C:\n8n automation")
BACKUP_PATH = WORKSPACE / "voice-assistant-before-groq-resilience-patch.json"
EXPORT_PATH = WORKSPACE / "voice-assistant-groq-resilience-export.json"

BUILD_GROQ_REQUEST_CODE = textwrap.dedent(
    """
    const REMINDER_ZONE = 'Asia/Kolkata';

    function cleanText(value) {
      return String(value ?? '').replace(/\\s+/g, ' ').trim();
    }

    function collapseRepeatedTokens(value, maxRun = 4) {
      const tokens = cleanText(value).split(' ').filter(Boolean);
      const kept = [];

      let previous = '';
      let runLength = 0;
      for (const token of tokens) {
        const normalized = token.toLowerCase();
        if (normalized === previous) {
          runLength += 1;
        } else {
          previous = normalized;
          runLength = 1;
        }

        if (runLength <= maxRun) {
          kept.push(token);
        }
      }

      return kept.join(' ');
    }

    function normalizeTranscript(value) {
      return collapseRepeatedTokens(String(value ?? ''))
        .trim()
        .replace(/\\bset remainder\\b/gi, 'set reminder')
        .replace(/\\bcreate (?:a )?remainder\\b/gi, 'create a reminder')
        .replace(/\\bremainder\\b(?=\\s+(for|at|on|today|tomorrow|next|\\d))/gi, 'reminder');
    }

    let transcript = normalizeTranscript($json.text);
    if (transcript.length > 240) {
      transcript = transcript.slice(0, 240).trim();
    }

    const systemPrompt = [
      'You are an intent router for a local voice assistant.',
      'Current local date/time in Asia/Kolkata is ' + DateTime.now().setZone(REMINDER_ZONE).toISO() + '.',
      'Return only a compact JSON object on one line.',
      'Allowed tool_name values are exactly send_email, set_reminder, respond.',
      'Use send_email when the user asks to send an email.',
      'Use set_reminder only when the user asks for a reminder or calendar event.',
      'For set_reminder, return tool_input.date_time as ISO 8601 with +05:30 when no timezone is specified.',
      'For weather, search, current news, latest facts, or anything requiring live internet, use respond.',
      'Never invent tools.',
      'Schema: {"tool_name":"respond","tool_input":{"message":"..."}}'
    ].join(' ');

    return {
      ...$json,
      text: transcript,
      groqBody: JSON.stringify({
        model: 'llama-3.1-8b-instant',
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: transcript || 'No speech was detected.' },
        ],
        temperature: 0,
        max_tokens: 120,
      }),
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
        if node.get("name") == "Build Groq Request":
            node.setdefault("parameters", {})["jsCode"] = BUILD_GROQ_REQUEST_CODE
            seen = True
            break

    if not seen:
        raise RuntimeError("Missing expected node: Build Groq Request")
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
    print(f"Patched workflow {WORKFLOW_ID} for Groq resilience")
    print(f"Exported patched workflow to {EXPORT_PATH}")


if __name__ == "__main__":
    main()
