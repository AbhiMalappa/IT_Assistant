from typing import List, Dict, Any, Optional
from .supabase_client import supabase


def get_by_ids(ids: List[str]) -> List[Dict]:
    if not ids:
        return []
    response = supabase.table("incidents").select("*").in_("id", ids).execute()
    return response.data


def get_all() -> List[Dict]:
    response = supabase.table("incidents").select("*").execute()
    return response.data


def get_by_number(number: str) -> Optional[Dict]:
    response = supabase.table("incidents").select("*").eq("number", number).limit(1).execute()
    return response.data[0] if response.data else None


def insert(incident: Dict[str, Any]) -> Dict:
    response = supabase.table("incidents").insert(incident).execute()
    return response.data[0]


def update(id: str, fields: Dict[str, Any]) -> Dict:
    response = supabase.table("incidents").update(fields).eq("id", id).execute()
    return response.data[0]
