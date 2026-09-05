import os
import sys
import copy
from pathlib import Path
from typing import Any
import pandas as pd
from openai import OpenAI

from wwg.models import (
    SCHEMA_VERSION_NORMALIZED, SCHEMA_VERSION_LOCKED, CONVENTION_ID,
    INPUT_SHEETS, EXCLUDED_SHEETS, DOCUMENTATION_SHEETS, BRANCHES,
    PARENTS, CANONICAL_ELEMENTS, PROMPT1B_REQUIRED_TOP_LEVEL_KEYS,
    ANALYSIS_SCHEMA_VERSION, FINAL_SCHEMA_VERSION, SUPPORTED_LOCKED_CONTRACTS,
    prompt1b_json_schema, partial_schema, final_schema, get_stages_config
)
from wwg.utils import (
    InputValidationError, OutputValidationError, LockedInputError,
    AnalysisOutputError, normalize_record, dataframe_to_records,
    clean_dataframe, remove_empty_fields, sha256_json, safe_filename,
    read_json, write_json, verify_locked_hash
)

# --- PIPELINE PROMPT 1 ---

def require_columns(sheets: dict[str, pd.DataFrame], sheet_name: str, required_columns: set[str]) -> None:
    existing = {str(col).strip() for col in sheets[sheet_name].columns}
    missing = required_columns - existing
    if missing:
        raise InputValidationError(f"Onglet {sheet_name} : colonnes obligatoires absentes : {sorted(missing)}")

def read_input_workbook(path: Path) -> dict[str, pd.DataFrame]:
    if not path.exists():
        raise InputValidationError(f"Fichier introuvable : {path}")
    workbook = pd.ExcelFile(path, engine="openpyxl")
    available = set(workbook.sheet_names)
    missing_sheets = set(INPUT_SHEETS) - available
    if missing_sheets:
        raise InputValidationError(f"Onglets obligatoires absents : {sorted(missing_sheets)}")
    return {
        sheet_name: pd.read_excel(workbook, sheet_name=sheet_name, dtype=object)
        for sheet_name in INPUT_SHEETS
    }

def validate_input_structure(sheets: dict[str, pd.DataFrame]) -> None:
    require_columns(sheets, "CASE", {"schema_version", "case_id", "language", "question_exact", "reading_perspective", "question_domain", "literal_action", "actual_function_sought", "desired_outcome"})
    require_columns(sheets, "CAST", {"case_id", "cast_datetime_local", "year_stem", "year_branch", "month_stem", "month_branch", "day_stem", "day_branch", "hour_stem", "hour_branch"})
    require_columns(sheets, "HEXAGRAMS", {"case_id", "stage", "hexagram_number_displayed", "hexagram_name_displayed", "upper_trigram_displayed", "lower_trigram_displayed"})
    require_columns(sheets, "LINES", {"case_id", "line_no", "original_yin_yang", "is_moving", "original_branch_displayed", "original_parent_displayed", "self_other_displayed"})

    case_df = clean_dataframe(sheets["CASE"])
    cast_df = clean_dataframe(sheets["CAST"])
    hex_df = clean_dataframe(sheets["HEXAGRAMS"])
    lines_df = clean_dataframe(sheets["LINES"])

    if len(case_df) != 1 or len(cast_df) != 1 or len(lines_df) != 6:
        raise InputValidationError("Erreur de dimension sur les onglets principaux (CASE/CAST/LINES).")

    case_record = normalize_record(case_df.iloc[0].to_dict())
    if case_record.get("schema_version") != SCHEMA_VERSION_INPUT:
        raise InputValidationError(f"schema_version attendu : {SCHEMA_VERSION_INPUT}")

