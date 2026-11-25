import httpx
import json
import asyncio
import time
from typing import List, Dict, Any, Optional
from google import genai  # type: ignore
from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

ENTITY_EXTRACTION_PROMPT = """You are a medical entity extraction system. Identify any drug names (e.g. Semaglutide, Empagliflozin, Metformin, Insulin), molecular targets (e.g. SGLT2, GLP-1 receptor, DPP-4), or major clinical conditions/diseases (e.g. Type 2 Diabetes, Diabetic Foot Ulcers, retinopathy) mentioned in the clinical query below.

Query: {query}

Provide your extraction in the following exact JSON format (and nothing else):
{{
  "drugs": ["list", "of", "drugs/compounds/targets"],
  "diseases": ["list", "of", "diseases/conditions"]
}}"""

async def extract_entities_with_llm(query: str) -> Dict[str, List[str]]:
    """Uses Gemini to extract drug and disease entities from the query."""
    if not settings.GEMINI_API_KEY:
        return {"drugs": [], "diseases": []}
        
    try:
        # Run inside run_in_executor since google-genai is blocking
        loop = asyncio.get_event_loop()
        def _call_gemini():
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            resp = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=ENTITY_EXTRACTION_PROMPT.format(query=query),
                config={"response_mime_type": "application/json"}
            )
            return resp.text
            
        text = await loop.run_in_executor(None, _call_gemini)
        if text:
            raw_json = text.strip()
            # Clean markdown JSON block wrappers if any
            if raw_json.startswith("```"):
                raw_json = raw_json.split("```")[1]
                if raw_json.startswith("json"):
                    raw_json = raw_json[4:]
            data = json.loads(raw_json.strip())
            return {
                "drugs": [d.strip() for d in data.get("drugs", []) if d.strip()],
                "diseases": [dis.strip() for dis in data.get("diseases", []) if dis.strip()]
            }
    except Exception as e:
        log.warning("Entity extraction failed: %s", e)
    return {"drugs": [], "diseases": []}

async def fetch_chembl_details(drug_name: str) -> Optional[Dict[str, Any]]:
    """Search ChEMBL API for molecule details."""
    url = "https://www.ebi.ac.uk/chembl/api/data/molecule/search.json"
    params = {"q": drug_name, "limit": 1}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params, timeout=8.0)
            if r.status_code == 200:
                data = r.json()
                molecules = data.get("molecules", [])
                if molecules:
                    mol = molecules[0]
                    props = mol.get("molecule_properties") or {}
                    return {
                        "chembl_id": mol.get("molecule_chembl_id"),
                        "pref_name": mol.get("pref_name") or drug_name,
                        "molecule_type": mol.get("molecule_type"),
                        "max_phase": mol.get("max_phase"),
                        "first_approval": mol.get("first_approval"),
                        "formula": props.get("full_molformula"),
                        "molecular_weight": props.get("full_mwt"),
                    }
    except Exception as e:
        log.warning("ChEMBL fetch failed for %s: %s", drug_name, e)
    return None

async def fetch_clinical_trials(term: str) -> Optional[Dict[str, Any]]:
    """Search ClinicalTrials.gov for matching active studies."""
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = {
        "query.term": term,
        "filter.overallStatus": "RECRUITING",
        "pageSize": 3
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params, timeout=8.0)
            if r.status_code == 200:
                data = r.json()
                studies = data.get("studies", [])
                formatted_studies = []
                for s in studies:
                    proto = s.get("protocolSection", {})
                    ident = proto.get("identificationModule", {})
                    status_mod = proto.get("statusModule", {})
                    design = proto.get("designModule", {})
                    
                    formatted_studies.append({
                        "nct_id": ident.get("nctId"),
                        "title": ident.get("briefTitle"),
                        "status": status_mod.get("overallStatus"),
                        "phase": design.get("phases", ["Unknown"])[0] if design.get("phases") else "Unknown",
                    })
                return {
                    "total_studies_found": len(studies),
                    "top_trials": formatted_studies
                }
    except Exception as e:
        log.warning("ClinicalTrials fetch failed for %s: %s", term, e)
    return None

async def enrich_clinical_query(query: str) -> Dict[str, Any]:
    """Coordinates entity extraction and concurrent API harvesting."""
    entities = await extract_entities_with_llm(query)
    drugs = entities.get("drugs", [])
    diseases = entities.get("diseases", [])
    
    chembl_results = {}
    trial_results = {}
    
    # Fire requests concurrently
    tasks = []
    
    # 1. Fetch ChEMBL for drugs
    for drug in drugs[:2]:  # limit to top 2 to avoid overwhelming
        tasks.append((f"chembl_{drug}", fetch_chembl_details(drug)))
        tasks.append((f"trials_{drug}", fetch_clinical_trials(drug)))
        
    # 2. Fetch trials for diseases
    for disease in diseases[:1]:
        tasks.append((f"trials_{disease}", fetch_clinical_trials(disease)))
        
    if tasks:
        names = [t[0] for t in tasks]
        coroutines = [t[1] for t in tasks]
        results = await asyncio.gather(*coroutines)
        
        for name, res in zip(names, results):
            if res:
                if name.startswith("chembl_"):
                    drug_key = name[7:]
                    chembl_results[drug_key] = res
                elif name.startswith("trials_"):
                    term_key = name[7:]
                    trial_results[term_key] = res
                    
    return {
        "extracted_entities": entities,
        "chembl_data": chembl_results,
        "clinical_trials_data": trial_results
    }
