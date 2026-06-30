from harbor_emitter import emit_harbor_task


def test_emitted_test_wrapper_excludes_ee_bench_from_submission_diff(tmp_path) -> None:
    record = {
        "instance_id": "owner__repo-1",
        "repo": "owner/repo",
        "base_commit": "abc123",
        "problem_statement": "Fix validation errors.",
        "environment": {
            "files": {
                "Dockerfile": "FROM scratch\n",
            },
        },
        "eval": {
            "files": {
                "run.sh": "#!/usr/bin/env bash\n",
            },
        },
        "verify": {
            "files": {
                "patch.diff": "",
            },
        },
    }

    emit_harbor_task(record, tmp_path / "task")

    test_wrapper = (tmp_path / "task" / "tests" / "test.sh").read_text()
    assert "git diff --binary --no-ext-diff HEAD -- . ':(exclude).ee-bench/**'" in test_wrapper
    assert "git diff --binary --no-ext-diff HEAD > /ee-bench/submission/patch.diff" not in test_wrapper
