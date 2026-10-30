"""Nuwa output contracts, independent of routes and task execution."""

DIMENSIONS = ("writings", "conversations", "expression", "external_views", "decisions", "timeline")
CATEGORIES = (
    "mental_models",
    "decision_heuristics",
    "values",
    "analysis_protocol",
    "expression_style",
    "anti_patterns",
    "contradictions",
    "limits",
)
STR = {"type": "string"}
REF = {"type": "object", "required": ["chapter_id", "quote"], "properties": {"chapter_id": STR, "quote": STR}}
RULE = {
    "type": "object",
    "required": ["name", "category", "behavior", "trigger", "limitations", "attribution", "references"],
    "properties": {
        "name": STR,
        "category": {"enum": list(CATEGORIES)},
        "behavior": STR,
        "trigger": STR,
        "limitations": STR,
        "attribution": {"enum": ["direct", "paraphrase", "third_party", "inference"]},
        "references": {"type": "array", "items": REF},
    },
}
RULES = {
    "type": "object",
    "required": ["rules", "missing_dimensions"],
    "properties": {
        "rules": {"type": "array", "maxItems": 40, "items": RULE},
        "missing_dimensions": {"type": "array", "items": STR},
    },
}
OBSERVATIONS = {
    "type": "object",
    "required": ["observations"],
    "properties": {
        "observations": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "required": ["dimension", "content", "references"],
                "properties": {
                    "dimension": {"enum": list(DIMENSIONS)},
                    "content": STR,
                    "references": {"type": "array", "items": REF},
                },
            },
        }
    },
}
ASSESS = {
    "type": "object",
    "required": ["assessments"],
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["rule_id", "supported", "cross_context", "generative", "distinctive", "reason"],
                "properties": {
                    "rule_id": STR,
                    "supported": {"type": "boolean"},
                    "cross_context": {"type": "boolean"},
                    "generative": {"type": "boolean"},
                    "distinctive": {"type": "boolean"},
                    "reason": STR,
                },
            },
        }
    },
}
TESTS = {
    "type": "object",
    "required": ["tests"],
    "properties": {
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["question", "answer", "passed", "reason"],
                "properties": {"question": STR, "answer": STR, "passed": {"type": "boolean"}, "reason": STR},
            },
        }
    },
}
