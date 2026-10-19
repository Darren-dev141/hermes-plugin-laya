"""Tool schemas — what the LLM sees. These mirror the Laya server contract
(~/workspace/laya/client.py): choice sets are capped at 10 options because
confidence is uncalibrated beyond that, confidence is a ranking signal and
never a gate, and every result carries the decision_id under which Laya
logged the call.
"""

_OPTIONS_PROP = {
    "oneOf": [
        {
            "type": "object",
            "description": "Map of option name -> definition/description. "
            "Definitions matter: Laya judges the definitions you give, "
            "so write each one as the thing itself, not a label for it.",
            "additionalProperties": {"type": "string"},
        },
        {
            "type": "array",
            "description": "Bare option names (each name is its own definition).",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 10,
        },
    ],
    "description": "1 to 10 options. More than 10 is rejected before any call is made.",
}

_STATE_PROP = {
    "type": "string",
    "description": "The situation to judge: the facts, the question context, "
    "everything the decision turns on, as one text block.",
}

HEALTH = {
    "name": "laya_health",
    "description": (
        "Check whether the local Laya decision server is up and warm. "
        "Call this before a batch of laya_* decisions if Laya may have been "
        "restarted; a down Laya makes every other laya_* tool return an error."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CHOOSE = {
    "name": "laya_choose",
    "description": (
        "Ask Laya to pick the single best option for a situation. Use for "
        "fast either/or and small-set judgment calls (which source to trust, "
        "which lead to work first, which approach fits). Returns the choice, "
        "a confidence, per-option probabilities, and the decision_id. "
        "Confidence ranks options; it is not a probability the pick is right "
        "and never a gate by itself. At most 10 options."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": _STATE_PROP,
            "options": _OPTIONS_PROP,
            "instructions": {
                "type": "string",
                "description": "What 'best' means here, e.g. 'Which option best "
                "fits this state?' (the default).",
            },
        },
        "required": ["state", "options"],
    },
}

YES_NO = {
    "name": "laya_yes_no",
    "description": (
        "Ask Laya one yes/no question about a situation. Returns p_yes "
        "(probability of yes; 0.5 is the yes/no threshold), a confidence, and "
        "the decision_id. Use for quick classification: is this urgent, is "
        "this a fit, does this need a human."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": _STATE_PROP,
            "question": {
                "type": "string",
                "description": "The yes/no question, phrased so 'yes' is the "
                "affirmative, checkable answer.",
            },
        },
        "required": ["state", "question"],
    },
}

RANK = {
    "name": "laya_rank",
    "description": (
        "Ask Laya to rank a list of candidate strings best-first for a "
        "situation (search queries, leads, drafts, next actions). Returns "
        "the best item, the full ranking with probabilities, a confidence, "
        "and the decision_id. At most 10 candidates."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": _STATE_PROP,
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 10,
                "description": "The candidate strings to rank, 1 to 10.",
            },
            "instructions": {
                "type": "string",
                "description": "What 'best' means here, e.g. 'Which option is "
                "best?' (the default).",
            },
        },
        "required": ["state", "options"],
    },
}

JUDGE = {
    "name": "laya_judge",
    "description": (
        "Ask Laya for a typed judgment: one choice PLUS typed auxiliary "
        "fields, all answered in a single pass. Fields are yes_no (returns "
        "P(yes) in [0,1]) or score (REQUIRES 'levels': 2+ ordered labels; "
        "the returned value is the expected level INDEX as a float, not the "
        "label). Use when a decision needs a pick and calibrated side "
        "judgments together (pick a lead AND score urgency AND flag risk). "
        "Pass escalate_below (0..1) to have a low-confidence pick marked "
        "status='escalated': an escalated pick must not be acted on "
        "automatically — the caller decides explicitly. Returns choice, "
        "confidence, probabilities, fields, and the decision_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": _STATE_PROP,
            "options": _OPTIONS_PROP,
            "instructions": {
                "type": "string",
                "description": "What 'best' means for the choice, e.g. 'Which "
                "option best fits this state?' (the default).",
            },
            "schema": {
                "type": "object",
                "description": "The typed schema: {name, version?, fields}. "
                "Give the schema a stable name (and bump version when the "
                "fields change) so decision logs stay comparable.",
                "properties": {
                    "name": {"type": "string"},
                    "version": {"type": "integer"},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string", "enum": ["yes_no", "score"]},
                                "question": {
                                    "type": "string",
                                    "description": "Required for yes_no; "
                                    "optional label question for score.",
                                },
                                "levels": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 2,
                                    "description": "score only, REQUIRED: 2+ "
                                    "ordered labels, worst/lowest first. The "
                                    "value returned is the expected index "
                                    "into this list.",
                                },
                            },
                            "required": ["name", "type"],
                        },
                    },
                },
                "required": ["name"],
            },
            "escalate_below": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Optional. If the choice confidence falls below "
                "this, the result is marked status='escalated' with a note "
                "instead of being presented as a settled pick.",
            },
        },
        "required": ["state", "options", "schema"],
    },
}
