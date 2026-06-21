"""
Document ingestion for SRS / resume skill extraction (SDS §1.4, §2.1 Product Features).

Uses keyword catalog + lightweight NLP when spaCy is available.
"""
import os
import re
import pdfplumber
from docx import Document
from typing import List, Dict, Any
import io

try:
    import pytesseract
    from PIL import Image
except Exception:  # e.g. Python 3.14+ / broken tesseract shim
    pytesseract = None  # type: ignore[assignment,misc]
    Image = None  # type: ignore[assignment,misc]
from app.config import settings
from app.core.srs_format_validator import validate_srs_document_text

def _load_spacy_nlp():
    """spaCy may be unavailable on very new Python (e.g. 3.14) until upstream fixes land."""
    try:
        import spacy
        try:
            return spacy.load(settings.SPACY_MODEL)
        except Exception:
            return spacy.blank("en")
    except Exception:
        return None

class DocumentParser:
    def __init__(self):
        self.nlp = _load_spacy_nlp()
        self.technical_skills = {
            "frontend": [
                "react",
                "react.js",
                "angular",
                "vue",
                "javascript",
                "typescript",
                "html",
                "css",
                "material-ui",
                "tailwind",
                "bootstrap",
            ],
            "backend": [
                "node.js",
                "python",
                "django",
                "flask",
                "fastapi",
                "java",
                "spring",
                "c#",
                ".net",
                "php",
                "laravel",
            ],
            "database": ["mongodb", "mysql", "postgresql", "sqlite", "redis", "elasticsearch"],
            "devops": ["docker", "kubernetes", "aws", "azure", "gcp", "ci/cd", "jenkins", "git"],
            "ml_ai": [
                "python",
                "tensorflow",
                "pytorch",
                "scikit-learn",
                "pandas",
                "numpy",
                "nlp",
                "computer vision",
                "machine learning",
                "deep learning",
            ],
            "mobile": ["react native", "flutter", "swift", "kotlin", "android", "ios"],
            # SRS / travel & product specs often mention these but old catalog missed them
            "design_ux": [
                "figma",
                "ux design",
                "ui/ux",
                "ui ux",
                "visual design",
                "design system",
                "design systems",
                "wireframe",
                "prototype",
                "responsive design",
                "user interface",
                "user experience",
            ],
            "quality": [
                "manual testing",
                "automated testing",
                "test automation",
                "selenium",
                "pytest",
                "jest",
                "cypress",
                "quality assurance",
                "qa testing",
                "api testing",
            ],
            "security": [
                "authentication",
                "authorization",
                "jwt",
                "oauth",
                "rbac",
                "ssl",
                "tls",
            ],
        }

    @staticmethod
    def _simple_sentences(text: str) -> List[str]:
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return [p.strip() for p in parts if p.strip()] or ([text.strip()] if text.strip() else [])

    async def parse_pdf(self, file_path: str) -> str:
        """Extract text from PDF file"""
        text = ""
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                        
                    # Try to extract text from images using OCR
                    images = page.images
                    for img in images:
                        if "stream" in img and Image is not None and pytesseract is not None:
                            try:
                                img_data = img["stream"].get_data()
                                image = Image.open(io.BytesIO(img_data))
                                ocr_text = pytesseract.image_to_string(image)
                                text += ocr_text + "\n"
                            except Exception:
                                pass
        except Exception as e:
            print(f"Error parsing PDF: {e}")
            
        return text
    
    async def parse_docx(self, file_path: str) -> str:
        """Extract text from DOCX file"""
        text = ""
        try:
            doc = Document(file_path)
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
                
            # Extract text from tables
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        text += cell.text + " "
                    text += "\n"
        except Exception as e:
            print(f"Error parsing DOCX: {e}")
            
        return text
    
    async def parse_txt(self, file_path: str) -> str:
        """Extract text from TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            print(f"Error reading TXT file: {e}")
            return ""
    
    async def extract_requirements(self, text: str) -> Dict[str, Any]:
        """Extract project requirements from text using NLP (or heuristics if spaCy unavailable)."""
        if self.nlp is not None:
            try:
                doc = self.nlp(text)
                # `doc.sents` may not be available if the blank model has no sentencizer.
                sentences = [sent.text for sent in doc.sents]
                if not sentences:
                    sentences = self._simple_sentences(text)
            except Exception:
                sentences = self._simple_sentences(text)
            sentence_count = max(1, len(sentences))
        else:
            sentences = self._simple_sentences(text)
            sentence_count = max(1, len(sentences))

        requirements = {
            "title": "",
            "description": "",
            "detected_skills": [],
            "timeline_indicators": [],
            "complexity_score": 0,
            "team_size_suggestion": 1
        }
        
        # Extract title (first non-empty line or sentence)
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if line and len(line) > 10:
                requirements["title"] = line[:100]
                break
        
        # Extract description (first few sentences)
        if len(sentences) > 3:
            requirements["description"] = " ".join(sentences[:3])
        elif sentences:
            requirements["description"] = sentences[0]
        
        # Extract skills (keyword catalog; case-insensitive substring)
        all_skills: list[str] = []
        tl = text.lower()
        for category, skills in self.technical_skills.items():
            for skill in skills:
                if skill.lower() in tl:
                    all_skills.append(skill)

        requirements["detected_skills"] = list(dict.fromkeys(all_skills))
        
        # Extract timeline indicators
        timeline_keywords = ["deadline", "due", "complete by", "finish by", "timeline", "schedule"]
        for st in sentences:
            if any(keyword in st.lower() for keyword in timeline_keywords):
                requirements["timeline_indicators"].append(st)
        
        # Calculate complexity score
        word_count = len(text.split())
        skill_count = len(requirements["detected_skills"])
        
        requirements["complexity_score"] = min(
            100, 
            (word_count / 1000 * 20) + (skill_count * 10) + (sentence_count / 10 * 5)
        )
        
        # Suggest team size based on complexity
        if requirements["complexity_score"] > 70:
            requirements["team_size_suggestion"] = 3
        elif requirements["complexity_score"] > 40:
            requirements["team_size_suggestion"] = 2
        else:
            requirements["team_size_suggestion"] = 1
        
        return requirements

    async def extract_skills_catalog_only(self, text: str) -> List[str]:
        """Return normalized skill tokens from plain text (SDS §1.4 resume/profile analysis)."""
        data = await self.extract_requirements(text or "")
        return list(data.get("detected_skills") or [])
    
    async def parse_srs_document(
        self, file_path: str, *, require_srs_format: bool = False
    ) -> Dict[str, Any]:
        """Main function to parse any SRS document."""
        file_extension = os.path.splitext(file_path)[1].lower()
        
        if file_extension == '.pdf':
            text = await self.parse_pdf(file_path)
        elif file_extension == '.docx':
            text = await self.parse_docx(file_path)
        elif file_extension == '.doc':
            # Convert .doc to .docx or use antiword if needed
            text = await self.parse_txt(file_path)
        elif file_extension == '.txt':
            text = await self.parse_txt(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_extension}")
        
        if not text.strip():
            raise ValueError("Could not extract text from document")

        if require_srs_format:
            ok, reason = validate_srs_document_text(text)
            if not ok:
                raise ValueError(reason)
        
        requirements = await self.extract_requirements(text)
        
        return {
            "extracted_text": text[:5000],  # Limit text length
            "requirements": requirements,
            "file_metadata": {
                "path": file_path,
                "size": os.path.getsize(file_path),
                "extension": file_extension
            }
        }