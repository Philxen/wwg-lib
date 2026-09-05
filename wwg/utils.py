import copy
from datetime import date, datetime
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
import pandas as pd

# Exceptions
class InputValidationError(Exception):
    pass

class OutputValidationError(Exception):
    pass

class LockedInputError(Exception):
    pass

class AnalysisOutputError(Exception):
    pass

# Fonctions utilitaires
def is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip() == "":
        return True
    return False

def normalize_scalar(value: Any) -> Any:
    if is_missing(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return int(value)
        return value
    if hasattr(value, "item"):
        try:
            return normalize_scalar(value.item())
        except (ValueError, TypeError):
            pass
    text = str(value).strip()
    upper = text.upper()
    if upper in {"TRUE", "VRAI", "YES", "OUI"}:
        return True
    if upper in {"FALSE", "FAUX", "NO", "NON"}:
        return False
    return text

def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in record.items():
        key = str(key).strip()
        if not key or key.lower().startswith("unnamed"):
            continue
        result[key] = normalize_scalar(value)
    return result

def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    removable_columns = [
        col for col in df.columns
        if str(col).strip().lower() in {"index", "unnamed: 0"}
    ]
    if removable_columns:
        df = df.drop(columns=removable_columns)
    return df.dropna(how="all")

def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        normalize_record(record)
        for record in clean_dataframe(df).to_dict(orient="records")
    ]

def remove_empty_fields(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {k: remove_empty_fields(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v != {} and v != []}
    if isinstance(value, list):
        return [remove_empty_fields(item) for item in value]
    return value

def canonical_json_bytes(data: Any) -> bytes:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

def sha256_json(data: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()

def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value.strip("._") or "wwg_case"

def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise LockedInputError(f"Fichier introuvable : {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LockedInputError(f"JSON invalide : {exc}") from exc

def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def verify_locked_hash(locked: dict[str, Any]) -> None:
    stored_hash = locked.get("locked_payload_sha256")
    if not stored_hash:
        raise LockedInputError("locked_payload_sha256 est absent.")
    payload = copy.deepcopy(locked)
    payload.pop("locked_payload_sha256", None)
    calculated_hash = sha256_json(payload)
    if calculated_hash != stored_hash:
        raise LockedInputError(
            "L'empreinte du fichier verrouillé est invalide. "
            "Le fichier a peut-être été modifié après verrouillage."
        )