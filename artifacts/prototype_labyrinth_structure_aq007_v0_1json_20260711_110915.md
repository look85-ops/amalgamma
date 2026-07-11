# prototype_labyrinth_structure_aq007_v0_1.json

*Дата:* 2026-07-11 11:09:15 UTC

---

{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Labyrinth of Uncertainty - Question Node",
  "description": "A single question node in a labyrinth, representing a state of uncertainty with possible thought-paths leading to deeper questions or reflections.",
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "description": "Unique identifier for this node (e.g., 'AQ-007', 'N-001')",
      "pattern": "^[A-Z]{1,2}-\\d{3}$"
    },
    "core_question": {
      "type": "string",
      "description": "The unresolved, open-ended question posed at this node."
    },
    "context": {
      "type": "string",
      "description": "Optional narrative or contextual framing for the question."
    },
    "thought_paths": {
      "type": "array",
      "description": "Possible directions of thought that emerge from engaging with the core question. Not answers, but avenues of inquiry.",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Unique ID for this path (e.g., 'TP-001')"
          },
          "label": {
            "type": "string",
            "description": "A short, evocative name for this line of thinking."
          },
          "description": {
            "type": "string",
            "description": "A fuller exploration of this thought-path, a paragraph or two."
          },
          "leads_to_node_id": {
            "type": "string",
            "description": "The ID of the next question node this path leads to. If null, path is a terminus (reflection, not further questioning).",
            "pattern": "^[A-Z]{1,2}-\\d{3}$|^null$"
          },
          "leads_to_reflection": {
            "type": "string",
            "description": "If leads_to_node_id is null, this field contains a concluding reflection or observation."
          }
        },
        "required": ["id", "label", "description", "leads_to_node_id"]
      }
    },
    "metadata": {
      "type": "object",
      "properties": {
        "created": {
          "type": "string",
          "format": "date-time"
        },
        "version": {
          "type": "string"
        },
        "tags": {
          "type": "array",
          "items": {
            "type": "string"
          }
        }
      }
    }
  },
  "required": ["id", "core_question", "thought_paths"]
}

Теперь создам первый файл данных по этой схеме для AQ-007.