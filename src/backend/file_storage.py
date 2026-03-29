"""
File Storage Module for Mneme (Phase 7)

This module handles file storage operations for attachments:
- File validation (type, size, magic bytes)
- UUID generation for file references
- Directory management
- File saving with proper structure
- Hash calculation for deduplication

STORAGE STRUCTURE:
    data/{profile}/attachments/{uuid}/
    ├── original.{ext}    # Original or auto-resized file
    ├── optimized.{ext}   # Images: 1568px max (for AI context)
    ├── thumbnail.{ext}   # Images: 300px max (for UI)
    └── metadata.json     # File information

DESIGN PRINCIPLES:
- Local-first: All files stored on user's machine
- UUID-based: No user paths to prevent traversal attacks
- Auto-resize: Large images resized instead of rejected
"""

import os
import json
import uuid
import hashlib
import mimetypes
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

# Try to import Pillow for image processing
try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("Warning: Pillow not installed. Image processing disabled.")
    print("Install with: pip install Pillow")


class FileStorageError(Exception):
    """Base exception for file storage errors."""
    pass


class FileValidationError(FileStorageError):
    """Raised when file validation fails."""
    pass


class FileStorage:
    """
    Handles file storage operations for attachments.

    Manages file upload, validation, storage structure, and metadata.
    """

    # Allowed MIME types and their categories
    ALLOWED_TYPES = {
        # Images
        "image/jpeg": "image",
        "image/png": "image",
        "image/gif": "image",
        "image/webp": "image",
        # Text
        "text/plain": "text",
        "text/markdown": "text",
        # Data
        "application/json": "data",
        # Documents
        "application/pdf": "document",
    }

    # File extension mapping
    MIME_TO_EXTENSION = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "application/json": ".json",
        "application/pdf": ".pdf",
    }

    # Magic bytes for file type verification
    MAGIC_BYTES = {
        "image/jpeg": [b'\xff\xd8\xff'],
        "image/png": [b'\x89PNG\r\n\x1a\n'],
        "image/gif": [b'GIF87a', b'GIF89a'],
        "image/webp": [b'RIFF'],  # Followed by size then WEBP
        "application/pdf": [b'%PDF'],
    }

    # Size limits (in bytes)
    MAX_IMAGE_SIZE = 50 * 1024 * 1024  # 50MB hard limit for images (will be resized)
    MAX_TEXT_SIZE = 50 * 1024 * 1024   # 50MB for text files
    MAX_PDF_SIZE = 50 * 1024 * 1024    # 50MB for PDFs

    # Image resize thresholds
    IMAGE_RESIZE_THRESHOLD_SIZE = 10 * 1024 * 1024  # 10MB triggers resize
    IMAGE_RESIZE_THRESHOLD_DIMENSION = 8000  # 8000px triggers resize
    IMAGE_OPTIMIZED_MAX = 1568  # Max dimension for AI context
    IMAGE_THUMBNAIL_MAX = 300   # Max dimension for UI thumbnails
    IMAGE_QUALITY = 85  # JPEG quality for resized images

    def __init__(self, attachments_dir: str):
        """
        Initialize file storage.

        Args:
            attachments_dir: Path to attachments directory
                           (e.g., "data/main/attachments")
        """
        self.attachments_dir = Path(attachments_dir)
        self._ensure_directory()

    def _ensure_directory(self):
        """Create attachments directory if it doesn't exist."""
        self.attachments_dir.mkdir(parents=True, exist_ok=True)

    def generate_uuid(self) -> str:
        """Generate a unique identifier for a file."""
        return str(uuid.uuid4())

    def validate_file(self, file_data: bytes, filename: str,
                      mime_type: Optional[str] = None) -> Tuple[str, str]:
        """
        Validate file type and size.

        Args:
            file_data: File content as bytes
            filename: Original filename
            mime_type: MIME type (optional, will be guessed if not provided)

        Returns:
            Tuple of (validated_mime_type, file_category)

        Raises:
            FileValidationError: If file is invalid
        """
        # Determine MIME type
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(filename)

        if not mime_type:
            raise FileValidationError(
                f"Could not determine file type for: {filename}"
            )

        # Check if type is allowed
        if mime_type not in self.ALLOWED_TYPES:
            allowed = ", ".join(sorted(set(self.ALLOWED_TYPES.values())))
            raise FileValidationError(
                f"File type '{mime_type}' not allowed. "
                f"Allowed types: {allowed}"
            )

        category = self.ALLOWED_TYPES[mime_type]

        # Verify magic bytes for binary files
        if mime_type in self.MAGIC_BYTES:
            if not self._verify_magic_bytes(file_data, mime_type):
                raise FileValidationError(
                    f"File content doesn't match declared type: {mime_type}"
                )

        # Check size limits
        size = len(file_data)
        if category == "image" and size > self.MAX_IMAGE_SIZE:
            raise FileValidationError(
                f"Image exceeds maximum size of {self.MAX_IMAGE_SIZE // (1024*1024)}MB"
            )
        elif category == "text" and size > self.MAX_TEXT_SIZE:
            raise FileValidationError(
                f"Text file exceeds maximum size of {self.MAX_TEXT_SIZE // (1024*1024)}MB"
            )
        elif category == "data" and size > self.MAX_TEXT_SIZE:
            raise FileValidationError(
                f"JSON file exceeds maximum size of {self.MAX_TEXT_SIZE // (1024*1024)}MB"
            )
        elif category == "document" and size > self.MAX_PDF_SIZE:
            raise FileValidationError(
                f"PDF exceeds maximum size of {self.MAX_PDF_SIZE // (1024*1024)}MB"
            )

        # Check for empty files
        if size == 0:
            raise FileValidationError("Empty files are not allowed")

        return mime_type, category

    def _verify_magic_bytes(self, file_data: bytes, mime_type: str) -> bool:
        """
        Verify file content matches declared MIME type using magic bytes.

        Args:
            file_data: File content
            mime_type: Declared MIME type

        Returns:
            True if magic bytes match
        """
        if mime_type not in self.MAGIC_BYTES:
            return True  # No magic bytes to check

        expected_bytes = self.MAGIC_BYTES[mime_type]
        for magic in expected_bytes:
            if file_data[:len(magic)] == magic:
                return True

        return False

    def calculate_hash(self, file_data: bytes) -> str:
        """
        Calculate SHA-256 hash of file data.

        Args:
            file_data: File content

        Returns:
            Hex digest of hash
        """
        return hashlib.sha256(file_data).hexdigest()

    def store_file(self, file_data: bytes, filename: str,
                   mime_type: Optional[str] = None,
                   file_uuid: Optional[str] = None) -> Dict:
        """
        Store a file with proper directory structure.

        For images, this will:
        - Auto-resize if over size/dimension thresholds
        - Create optimized version (1568px max)
        - Create thumbnail (300px max)

        Args:
            file_data: File content as bytes
            filename: Original filename
            mime_type: MIME type (optional)
            file_uuid: UUID to use (optional, generates new if not provided)

        Returns:
            Dict with storage info:
            {
                "uuid": "...",
                "filename": "original.jpg",
                "mime_type": "image/jpeg",
                "category": "image",
                "size_bytes": 12345,
                "file_hash": "abc123...",
                "storage_path": "a1b2c3d4-...",
                "was_resized": False,
                "original_size": 12345,
                "metadata": {...}
            }
        """
        # Validate file
        mime_type, category = self.validate_file(file_data, filename, mime_type)

        # Generate UUID if not provided
        if not file_uuid:
            file_uuid = self.generate_uuid()

        # Create storage directory
        file_dir = self.attachments_dir / file_uuid
        file_dir.mkdir(parents=True, exist_ok=True)

        # Get extension
        ext = self.MIME_TO_EXTENSION.get(mime_type, Path(filename).suffix)

        # Calculate hash before any processing
        file_hash = self.calculate_hash(file_data)
        original_size = len(file_data)

        # Store based on category
        if category == "image":
            result = self._store_image(file_data, file_dir, ext, mime_type)
        else:
            result = self._store_other(file_data, file_dir, ext)

        # Build metadata
        metadata = {
            "original_filename": filename,
            "original_size": original_size,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata.update(result.get("metadata", {}))

        # Save metadata.json
        metadata_path = file_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return {
            "uuid": file_uuid,
            "filename": filename,
            "mime_type": mime_type,
            "category": category,
            "size_bytes": result["size_bytes"],
            "file_hash": file_hash,
            "storage_path": file_uuid,
            "was_resized": result.get("was_resized", False),
            "original_size": original_size,
            "metadata": metadata,
        }

    def _store_image(self, file_data: bytes, file_dir: Path,
                     ext: str, mime_type: str) -> Dict:
        """
        Store image with processing (resize, thumbnail, optimized).

        Args:
            file_data: Image bytes
            file_dir: Directory to store in
            ext: File extension
            mime_type: MIME type

        Returns:
            Dict with processing results
        """
        if not PILLOW_AVAILABLE:
            # Fallback: just store original
            original_path = file_dir / f"original{ext}"
            with open(original_path, "wb") as f:
                f.write(file_data)
            return {
                "size_bytes": len(file_data),
                "was_resized": False,
                "metadata": {"pillow_available": False}
            }

        from io import BytesIO

        # Open image
        img = Image.open(BytesIO(file_data))
        original_width, original_height = img.size
        original_format = img.format or "JPEG"

        # Check if resize needed
        needs_resize = (
            len(file_data) > self.IMAGE_RESIZE_THRESHOLD_SIZE or
            original_width > self.IMAGE_RESIZE_THRESHOLD_DIMENSION or
            original_height > self.IMAGE_RESIZE_THRESHOLD_DIMENSION
        )

        was_resized = False

        # Handle RGBA for JPEG
        if img.mode == 'RGBA' and mime_type == 'image/jpeg':
            # Convert RGBA to RGB for JPEG
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode not in ('RGB', 'L', 'RGBA'):
            img = img.convert('RGB')

        # Resize if needed (this becomes the "original")
        if needs_resize:
            max_dim = max(original_width, original_height)
            if max_dim > self.IMAGE_RESIZE_THRESHOLD_DIMENSION:
                # Resize to threshold
                ratio = self.IMAGE_RESIZE_THRESHOLD_DIMENSION / max_dim
                new_size = (
                    int(original_width * ratio),
                    int(original_height * ratio)
                )
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                was_resized = True

        # Save "original" (possibly resized)
        original_path = file_dir / f"original{ext}"
        save_format = original_format if original_format in ('JPEG', 'PNG', 'GIF', 'WEBP') else 'JPEG'

        if save_format == 'JPEG':
            img.save(original_path, format=save_format, quality=self.IMAGE_QUALITY)
        else:
            img.save(original_path, format=save_format)

        stored_size = original_path.stat().st_size
        stored_width, stored_height = img.size

        # Create optimized version (for AI context)
        optimized_path = file_dir / f"optimized{ext}"
        self._create_resized_image(img, optimized_path, self.IMAGE_OPTIMIZED_MAX, save_format)

        # Create thumbnail (for UI)
        thumbnail_path = file_dir / f"thumbnail{ext}"
        self._create_resized_image(img, thumbnail_path, self.IMAGE_THUMBNAIL_MAX, save_format)

        return {
            "size_bytes": stored_size,
            "was_resized": was_resized,
            "metadata": {
                "width": stored_width,
                "height": stored_height,
                "original_width": original_width,
                "original_height": original_height,
                "format": save_format,
            }
        }

    def _create_resized_image(self, img: Image.Image, path: Path,
                              max_dimension: int, save_format: str):
        """
        Create a resized version of an image.

        Args:
            img: PIL Image object
            path: Path to save to
            max_dimension: Maximum width/height
            save_format: Image format (JPEG, PNG, etc.)
        """
        width, height = img.size

        # Only resize if larger than max
        if width > max_dimension or height > max_dimension:
            ratio = max_dimension / max(width, height)
            new_size = (int(width * ratio), int(height * ratio))
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
        else:
            resized = img

        if save_format == 'JPEG':
            resized.save(path, format=save_format, quality=self.IMAGE_QUALITY)
        else:
            resized.save(path, format=save_format)

    def _store_other(self, file_data: bytes, file_dir: Path, ext: str) -> Dict:
        """
        Store non-image file.

        Args:
            file_data: File bytes
            file_dir: Directory to store in
            ext: File extension

        Returns:
            Dict with storage results
        """
        original_path = file_dir / f"original{ext}"
        with open(original_path, "wb") as f:
            f.write(file_data)

        metadata = {}

        # For JSON, also save pretty-printed version
        if ext == ".json":
            try:
                data = json.loads(file_data.decode("utf-8"))
                pretty_path = file_dir / "pretty.json"
                with open(pretty_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                metadata["is_valid_json"] = True
            except (json.JSONDecodeError, UnicodeDecodeError):
                metadata["is_valid_json"] = False

        # For text files, calculate line/word count
        if ext in (".txt", ".md"):
            try:
                text = file_data.decode("utf-8")
                metadata["line_count"] = text.count("\n") + 1
                metadata["word_count"] = len(text.split())
                metadata["encoding"] = "utf-8"
            except UnicodeDecodeError:
                metadata["encoding"] = "unknown"

        return {
            "size_bytes": len(file_data),
            "metadata": metadata
        }

    def get_file_path(self, file_uuid: str, version: str = "original") -> Optional[Path]:
        """
        Get path to a stored file.

        Args:
            file_uuid: File UUID
            version: Which version ("original", "optimized", "thumbnail")

        Returns:
            Path to file or None if not found
        """
        file_dir = self.attachments_dir / file_uuid

        if not file_dir.exists():
            return None

        # Find file with matching prefix
        for file in file_dir.iterdir():
            if file.stem == version:
                return file

        return None

    def get_metadata(self, file_uuid: str) -> Optional[Dict]:
        """
        Get stored metadata for a file.

        Args:
            file_uuid: File UUID

        Returns:
            Metadata dict or None if not found
        """
        metadata_path = self.attachments_dir / file_uuid / "metadata.json"

        if not metadata_path.exists():
            return None

        with open(metadata_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def update_metadata(self, file_uuid: str, updates: Dict) -> bool:
        """
        Merge new fields into an existing metadata.json.

        Args:
            file_uuid: File UUID
            updates: Dict of fields to add/overwrite

        Returns:
            True if updated, False if metadata file not found
        """
        metadata_path = self.attachments_dir / file_uuid / "metadata.json"
        if not metadata_path.exists():
            return False

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        metadata.update(updates)

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return True

    def delete_file(self, file_uuid: str) -> bool:
        """
        Delete a stored file and all its versions.

        Args:
            file_uuid: File UUID

        Returns:
            True if deleted, False if not found
        """
        file_dir = self.attachments_dir / file_uuid

        if not file_dir.exists():
            return False

        # Remove all files in directory
        for file in file_dir.iterdir():
            file.unlink()

        # Remove directory
        file_dir.rmdir()

        return True

    def get_storage_stats(self) -> Dict:
        """
        Get statistics about stored files.

        Returns:
            Dict with storage statistics
        """
        total_size = 0
        file_count = 0

        for file_dir in self.attachments_dir.iterdir():
            if file_dir.is_dir():
                file_count += 1
                for file in file_dir.iterdir():
                    if file.is_file():
                        total_size += file.stat().st_size

        return {
            "total_files": file_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "attachments_dir": str(self.attachments_dir),
        }
