from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_obsolete_source_and_dependency_are_absent():
    obsolete = [
        ROOT / "scripts" / "seo_keywords.py",
        ROOT / "toolkit" / "fix_image_paths.py",
        ROOT / "toolkit" / "normalize_image.py",
    ]
    assert not [path for path in obsolete if path.exists()]
    assert "cssutils" not in (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "cssutils" not in (ROOT / "scripts" / "diagnose.py").read_text(encoding="utf-8").lower()
