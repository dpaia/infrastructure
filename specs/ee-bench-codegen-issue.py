# Export EE-bench codegen datapoint from a single GitHub issue (DSL version)
# Usage: ee-dataset run-script specs/ee-bench-codegen-issue.py \
#   -S ORGANIZATION=apache -S REPOSITORY=kafka -S ISSUE_NUMBER=12345
# Override version: -S VERSION=2.0
# Override output:  -S OUTPUT=/tmp/my-output.json

from ee_bench_dsl import Pipeline, env

pipeline = (
    Pipeline()
    .provider(
        "github",
        type="github_issues",
        role="primary",
        fetch_commits=True,
        parse_comments=True,
        # build system is auto-detected by gradle/maven providers from repo_tree
    )
    .provider(
        "patch_splitter",
        type="patch_splitter",
        item_mapping={"patch": "{{ providers.github.patch }}"},
    )
    .provider(
        "maven",
        type="maven",
        item_mapping={
            "test_patch": "{{ fields.test_patch }}",
            "FAIL_TO_PASS": "{{ fields.FAIL_TO_PASS }}",
            "PASS_TO_PASS": "{{ fields.PASS_TO_PASS }}",
        },
    )
    .provider(
        "gradle",
        type="gradle",
        item_mapping={
            "test_patch": "{{ fields.test_patch }}",
            "FAIL_TO_PASS": "{{ fields.FAIL_TO_PASS }}",
            "PASS_TO_PASS": "{{ fields.PASS_TO_PASS }}",
        },
    )
    .generator("ee_bench_codegen")
    .generator_options(
        version=env("VERSION", default="1.0"),
        tags={
            "exclude": [
                "ee-bench-*",
                "Epic",
                "Review",
                "Invalid",
                "Wontfix",
                "Verified",
                "Bugfix",
                "Documentation",
            ],
        },
    )
    .select(
        "issues",
        repo=f"{env('ORGANIZATION')}/{env('REPOSITORY')}",
        issue_numbers=[int(env("ISSUE_NUMBER"))],
    )
    .defer_validation()
    .output(env("OUTPUT", default="/tmp/ee-bench-dsl-output.json"), fmt="json")
)