def build_prompt1a(workbook_path: Path, sheets: dict[str, pd.DataFrame]) -> dict[str, Any]:
    case = dataframe_to_records(sheets["CASE"])[0]
    cast = dataframe_to_records(sheets["CAST"])[0]
    sources = dataframe_to_records(sheets["SOURCES"])
    hexagrams = sorted(dataframe_to_records(sheets["HEXAGRAMS"]), key=lambda r: 0 if r.get("stage") == "ORIGINAL" else 1)
    lines = sorted(dataframe_to_records(sheets["LINES"]), key=lambda r: int(r["line_no"]))

    normalized = {
        "schema_version": SCHEMA_VERSION_NORMALIZED,
        "normalization_stage": "PROMPT_1A",
        "case_id": case["case_id"],
        "input_file": {"filename": workbook_path.name, "sha256": hashlib.sha256(workbook_path.read_bytes()).hexdigest()},
        "scope": {"sheets_used": list(INPUT_SHEETS), "sheets_explicitly_excluded": list(EXCLUDED_SHEETS), "documentation_sheets_ignored": list(DOCUMENTATION_SHEETS), "line_numbering": "BOTTOM_TO_TOP"},
        "case": case, "sources": sources, "cast": cast, "hexagrams_displayed": hexagrams, "lines_displayed": lines,
        "normalization_audit": {"status": "VALID", "hard_errors": [], "warnings": [], "statement": "Données filtrées conformes."}
    }
    normalized = remove_empty_fields(normalized)
    normalized["normalized_payload_sha256"] = sha256_json(normalized)
    return normalized

def call_prompt1b(normalized: dict[str, Any], model: str, prompt_1b_system: str, prompt_1b_output_req: str) -> dict[str, Any]:
    client = OpenAI()
    user_content = prompt_1b_output_req + "\n\nOBJET PRODUIT PAR PROMPT 1A :\n" + json.dumps(normalized, ensure_ascii=False, indent=2)
    response = client.responses.create(
        model=model,
        input=[{"role": "system", "content": prompt_1b_system}, {"role": "user", "content": user_content}],
        text={"format": {"type": "json_schema", "name": "wwg_prompt1b_locked_sheet", "strict": False, "schema": prompt1b_json_schema()}}
    )
    if not response.output_text:
        raise OutputValidationError("L'API n'a renvoyé aucun contenu.")
    return json.loads(response.output_text)

def validate_prompt1b_output(result: dict[str, Any], normalized: dict[str, Any]) -> tuple[bool, list[str]]:
    errors = []
    if result.get("schema_version") != SCHEMA_VERSION_LOCKED:
        errors.append("schema_version de sortie invalide.")
    return len(errors) == 0, errors

def apply_final_lock(result: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    local_valid, local_errors = validate_prompt1b_output(result, normalized)
    lock = result.setdefault("lock", {})
    audit = result.setdefault("audit", {})
    blocking_issues = audit.setdefault("blocking_issues", [])
    final_locked = local_valid and lock.get("requested_status") == "LOCKABLE" and len(blocking_issues) == 0

    lock["local_validation"] = {"status": "PASSED" if local_valid else "FAILED", "errors": local_errors}
    lock["final_status"] = "LOCKED" if final_locked else "NOT_LOCKED"
    lock["input_payload_sha256"] = normalized.get("normalized_payload_sha256")
    result["locked_payload_sha256"] = sha256_json(result)
    return result

def run_wwg_pipeline(input_file: Path, output_dir: Path, model: str, prompt_1b_system: str, prompt_1b_output_req: str, normalize_only: bool = False) -> int:
    try:
        sheets = read_input_workbook(input_file)
        validate_input_structure(sheets)
        normalized = build_prompt1a(input_file, sheets)
        case_id = safe_filename(str(normalized["case_id"]))
        output_dir.mkdir(parents=True, exist_ok=True)
        
        write_json(output_dir / f"{case_id}.prompt1a.normalized.json", normalized)
        if normalize_only:
            return 0

        raw_result = call_prompt1b(normalized, model, prompt_1b_system, prompt_1b_output_req)
        write_json(output_dir / f"{case_id}.prompt1b.raw.json", raw_result)
        
        locked_result = apply_final_lock(raw_result, normalized)
        locked_path = output_dir / f"{case_id}.locked.json"
        write_json(locked_path, locked_result)
        return 0 if locked_result["lock"]["final_status"] == "LOCKED" else 2
    except Exception as exc:
        print(f"[ERREUR] {exc}", file=sys.stderr)
        return 1


# --- PIPELINE ANALYTIQUE (PROMPTS 2 à 7) ---

def validate_locked_input(locked: dict[str, Any]) -> None:
    schema_version = locked.get("schema_version")
    convention_id = locked.get("convention", {}).get("id")
    if (schema_version, convention_id) not in SUPPORTED_LOCKED_CONTRACTS:
        raise LockedInputError("Contrat verrouillé non reconnu.")
    verify_locked_hash(locked)

def call_openai_json(client: OpenAI, model: str, system_prompt: str, user_payload: dict[str, Any], schema_name: str, schema: dict[str, Any]) -> dict[str, Any]:
    response = client.responses.create(
        model=model,
        input=[{"role": "system", "content": system_prompt}, {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)}],
        text={"format": {"type": "json_schema", "name": schema_name, "strict": False, "schema": schema}}
    )
    if not response.output_text:
        raise AnalysisOutputError(f"Aucune sortie pour {schema_name}.")
    return json.loads(response.output_text)

