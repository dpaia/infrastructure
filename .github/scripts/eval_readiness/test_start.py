from eval_readiness.config import LanguageMapping, ReadinessConfig, ReadinessProfile
from eval_readiness.start import StartDecision, evaluate_start, parse_instance_id


def test_parse_instance_id_from_github_data_url() -> None:
    assert (
        parse_instance_id("https://github.com/dpaia/dataset/blob/main/codegen/spring/dpaia__spring-132.json")
        == "dpaia__spring-132"
    )


def test_evaluate_start_accepts_valid_item() -> None:
    decision = evaluate_start(
        eval_type="codegen",
        pr_state="CLOSED",
        labels=["REST", "Language: Java"],
        eval_item={"fields": {"Status": "Prepare for Eval", "Verification": "Generated"}},
        dataset_item={"fields": {"Data": "https://github.com/dpaia/dataset/blob/main/codegen/repo/inst-1.json"}},
        readiness_config=_config(),
    )

    assert decision == StartDecision(
        queued=True,
        reason="queued",
        detail="Eval-readiness start guards passed",
        instance_id="inst-1",
        data_url="https://github.com/dpaia/dataset/blob/main/codegen/repo/inst-1.json",
        hf_path="code-generation-swe/java/dpai-java-instances.large",
        hf_dataset="JetBrains/eval_plugin",
        language_label="Language: Java",
    )


def test_evaluate_start_blocks_wrong_public_status() -> None:
    decision = evaluate_start(
        eval_type="codegen",
        pr_state="CLOSED",
        labels=["Language: Java"],
        eval_item={"fields": {"Status": "Done", "Verification": "Generated"}},
        dataset_item={"fields": {"Data": "https://github.com/dpaia/dataset/blob/main/codegen/repo/inst-1.json"}},
        readiness_config=_config(),
    )

    assert not decision.queued
    assert decision.reason == "invalid_public_status"


def test_evaluate_start_blocks_missing_dataset_data() -> None:
    decision = evaluate_start(
        eval_type="codegen",
        pr_state="CLOSED",
        labels=["Language: Java"],
        eval_item={"fields": {"Status": "Prepare for Eval", "Verification": "Generated"}},
        dataset_item={"fields": {}},
        readiness_config=_config(),
    )

    assert not decision.queued
    assert decision.reason == "missing_dataset_data"


def test_evaluate_start_blocks_unsupported_language() -> None:
    decision = evaluate_start(
        eval_type="codegen",
        pr_state="CLOSED",
        labels=["Language: Python"],
        eval_item={"fields": {"Status": "Prepare for Eval", "Verification": "Generated"}},
        dataset_item={"fields": {"Data": "https://github.com/dpaia/dataset/blob/main/codegen/repo/inst-1.json"}},
        readiness_config=_config(),
    )

    assert not decision.queued
    assert decision.reason == "missing_language"
    assert decision.instance_id == "inst-1"


def _config() -> ReadinessConfig:
    return ReadinessConfig(
        profiles={
            "codegen": ReadinessProfile(
                eval_type="codegen",
                enabled=True,
                hf_dataset="JetBrains/eval_plugin",
                hf_base_path="code-generation-swe",
                generator_kind="dpai-generic-format",
                registration_bucket="swe/dataset/dev",
            )
        },
        languages={
            "Language: Java": LanguageMapping(
                label="Language: Java",
                hf_dir="java",
                hf_filename="dpai-java-instances.large",
                pipeline_language_enum="JAVA",
                teamcity_dataset_id="Dpai-Bench",
            )
        },
    )
