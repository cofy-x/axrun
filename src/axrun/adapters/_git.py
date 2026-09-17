"""Trusted canonical Git patch export used after an agent exits."""

from __future__ import annotations

import shlex


def canonical_patch_export(base_commit: str, output_path: str) -> str:
    """Return shell code that exports the complete workspace delta.

    A temporary index includes committed, staged, unstaged, deleted, and
    non-ignored untracked files without changing the agent's real index.
    """

    base = shlex.quote(base_commit)
    output = shlex.quote(output_path)
    return "\n".join(
        (
            "tmp_dir=$(mktemp -d)",
            "patch_rc=$?",
            'tmp_index="$tmp_dir/index"',
            'if [ "$patch_rc" -eq 0 ]; then',
            f"  base_tree=$(git rev-parse --verify {base}^{{commit}})",
            "  patch_rc=$?",
            "fi",
            'if [ "$patch_rc" -eq 0 ]; then',
            '  GIT_INDEX_FILE="$tmp_index" git read-tree HEAD &&',
            '    GIT_INDEX_FILE="$tmp_index" git -c core.fileMode=false add -A -- . &&',
            '    GIT_INDEX_FILE="$tmp_index" git -c core.fileMode=false '
            f'--no-pager diff --cached --binary "$base_tree" -- > {output}',
            "  patch_rc=$?",
            "fi",
            'test -z "$tmp_dir" || rm -rf -- "$tmp_dir"',
        )
    )