def validate_partial_result(result: dict[str, Any], stage: dict[str, Any], locked: dict[str, Any], dependency_results: dict[str, dict[str, Any]]) -> None:
    if result["schema_version"] != ANALYSIS_SCHEMA_VERSION or result["stage_id"] != stage["stage_id"]:
        raise AnalysisOutputError(f"{stage['stage_id']} : schémas ou identifiants incorrects.")

def add_artifact_hash(result: dict[str, Any]) -> dict[str, Any]:
    res_copy = copy.deepcopy(result)
    res_copy.pop("artifact_sha256", None)
    res_copy["artifact_sha256"] = sha256_json(res_copy)
    return res_copy

def run_wwg_analysis_pipeline(locked_file: Path, output_dir: Path, model: str, common_rules: str, prompts_dict: dict) -> int:
    try:
        locked = read_json(locked_file)
        validate_locked_input(locked)
        output_dir.mkdir(parents=True, exist_ok=True)
        client = OpenAI()
        case_id = safe_filename(locked["case_id"])
        locked_hash = locked["locked_payload_sha256"]
        results = {}

        stages = get_stages_config(
            prompts_dict["P2"], prompts_dict["P3"], prompts_dict["P4"],
            prompts_dict["P5"], prompts_dict["P6"]
        )

        for stage in stages:
            stage_id = stage["stage_id"]
            dependency_results = {dep: results[dep] for dep in stage["dependencies"]}
            dependency_hashes = {dep: res["artifact_sha256"] for dep, res in dependency_results.items()}

            user_payload = {
                "task": stage["prompt"],
                "required_output_metadata": {
                    "schema_version": ANALYSIS_SCHEMA_VERSION,
                    "stage_id": stage_id,
                    "case_id": locked["case_id"],
                    "locked_input_sha256": locked_hash,
                    "dependency_hashes": dependency_hashes,
                },
                "locked_reading": locked,
                "previous_analyses": dependency_results,
            }

            result = call_openai_json(client, model, common_rules, user_payload, f"wwg_{stage_id.lower()}", partial_schema())
            validate_partial_result(result, stage, locked, results)
            result = add_artifact_hash(result)
            results[stage_id] = result
            write_json(output_dir / f"{case_id}.{stage['filename']}.json", result)

        # Bundle & Prompt 7
        bundle = {"schema_version": "wwg.analysis_bundle.v1", "case_id": locked["case_id"], "locked_input_sha256": locked_hash, "analyses": results}
        bundle["bundle_sha256"] = sha256_json(bundle)
        write_json(output_dir / f"{case_id}.analysis_bundle.json", bundle)

        final_dependency_hashes = {s_id: res["artifact_sha256"] for s_id, res in results.items()}
        final_payload = {
            "task": prompts_dict["P7"],
            "required_output_metadata": {
                "schema_version": FINAL_SCHEMA_VERSION,
                "stage_id": "P7_FINAL_AUDIT",
                "case_id": locked["case_id"],
                "locked_input_sha256": locked_hash,
                "dependency_hashes": final_dependency_hashes,
            },
            "locked_reading": locked,
            "partial_analyses": results,
        }

        final_result = call_openai_json(client, model, common_rules, final_payload, "wwg_p7_final_audit", final_schema())
        final_result = add_artifact_hash(final_result)
        write_json(output_dir / f"{case_id}.P7_final.json", final_result)
        (output_dir / f"{case_id}.P7_final.md").write_text(final_result["payload"]["final_markdown"], encoding="utf-8")
        return 0
    except Exception as exc:
        print(f"[ERREUR] {exc}", file=sys.stderr)
        return 1