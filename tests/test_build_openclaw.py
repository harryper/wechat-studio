from scripts.build_openclaw import build


def test_build_excludes_development_and_builder_files(tmp_path):
    output = tmp_path / "openclaw"
    build(output)

    assert (output / "SKILL.md").is_file()
    assert (output / "scripts" / "write_article.py").is_file()
    assert (output / "references" / "knowledge-corpus.yaml").is_file()
    assert not (output / "scripts" / "build_openclaw.py").exists()
    assert not (output / "scripts" / "migrate_web_state_to_d1.py").exists()
    assert not (output / "references" / "plans").exists()
    assert not (output / "references" / "specs").exists()
