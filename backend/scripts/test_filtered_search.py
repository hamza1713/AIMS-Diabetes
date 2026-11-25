import os
import sys
from pathlib import Path

# Force UTF-8 encoding for Windows standard output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.retrieval.text_engine import text_engine
from app.agents.orchestrator import _USER_DEPARTMENT_SCOPES

def test_rbac_filtering():
    print("=" * 80)
    print("            FAISS ROLE-BASED ACCESS CONTROL (RBAC) TEST RUN            ")
    print("=" * 80)

    # 1. Load Text Engine
    if not text_engine._load():
        print("❌ Error: FAISS index could not be loaded. Ingest papers first.")
        return

    print(f"Loaded {len(text_engine._metadata)} pages in local index.")

    # 2. Define test scenarios
    scenarios = [
        {
            "user_id": "clinician_endo",
            "query": "SGLT2 Inhibitors and Cardiovascular/Renal Outcomes in Type 2 Diabetes",
            "search_term": "SGLT2 (Cardiology Paper - Clinician Endo Request)",
            "should_allow_department": "Endocrinology",
            "should_block_department": "Cardiology"
        },
        {
            "user_id": "clinician_cardio",
            "query": "SGLT2 Inhibitors and Cardiovascular/Renal Outcomes in Type 2 Diabetes",
            "search_term": "SGLT2 (Cardiology Paper - Clinician Cardio Request)",
            "should_allow_department": "Cardiology",
            "should_block_department": "Endocrinology"
        },
        {
            "user_id": "researcher_nutrition",
            "query": "Glycemic Impact of Dietary Carbohydrate Restriction in Type 2 Diabetes Remission",
            "search_term": "Carbohydrate Remission (Nutrition Paper - Nutrition Request)",
            "should_allow_department": "Nutrition",
            "should_block_department": "Cardiology"
        },
        {
            "user_id": "clinician_endo",
            "query": "Glycemic Impact of Dietary Carbohydrate Restriction in Type 2 Diabetes Remission",
            "search_term": "Carbohydrate Remission (Nutrition Paper - Clinician Endo Request)",
            "should_allow_department": "Endocrinology",
            "should_block_department": "Nutrition"
        }
    ]

    for idx, sc in enumerate(scenarios, 1):
        user_id = sc["user_id"]
        query = sc["query"]
        allowed_depts = _USER_DEPARTMENT_SCOPES.get(user_id)
        
        print(f"\n[{idx}] Scenario: User '{user_id}' querying '{sc['search_term']}'")
        print(f"    Allowed Departments Scope: {allowed_depts if allowed_depts is not None else 'UNRESTRICTED (All)'}")
        
        # Run search with filters
        results = text_engine.search_enriched(
            queries=[query],
            top_k=5,
            allowed_departments=allowed_depts
        )
        
        print(f"    Retrieved: {len(results)} results")
        
        departments_found = set()
        for r in results:
            title = r.get("title")
            dept = r.get("department", "General")
            page = r.get("page_number")
            departments_found.add(dept)
            print(f"      - [Dept: {dept:<13}] {title[:50]}... (p. {page})")
            
        # Security Boundary Validations
        if allowed_depts is not None:
            # Check that no departments outside allowed_depts are retrieved
            violators = [dept for dept in departments_found if dept not in allowed_depts]
            if violators:
                print(f"    ❌ SECURITY BOUNDARY VIOLATION! Retrieved unauthorized departments: {violators}")
            else:
                print("    ✅ SECURITY BOUNDARY ENFORCED. No unauthorized departments retrieved.")
                
            # Verify specific block department is not in retrieved set
            block_dept = sc["should_block_department"]
            if block_dept and block_dept in departments_found:
                print(f"    ❌ SECURITY BOUNDARY VIOLATION! User retrieved '{block_dept}' document.")
            elif block_dept:
                print(f"    ✅ SECURITY BOUNDARY ENFORCED. Restricted department '{block_dept}' successfully blocked.")
        else:
            print("    ✅ UNRESTRICTED ACCESS. All departments retrieved.")

    print("\n" + "=" * 80)
    print("                      RBAC SECURITY RUN COMPLETED                      ")
    print("=" * 80)

if __name__ == "__main__":
    test_rbac_filtering()
