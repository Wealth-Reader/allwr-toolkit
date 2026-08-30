"""Selection manifest parsing."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from allwr_toolkit.connectors.asana.manifest import read_selection_manifest
from allwr_toolkit.core.errors import ConfigurationError


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "manifest.txt"
    path.write_text(content, encoding="utf-8")
    return path


def test_selects_gid_lines_and_ignores_comments(tmp_path: Path) -> None:
    manifest = read_selection_manifest(
        write(
            tmp_path,
            "# header comment\n"
            "## Project section\n"
            "1200000000000001\tProject\tOPEN\ttitle one\n"
            "#1200000000000002\tProject\tOPEN\texcluded\n"
            "\n"
            "1200000000000003\n",
        )
    )
    assert manifest.selected == ["1200000000000001", "1200000000000003"]
    assert manifest.invalid_lines == []


def test_duplicate_gids_reported_once(tmp_path: Path) -> None:
    manifest = read_selection_manifest(
        write(
            tmp_path,
            "1200000000000001\tfirst\n1200000000000001\tsecond\n",
        )
    )
    assert manifest.selected == ["1200000000000001"]
    assert manifest.duplicates == ["1200000000000001"]


def test_invalid_gid_like_lines_are_reported_not_dropped(tmp_path: Path) -> None:
    manifest = read_selection_manifest(write(tmp_path, "12ab\tnot a gid\n1200000000000001\tfine\n"))
    assert manifest.selected == ["1200000000000001"]
    assert manifest.invalid_lines == [1]


def test_distinct_gids_with_equal_titles_stay_distinct(tmp_path: Path) -> None:
    manifest = read_selection_manifest(
        write(
            tmp_path,
            "1200000000000001\tProject\tOPEN\tSame title\n"
            "1200000000000004\tProject\tOPEN\tSame title\n",
        )
    )
    assert manifest.selected == ["1200000000000001", "1200000000000004"]
    assert manifest.duplicates == []


def test_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        read_selection_manifest(tmp_path / "nope.txt")


@given(st.text(alphabet=st.characters(exclude_characters="\n\r"), max_size=60))
def test_comment_lines_never_select(prefix: str) -> None:
    line = "#" + prefix
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "m.txt"
        path.write_text(line + "\n", encoding="utf-8")
        manifest = read_selection_manifest(path)
        assert manifest.selected == []
