"""
Artifact Storage Module for Mneme Memory System

Handles filesystem storage for creative and technical artifacts:
- Poetry, stories, technical docs, design work
- Human-readable markdown under data/{profile}/artifacts/
- No database tables — pure filesystem

Directory structure:
    data/{profile}/artifacts/{category}/{slug}/ARTIFACT.md

Created lazily on first save (like attachments/).
"""

from pathlib import Path
from datetime import date as date_type
from typing import List, Optional


class ArtifactStorage:
    """
    Manages artifact files on disk.

    Each artifact lives at:
        {artifacts_dir}/{category}/{slug}/ARTIFACT.md

    Supporting files (characters.md, images, etc.) may coexist in
    the same directory — this class only manages ARTIFACT.md.
    """

    ARTIFACT_FILENAME = "ARTIFACT.md"

    def __init__(self, artifacts_dir: str):
        """
        Args:
            artifacts_dir: Absolute path to the artifacts root
                           (e.g. "data/main/artifacts")
        """
        self.artifacts_dir = Path(artifacts_dir)

    def save(
        self,
        category: str,
        slug: str,
        title: str,
        summary: str,
        tags: List[str],
        content: str,
        artifact_date: Optional[str] = None,
    ) -> str:
        """
        Write ARTIFACT.md for the given category/slug.

        Creates the directory tree lazily (exist_ok=True).

        Args:
            category:      Top-level category dir (e.g. "poetry")
            slug:          Artifact slug (e.g. "2026-03-06_recipe-caramel")
            title:         Human-readable title
            summary:       One-line summary for frontmatter
            tags:          List of tag strings
            content:       Body text (markdown, written after frontmatter)
            artifact_date: ISO date string; defaults to today

        Returns:
            str: Absolute path to the written ARTIFACT.md
        """
        artifact_dir = self.artifacts_dir / category / slug
        artifact_dir.mkdir(parents=True, exist_ok=True)

        if artifact_date is None:
            artifact_date = str(date_type.today())

        # Build YAML frontmatter
        tags_yaml = "[" + ", ".join(tags) + "]"
        frontmatter_lines = [
            "---",
            f'title: "{title}"',
            f"date: {artifact_date}",
            f"tags: {tags_yaml}",
            f'summary: "{summary}"',
            "---",
        ]

        frontmatter = "\n".join(frontmatter_lines)
        artifact_text = frontmatter + "\n\n" + content.strip() + "\n"

        artifact_path = artifact_dir / self.ARTIFACT_FILENAME
        artifact_path.write_text(artifact_text, encoding="utf-8")

        return str(artifact_path)

    def artifact_path(self, category: str, slug: str) -> Path:
        """Return the expected ARTIFACT.md path (may not exist yet)."""
        return self.artifacts_dir / category / slug / self.ARTIFACT_FILENAME

    def exists(self, category: str, slug: str) -> bool:
        """Check whether an artifact already exists on disk."""
        return self.artifact_path(category, slug).exists()
