import re
import os
import cv2
import numpy as np
import pytesseract
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pdf2image import convert_from_bytes
from deep_translator import GoogleTranslator

# Windows local dev paths (ignored on Linux/Render)
if os.name == "nt":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    POPPLER_PATH = r"C:\Users\USER\Downloads\poppler-25.12.0\Library\bin"
else:
    POPPLER_PATH = None  # Linux: poppler installed system-wide via apt

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── image preprocessing (same as notebook) ──────────────────────────────────
def preprocess_page(pil_img):
    img = np.array(pil_img)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return thresh

# ── OCR (Marathi + English) ──────────────────────────────────────────────────
def bilingual_ocr(img):
    return pytesseract.image_to_string(
        img, lang="mar+eng", config="--psm 6 --oem 3"
    ).strip()

# ── protect URLs / emails / dates before translation ────────────────────────
def create_protected_map(text):
    protected_map = {}
    patterns = [
        r'https?://[^\s]+|www\.[^\s]+',
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
        r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b',
    ]
    all_matches = []
    for p in patterns:
        all_matches.extend(re.findall(p, text))

    protected_text = text
    for idx, item in enumerate(all_matches):
        placeholder = f"__PROTECTED_{idx}__"
        protected_map[placeholder] = item
        protected_text = protected_text.replace(item, placeholder, 1)
    return protected_text, protected_map

def restore_protected(text, protected_map):
    for placeholder, original in protected_map.items():
        text = text.replace(placeholder, original)
    return text

# ── Marathi detection ────────────────────────────────────────────────────────
def contains_marathi(text):
    return any('\u0900' <= ch <= '\u097F' for ch in text)

# ── translation ──────────────────────────────────────────────────────────────
def translate_line(line: str) -> str:
    try:
        return GoogleTranslator(source="mr", target="en").translate(line)
    except Exception:
        return line  # fallback: return original

def safe_document_translation(text: str) -> str:
    protected_text, protected_map = create_protected_map(text)
    translated_lines = []
    for line in protected_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            translated_lines.append("")
        elif contains_marathi(stripped):
            translated_lines.append(translate_line(stripped))
        else:
            translated_lines.append(stripped)
    return restore_protected("\n".join(translated_lines), protected_map)

# ── API endpoint ─────────────────────────────────────────────────────────────
@app.post("/translate")
async def translate_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    pdf_bytes = await file.read()

    try:
        kwargs = {"dpi": 300}
        if POPPLER_PATH:
            kwargs["poppler_path"] = POPPLER_PATH
        pages = convert_from_bytes(pdf_bytes, **kwargs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF conversion failed: {e}")

    # OCR all pages
    raw_text = ""
    for i, page in enumerate(pages):
        processed = preprocess_page(page)
        raw_text += f"\n--- Page {i+1} ---\n"
        raw_text += bilingual_ocr(processed) + "\n"

    # Translate
    translated = safe_document_translation(raw_text)

    return JSONResponse({
        "pages": len(pages),
        "original": raw_text.strip(),
        "translated": translated.strip(),
    })

@app.get("/health")
def health():
    return {"status": "ok"}
