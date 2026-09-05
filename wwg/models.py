from typing import Any

SCHEMA_VERSION_INPUT = "wwg.input.v1"
SCHEMA_VERSION_NORMALIZED = "wwg.normalized.v1"
SCHEMA_VERSION_LOCKED = "wwg.locked.v1"
CONVENTION_ID = "WWG_JING_FANG_EIGHT_PALACES_V1"

INPUT_SHEETS = (
    "CASE",
    "SOURCES",
    "CAST",
    "HEXAGRAMS",
    "LINES",
)

EXCLUDED_SHEETS = (
    "HIDDEN",
    "BRANCH_STRENGTH",
)

DOCUMENTATION_SHEETS = (
    "DATA_DICTIONARY",
    "LISTS",
)

BRANCHES = {
    "ZI", "CHOU", "YIN", "MAO", "CHEN", "SI",
    "WU", "WEI", "SHEN", "YOU", "XU", "HAI",
}

STEMS = {
    "JIA", "YI", "BING", "DING", "WU",
    "JI", "GENG", "XIN", "REN", "GUI",
}

PARENTS = {
    "PARENTS", "SIBLINGS", "CHILDREN", "WEALTH", "OFFICER",
}

TRIGRAMS = {
    "QIAN", "DUI", "LI", "ZHEN", "XUN", "KAN", "GEN", "KUN",
}

SELF_OTHER = {"SHI", "YING", "NONE"}
YIN_YANG = {"YIN", "YANG"}
CANONICAL_ELEMENTS = {"WOOD", "FIRE", "EARTH", "METAL", "WATER"}

PROMPT1B_REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "case_id",
    "convention",
    "source_snapshot",
    "calendar",
    "hexagrams",
    "lines",
    "structural_diagnostics",
    "branch_strength",
    "interpretive_roles",
    "audit",
    "lock",
    "case_context",
    "changed_line_structure",
}

ANALYSIS_SCHEMA_VERSION = "wwg.analysis.v1"
FINAL_SCHEMA_VERSION = "wwg.final.v1"

SUPPORTED_LOCKED_CONTRACTS = {
    ("wwg.locked.v1", "WWG_JING_FANG_EIGHT_PALACES_V1"),
    ("wwg.locked.v2", "WWG_JING_FANG_EIGHT_PALACES_V2"),
}

def prompt1b_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": sorted(PROMPT1B_REQUIRED_TOP_LEVEL_KEYS),
        "properties": {
            "schema_version": {"type": "string", "const": SCHEMA_VERSION_LOCKED},
            "case_id": {"type": "string"},
            "case_context": {"type": "object"},
            "changed_line_structure": {"type": "array", "minItems": 6, "maxItems": 6},
            "convention": {"type": "object"},
            "source_snapshot": {"type": "object"},
            "calendar": {"type": "object"},
            "hexagrams": {"type": "object"},
            "lines": {"type": "array", "minItems": 6, "maxItems": 6},
            "structural_diagnostics": {"type": "object"},
            "branch_strength": {"type": "array", "minItems": 12, "maxItems": 12},
            "interpretive_roles": {"type": "object"},
            "audit": {"type": "object"},
            "lock": {"type": "object"},
        },
        "additionalProperties": True,
    }

def partial_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "schema_version", "stage_id", "case_id", "locked_input_sha256",
            "dependency_hashes", "status", "evidence", "payload",
            "uncertainties", "reusable_synthesis",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": ANALYSIS_SCHEMA_VERSION},
            "stage_id": {"type": "string"},
            "case_id": {"type": "string"},
            "locked_input_sha256": {"type": "string"},
            "dependency_hashes": {"type": "object"},
            "status": {
                "type": "string",
                "enum": ["COMPLETED", "COMPLETED_WITH_UNCERTAINTY", "INDETERMINABLE", "INPUT_CONTRADICTION"],
            },
            "evidence": {"type": "array"},
            "payload": {"type": "object"},
            "uncertainties": {"type": "array"},
            "reusable_synthesis": {"type": "string"},
        },
        "additionalProperties": True,
    }

def final_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "schema_version", "stage_id", "case_id", "locked_input_sha256",
            "dependency_hashes", "status", "payload",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": FINAL_SCHEMA_VERSION},
            "stage_id": {"type": "string", "const": "P7_FINAL_AUDIT"},
            "case_id": {"type": "string"},
            "locked_input_sha256": {"type": "string"},
            "dependency_hashes": {"type": "object"},
            "status": {
                "type": "string",
                "enum": ["COMPLETED", "COMPLETED_WITH_UNCERTAINTY", "INDETERMINABLE", "INPUT_CONTRADICTION"],
            },
            "payload": {"type": "object"},
        },
        "additionalProperties": True,
    }

def get_stages_config(prompt_2, prompt_3, prompt_4, prompt_5, prompt_6) -> list:
    return [
        {
            "stage_id": "P2_FUNCTIONAL_MAP",
            "filename": "P2_functional_map",
            "prompt": prompt_2,
            "dependencies": [],
        },
        {
            "stage_id": "P3_YONG_STATE",
            "filename": "P3_yong_state",
            "prompt": prompt_3,
            "dependencies": ["P2_FUNCTIONAL_MAP"],
        },
        {
            "stage_id": "P4_DYNAMIC_MAP",
            "filename": "P4_dynamic_map",
            "prompt": prompt_4,
            "dependencies": ["P2_FUNCTIONAL_MAP", "P3_YONG_STATE"],
        },
        {
            "stage_id": "P5_CONTEXTUAL_FACTORS",
            "filename": "P5_contextual_factors",
            "prompt": prompt_5,
            "dependencies": ["P2_FUNCTIONAL_MAP", "P3_YONG_STATE", "P4_DYNAMIC_MAP"],
        },
        {
            "stage_id": "P6_TIMING",
            "filename": "P6_timing",
            "prompt": prompt_6,
            "dependencies": ["P2_FUNCTIONAL_MAP", "P3_YONG_STATE", "P4_DYNAMIC_MAP", "P5_CONTEXTUAL_FACTORS"],
        },
    ]