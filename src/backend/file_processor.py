"""
File Processor Module for Mneme (Phase 7)

This module handles file processing operations:
- Loading files for AI context (base64, text content)
- Text content extraction and preview generation
- PDF processing (text extraction, page rendering)
- JSON schema inference
- Content formatting for Anthropic API

CONTEXT FORMATS:
    Images:  {"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}
    Text:    {"type": "text", "text": "...content..."}

DESIGN PRINCIPLES:
- Efficient loading: Only load what's needed for context
- Graceful degradation: Handle missing dependencies
- Preview generation: Smart truncation for large files
"""

import os
import json
import base64
from pathlib import Path
from typing import Optional, Dict, List, Any, Union

# Try to import optional dependencies
try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False


class FileProcessorError(Exception):
    """Base exception for file processor errors."""
    pass


class FileProcessor:
    """
    Handles file processing for AI context.

    Loads and formats files for inclusion in Anthropic API messages.
    """

    # Content preview limits
    PREVIEW_MAX_CHARS = 2000
    CONTEXT_MAX_CHARS = 50000  # Max chars for full text in context

    # PDF settings
    PDF_MAX_PAGES = 20
    PDF_RENDER_DPI = 150

    def __init__(self, attachments_dir: str):
        """
        Initialize file processor.

        Args:
            attachments_dir: Path to attachments directory
        """
        self.attachments_dir = Path(attachments_dir)

    def load_for_context(self, attachment: Dict,
                         version: str = "optimized") -> Dict:
        """
        Load a file formatted for AI context.

        Args:
            attachment: Attachment record from database
            version: Which version to load ("optimized", "original", "thumbnail")

        Returns:
            Content block for Anthropic API message
            Images: {"type": "image", "source": {...}}
            Text/JSON: {"type": "text", "text": "..."}
        """
        mime_type = attachment["mime_type"]
        file_uuid = attachment["uuid"]
        category = self._get_category(mime_type)

        if category == "image":
            return self._load_image_for_context(file_uuid, mime_type, version)
        elif category == "document":
            return self._load_pdf_for_context(file_uuid)
        else:
            return self._load_text_for_context(file_uuid, mime_type)

    def _get_category(self, mime_type: str) -> str:
        """Get category from MIME type."""
        if mime_type.startswith("image/"):
            return "image"
        elif mime_type == "application/pdf":
            return "document"
        elif mime_type == "application/json":
            return "data"
        else:
            return "text"

    def _load_image_for_context(self, file_uuid: str, mime_type: str,
                                version: str = "optimized") -> Dict:
        """
        Load image as base64 for AI context.

        Args:
            file_uuid: File UUID
            mime_type: Image MIME type
            version: Which version to load

        Returns:
            Image content block for API
        """
        file_dir = self.attachments_dir / file_uuid

        # Find the requested version
        for file in file_dir.iterdir():
            if file.stem == version:
                with open(file, "rb") as f:
                    image_data = f.read()

                base64_data = base64.b64encode(image_data).decode("utf-8")

                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64_data
                    }
                }

        # Fallback to original if version not found (guard against infinite recursion)
        if version != "original":
            return self._load_image_for_context(file_uuid, mime_type, "original")
        return None

    def _load_text_for_context(self, file_uuid: str, mime_type: str,
                               max_chars: Optional[int] = None) -> Dict:
        """
        Load text file for AI context.

        Args:
            file_uuid: File UUID
            mime_type: Text MIME type
            max_chars: Maximum characters to include

        Returns:
            Text content block for API
        """
        file_dir = self.attachments_dir / file_uuid
        max_chars = max_chars or self.CONTEXT_MAX_CHARS

        # Find original file
        original_path = None
        for file in file_dir.iterdir():
            if file.stem == "original":
                original_path = file
                break

        if not original_path:
            return {
                "type": "text",
                "text": "[File content not found]"
            }

        # Read content
        try:
            with open(original_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try with different encoding
            with open(original_path, "r", encoding="latin-1") as f:
                content = f.read()

        # Format based on type
        if mime_type == "application/json":
            # Pretty format JSON
            try:
                data = json.loads(content)
                content = json.dumps(data, indent=2)
            except json.JSONDecodeError:
                pass  # Keep original content

        # Truncate if needed
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Content truncated at {max_chars:,} characters]"

        return {
            "type": "text",
            "text": content
        }

    def _load_pdf_for_context(self, file_uuid: str) -> Dict:
        """
        Load PDF content for AI context.

        Extracts text from PDF. If text extraction fails or PDF is
        image-based, falls back to rendered page images.

        Args:
            file_uuid: File UUID

        Returns:
            Text or image content block for API
        """
        file_dir = self.attachments_dir / file_uuid

        # Find original PDF
        original_path = None
        for file in file_dir.iterdir():
            if file.stem == "original" and file.suffix == ".pdf":
                original_path = file
                break

        if not original_path:
            return {
                "type": "text",
                "text": "[PDF file not found]"
            }

        # Try text extraction first
        if PDFPLUMBER_AVAILABLE:
            try:
                text = self._extract_pdf_text(original_path)
                if text and len(text.strip()) > 100:
                    # Good text content
                    if len(text) > self.CONTEXT_MAX_CHARS:
                        text = text[:self.CONTEXT_MAX_CHARS] + \
                               f"\n\n[Content truncated at {self.CONTEXT_MAX_CHARS:,} characters]"
                    return {
                        "type": "text",
                        "text": text
                    }
            except Exception as e:
                pass  # Fall through to page rendering

        # Fallback: check for rendered pages
        pages_dir = file_dir / "pages"
        if pages_dir.exists():
            return self._load_pdf_pages_for_context(pages_dir)

        return {
            "type": "text",
            "text": "[PDF content could not be extracted. Install pdfplumber: pip install pdfplumber]"
        }

    def _extract_pdf_text(self, pdf_path: Path) -> str:
        """
        Extract text from PDF using pdfplumber.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted text
        """
        if not PDFPLUMBER_AVAILABLE:
            return ""

        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages[:self.PDF_MAX_PAGES]):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

            if len(pdf.pages) > self.PDF_MAX_PAGES:
                text_parts.append(
                    f"\n[Showing first {self.PDF_MAX_PAGES} of {len(pdf.pages)} pages]"
                )

        return "\n\n".join(text_parts)

    def _load_pdf_pages_for_context(self, pages_dir: Path) -> List[Dict]:
        """
        Load rendered PDF pages as images for context.

        Args:
            pages_dir: Directory containing page images

        Returns:
            List of image content blocks
        """
        pages = []
        for page_file in sorted(pages_dir.iterdir()):
            if page_file.suffix.lower() in (".jpg", ".jpeg", ".png"):
                with open(page_file, "rb") as f:
                    image_data = f.read()

                base64_data = base64.b64encode(image_data).decode("utf-8")
                mime_type = "image/jpeg" if page_file.suffix.lower() in (".jpg", ".jpeg") else "image/png"

                pages.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64_data
                    }
                })

                if len(pages) >= self.PDF_MAX_PAGES:
                    break

        if not pages:
            return [{"type": "text", "text": "[No PDF page images found]"}]

        return pages  # Return list of image blocks

    def generate_preview(self, file_uuid: str, mime_type: str) -> str:
        """
        Generate content preview for database storage.

        Args:
            file_uuid: File UUID
            mime_type: File MIME type

        Returns:
            Preview text (first ~2000 chars)
        """
        category = self._get_category(mime_type)

        if category == "image":
            # No text preview for images
            return ""

        file_dir = self.attachments_dir / file_uuid

        # Find original file
        original_path = None
        for file in file_dir.iterdir():
            if file.stem == "original":
                original_path = file
                break

        if not original_path:
            return ""

        if category == "document":
            # PDF: extract text preview
            if PDFPLUMBER_AVAILABLE:
                try:
                    text = self._extract_pdf_text(original_path)
                    return text[:self.PREVIEW_MAX_CHARS]
                except Exception:
                    return ""
            return ""

        # Text/JSON: read content
        try:
            with open(original_path, "r", encoding="utf-8") as f:
                content = f.read(self.PREVIEW_MAX_CHARS + 100)
        except UnicodeDecodeError:
            try:
                with open(original_path, "r", encoding="latin-1") as f:
                    content = f.read(self.PREVIEW_MAX_CHARS + 100)
            except Exception:
                return ""

        return content[:self.PREVIEW_MAX_CHARS]

    def infer_json_schema(self, file_uuid: str) -> Optional[Dict]:
        """
        Infer schema from JSON file.

        Args:
            file_uuid: File UUID

        Returns:
            Inferred schema or None
        """
        file_dir = self.attachments_dir / file_uuid
        original_path = file_dir / "original.json"

        if not original_path.exists():
            return None

        try:
            with open(original_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

        return self._infer_schema(data)

    def _infer_schema(self, data: Any, depth: int = 0, max_depth: int = 3) -> Dict:
        """
        Recursively infer schema from JSON data.

        Args:
            data: JSON data
            depth: Current recursion depth
            max_depth: Maximum recursion depth

        Returns:
            Schema description
        """
        if depth >= max_depth:
            return {"type": "..."}

        if isinstance(data, dict):
            return {
                "type": "object",
                "keys": list(data.keys())[:10],  # First 10 keys
                "key_count": len(data),
                "sample_values": {
                    k: self._infer_schema(v, depth + 1, max_depth)
                    for k, v in list(data.items())[:5]  # First 5 values
                }
            }
        elif isinstance(data, list):
            return {
                "type": "array",
                "length": len(data),
                "item_type": self._infer_schema(data[0], depth + 1, max_depth) if data else None
            }
        elif isinstance(data, bool):
            return {"type": "boolean"}
        elif isinstance(data, int):
            return {"type": "integer"}
        elif isinstance(data, float):
            return {"type": "number"}
        elif isinstance(data, str):
            return {
                "type": "string",
                "length": len(data),
                "sample": data[:50] if len(data) > 50 else data
            }
        elif data is None:
            return {"type": "null"}
        else:
            return {"type": str(type(data).__name__)}

    def render_pdf_pages(self, file_uuid: str) -> int:
        """
        Render PDF pages as images for visual PDFs.

        Args:
            file_uuid: File UUID

        Returns:
            Number of pages rendered
        """
        if not PILLOW_AVAILABLE:
            return 0

        try:
            from pdf2image import convert_from_path
        except ImportError:
            return 0

        file_dir = self.attachments_dir / file_uuid
        original_path = file_dir / "original.pdf"

        if not original_path.exists():
            return 0

        pages_dir = file_dir / "pages"
        pages_dir.mkdir(exist_ok=True)

        try:
            images = convert_from_path(
                original_path,
                dpi=self.PDF_RENDER_DPI,
                first_page=1,
                last_page=self.PDF_MAX_PAGES
            )

            for i, image in enumerate(images):
                page_path = pages_dir / f"page_{i + 1:03d}.jpg"
                image.save(page_path, "JPEG", quality=85)

            return len(images)

        except Exception as e:
            return 0

    def get_file_info(self, file_uuid: str) -> Optional[Dict]:
        """
        Get comprehensive information about a file.

        Args:
            file_uuid: File UUID

        Returns:
            File info dict or None
        """
        file_dir = self.attachments_dir / file_uuid

        if not file_dir.exists():
            return None

        # Load metadata
        metadata_path = file_dir / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        else:
            metadata = {}

        # Get file sizes
        files = {}
        for file in file_dir.iterdir():
            if file.is_file():
                files[file.stem] = {
                    "path": str(file),
                    "size_bytes": file.stat().st_size,
                    "extension": file.suffix
                }

        return {
            "uuid": file_uuid,
            "metadata": metadata,
            "files": files
        }


def format_file_for_message(attachment: Dict, content_block: Union[Dict, List[Dict]]) -> List[Dict]:
    """
    Format file content block(s) with filename label.

    Args:
        attachment: Attachment record
        content_block: Content block(s) from load_for_context

    Returns:
        List of content blocks with label
    """
    filename = attachment.get("filename", "Unknown file")
    blocks = []

    # Add filename label
    blocks.append({
        "type": "text",
        "text": f"📎 File: {filename}"
    })

    # Add content block(s)
    if isinstance(content_block, list):
        blocks.extend(content_block)
    else:
        blocks.append(content_block)

    return blocks
