import os
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.core.database import SessionLocal, engine, Base
from app.models.db_models import ResearchPaper, PaperPage
from app.retrieval.pdf_processor import render_pdf_to_images, get_pdf_page_count
from app.retrieval.colpali_engine import colpali_engine

def create_sample_diabetes_pdf(output_path: str, title: str, content_lines: list):
    """Generates a synthetic clinical research paper PDF for testing Phase 1 setup."""
    from pypdf import PdfWriter
    from PIL import Image, ImageDraw, ImageFont

    # Render simple PDF page image and save to PDF
    width, height = 1200, 1600
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Title & Header
    draw.rectangle([(50, 50), (1150, 150)], fill=(30, 58, 138))
    draw.text((80, 85), title, fill=(255, 255, 255))
    
    # Paper Content
    y_pos = 200
    for line in content_lines:
        draw.text((80, y_pos), line, fill=(15, 23, 42))
        y_pos += 40

    # Draw sample Clinical Data Table box
    draw.rectangle([(80, 600), (1120, 900)], outline=(30, 58, 138), width=3)
    draw.text((100, 620), "[CLINICAL TRIAL RESULT TABLE]", fill=(30, 58, 138))
    draw.text((100, 680), "Parameter              Baseline (N=250)     Week 24 (N=248)    p-value", fill=(15, 23, 42))
    draw.text((100, 730), "HbA1c (%)              8.4 ± 0.6            7.1 ± 0.5          <0.001", fill=(15, 23, 42))
    draw.text((100, 780), "Fasting Glucose mg/dL  168 ± 22             124 ± 18          <0.001", fill=(15, 23, 42))
    draw.text((100, 830), "Body Weight (kg)       88.2 ± 10.4          84.1 ± 9.8         0.002", fill=(15, 23, 42))

    temp_img_path = output_path.replace(".pdf", "_temp.png")
    img.save(temp_img_path, "PNG")

    # Convert PNG to PDF
    pdf_img = Image.open(temp_img_path).convert("RGB")
    pdf_img.save(output_path, "PDF")
    if os.path.exists(temp_img_path):
        os.remove(temp_img_path)

def setup_demo_papers(papers_dir: str):
    """Creates initial sample diabetes research papers if papers directory is empty."""
    os.makedirs(papers_dir, exist_ok=True)
    existing_pdfs = [f for f in os.listdir(papers_dir) if f.endswith(".pdf")]
    
    if existing_pdfs:
        print(f"[Ingest] Found {len(existing_pdfs)} existing PDF research papers in {papers_dir}.")
        return

    print("[Ingest] No PDFs found. Creating sample peer-reviewed diabetes research papers for testing...")
    
    sample_papers = [
        {
            "filename": "sglt2_inhibitors_t2d_study_2023.pdf",
            "title": "Efficacy of SGLT2 Inhibitors vs GLP-1 RAs in Glycemic Control & Renal Outcomes",
            "content": [
                "Journal of Clinical Endocrinology & Metabolism (2023)",
                "Authors: Dr. A. Smith, Dr. M. Johnson, et al.",
                "ABSTRACT:",
                "Sodium-glucose cotransporter-2 (SGLT2) inhibitors and glucagon-like peptide-1 (GLP-1) receptor agonists",
                "have demonstrated significant reductions in cardiovascular and renal complications in Type 2 Diabetes.",
                "This randomized controlled trial evaluates 498 T2D patients over 24 weeks.",
                "RESULTS SUMMARY:",
                "- Mean HbA1c reduction was 1.3% in SGLT2 cohort vs 1.1% in GLP-1 RA cohort.",
                "- SGLT2 inhibitors showed superior reduction in systolic blood pressure (-5.4 mmHg).",
                "- Risk of hypoglycemia was minimal across both intervention groups (<1.2%)."
            ]
        },
        {
            "filename": "nutrition_interventions_hba1c_2024.pdf",
            "title": "Impact of Low-Carbohydrate Dietary Interventions on Glycemic Variability & HbA1c",
            "content": [
                "Diabetes Care & Nutrition Review (2024)",
                "Authors: Dr. R. Patel, Dr. E. Davis",
                "ABSTRACT:",
                "Dietary carbohydrate restriction significantly improves postprandial glucose spikes and insulin sensitivity.",
                "We analyzed continuous glucose monitoring (CGM) metrics across 320 Type 2 Diabetes adults.",
                "RESULTS SUMMARY:",
                "- Patients restricting carbohydrate intake to <50g/day achieved an average HbA1c reduction of 1.4%.",
                "- Time in Range (TIR 70-180 mg/dL) increased from 54% at baseline to 78% at 12 weeks.",
                "- Fasting insulin levels decreased by 28% without requiring increased dosage of basal insulin."
            ]
        }
    ]

    for p in sample_papers:
        pdf_file = os.path.join(papers_dir, p["filename"])
        create_sample_diabetes_pdf(pdf_file, p["title"], p["content"])
        print(f" -> Created sample research paper: {p['filename']}")

def ingest_all_papers():
    """Main ingestion routine: DB registration, rendering, and ColPali indexing."""
    print("=" * 60)
    print("      DIABETES RESEARCH PAPER INGESTION & COLPALI INDEXING     ")
    print("=" * 60)

    # 1. Database Table Initialization
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # 2. Verify / Setup Papers Directory
    papers_dir = os.path.abspath(settings.PAPERS_DIR)
    setup_demo_papers(papers_dir)

    pdf_files = [f for f in os.listdir(papers_dir) if f.endswith(".pdf")]
    print(f"\n[Step 1] Found {len(pdf_files)} research papers in '{papers_dir}'.")

    # 3. Process Each Paper into DB & Render Page Images
    processed_count = 0
    for pdf_name in pdf_files:
        pdf_path = os.path.join(papers_dir, pdf_name)
        
        # Check if already registered
        existing = db.query(ResearchPaper).filter(ResearchPaper.file_path == pdf_path).first()
        if not existing:
            page_count = get_pdf_page_count(pdf_path)
            paper = ResearchPaper(
                title=pdf_name.replace(".pdf", "").replace("_", " ").title(),
                file_path=pdf_path,
                page_count=page_count,
                indexed=True
            )
            db.add(paper)
            db.commit()
            db.refresh(paper)

            # Render PDF pages to PNG images
            img_paths = render_pdf_to_images(pdf_path)
            for page_idx, img_path in enumerate(img_paths):
                page_record = PaperPage(
                    paper_id=paper.id,
                    page_number=page_idx + 1,
                    image_path=img_path,
                    has_tables=True,
                    has_charts=True
                )
                db.add(page_record)
            db.commit()
            processed_count += 1
            print(f" -> Registered & rendered: {pdf_name} ({page_count} pages)")
        else:
            print(f" -> Already registered in DB: {pdf_name}")

    db.close()

    # 4. ColPali Visual Patch Vector Indexing
    print("\n[Step 2] Building ColPali (PaliGemma 2) Late-Interaction Index...")
    colpali_engine.index_documents(papers_dir)

    print("\n" + "=" * 60)
    print(" SUCCESS: Phase 1 Ingestion & ColPali Indexing Completed!")
    print("=" * 60)

if __name__ == "__main__":
    ingest_all_papers()
