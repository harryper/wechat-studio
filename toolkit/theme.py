"""
Theme system for WeChat Studio.

Loads YAML theme definitions for the converter and theme gallery.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Theme:
    """A theme definition with colors and base CSS."""

    name: str
    description: str
    base_css: str
    colors: dict = field(default_factory=dict)


def _default_themes_dir() -> str:
    """Return the themes/ directory relative to this file."""
    return str(Path(__file__).parent / "themes")


def load_theme(name: str, themes_dir: str = None) -> Theme:
    """
    Load a theme by name from a YAML file.

    Args:
        name: Theme name (without .yaml extension).
        themes_dir: Directory containing theme YAML files.
                    Defaults to themes/ relative to this file.

    Returns:
        A Theme object.

    Raises:
        FileNotFoundError: If the theme YAML file does not exist.
        ValueError: If the YAML is malformed or missing required fields.
    """
    if themes_dir is None:
        themes_dir = _default_themes_dir()

    theme_path = os.path.join(themes_dir, f"{name}.yaml")
    if not os.path.exists(theme_path):
        raise FileNotFoundError(f"Theme file not found: {theme_path}")

    with open(theme_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid theme file: {theme_path}")

    required = ("name", "description", "base_css", "colors")
    for key in required:
        if key not in data:
            raise ValueError(f"Theme file missing required field '{key}': {theme_path}")

    return Theme(
        name=data["name"],
        description=data["description"],
        base_css=data["base_css"],
        colors=data.get("colors", {}),
    )


def list_themes(themes_dir: str = None) -> list[str]:
    """
    List available theme names.

    Args:
        themes_dir: Directory containing theme YAML files.
                    Defaults to themes/ relative to this file.

    Returns:
        Sorted list of theme names (without .yaml extension).
    """
    if themes_dir is None:
        themes_dir = _default_themes_dir()

    if not os.path.isdir(themes_dir):
        return []

    names = []
    for filename in os.listdir(themes_dir):
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            names.append(filename.rsplit(".", 1)[0])

    return sorted(names)
