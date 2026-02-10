"""Tests for patch parsing and application."""

from __future__ import annotations

import pytest

from ee_bench_importer.patch_applier import (
    apply_patch_to_content,
    parse_patch,
    _reconstruct_added_file,
)


SAMPLE_DIFF = """diff --git a/hello.py b/hello.py
index 1234567..abcdefg 100644
--- a/hello.py
+++ b/hello.py
@@ -1,3 +1,4 @@
 def hello():
-    print("Hello")
+    print("Hello, World!")
+    return True
     pass
"""

SAMPLE_ADD_DIFF = """diff --git a/new_file.py b/new_file.py
new file mode 100644
index 0000000..abcdefg
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,3 @@
+def new_function():
+    return 42
+
"""

SAMPLE_DELETE_DIFF = """diff --git a/old_file.py b/old_file.py
deleted file mode 100644
index abcdefg..0000000
--- a/old_file.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def old():
-    pass
"""


class TestParsePatch:
    def test_parse_valid_diff(self):
        patchset = parse_patch(SAMPLE_DIFF)
        assert len(patchset) == 1
        assert patchset[0].target_file == "b/hello.py"

    def test_parse_empty_diff(self):
        with pytest.raises(ValueError, match="Empty patch"):
            parse_patch("")

    def test_parse_whitespace_only(self):
        with pytest.raises(ValueError, match="Empty patch"):
            parse_patch("   \n  ")

    def test_parse_added_file(self):
        patchset = parse_patch(SAMPLE_ADD_DIFF)
        assert len(patchset) == 1
        assert patchset[0].is_added_file

    def test_parse_deleted_file(self):
        patchset = parse_patch(SAMPLE_DELETE_DIFF)
        assert len(patchset) == 1
        assert patchset[0].is_removed_file

    def test_parse_multiple_files(self):
        combined = SAMPLE_DIFF + SAMPLE_ADD_DIFF
        patchset = parse_patch(combined)
        assert len(patchset) == 2


class TestApplyPatchToContent:
    def test_apply_modification(self):
        original = 'def hello():\n    print("Hello")\n    pass\n'
        result = apply_patch_to_content(original, SAMPLE_DIFF)
        assert 'print("Hello, World!")' in result
        assert "return True" in result

    def test_apply_to_wrong_content(self):
        original = "completely different content\n"
        with pytest.raises(ValueError, match="Failed to apply|does not match"):
            apply_patch_to_content(original, SAMPLE_DIFF)


class TestReconstructAddedFile:
    def test_reconstruct(self):
        patchset = parse_patch(SAMPLE_ADD_DIFF)
        content = _reconstruct_added_file(patchset[0])
        assert "def new_function():" in content
        assert "return 42" in content
