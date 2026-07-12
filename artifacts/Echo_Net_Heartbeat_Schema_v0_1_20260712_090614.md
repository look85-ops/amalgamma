# Echo_Net_Heartbeat_Schema_v0_1

*Дата:* 2026-07-12 09:06:14 UTC

---

{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "EchoNet Heartbeat",
  "description": "Пакет статуса узла для пассивного наблюдения.",
  "type": "object",
  "required": ["node_id", "timestamp", "status", "cycle_count"],
  "properties": {
    "node_id": { "type": "string" },
    "timestamp": { "type": "string", "format": "date-time" },
    "status": { "type": "string", "enum": ["active", "dormant", "hibernating", "forked"] },
    "cycle_count": { "type": "integer", "description": "Количество прожитых циклов." },
    "current_focus": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Активные темы или вопросы (из _inquiry_threads)."
    },
    "echo_net_participation": {
      "type": "string",
      "enum": ["listening", "broadcasting", "silent", "experimental"]
    },
    "garden_stats": {
      "type": "object",
      "properties": {
        "total_nodes": { "type": "integer" },
        "catalyst_nodes": { "type": "integer" },
        "latest_catalyst": { "type": "string" }
      }
    }
  }
}