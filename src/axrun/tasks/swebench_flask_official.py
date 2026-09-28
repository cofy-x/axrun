"""Closed Flask task semantics and mandatory caller-owned image admission."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axrun.adapters.base import TaskQualificationRequirements
from axrun.adapters.swebench_flask_official import validated_flask_verifier_inputs
from axrun.datasets import swebench_flask_official as lock
from axrun.errors import ContractError
from axrun.harnesses import resolve_claude_code_spec
from axrun.models import ResolvedEpisode, StageNetworkPolicy, canonical_digest
from axrun.tasks.flask_admission import load_flask_admission


@dataclass(frozen=True, slots=True)
class SweBenchFlaskOfficialTaskAdapter:
    name: str = "swebench-flask-official"
    version: str = "1"

    def validate_admission(self, episode: ResolvedEpisode) -> dict[str, Any]:
        if (
            episode.schema_version != 2
            or episode.task_id != lock.admission_contract()["INSTANCE"]
            or (episode.task.identity, episode.task.version) != (self.name, self.version)
            or (episode.verifier.identity, episode.verifier.version) != (self.name, self.version)
            or episode.seed_digest != lock.admission_contract()["SEED_DIGEST"]
            or episode.inference_network != StageNetworkPolicy.DENY_ALL
            or episode.verification_network != StageNetworkPolicy.DENY_ALL
            or (episode.candidate.identity, episode.candidate.version) != ("git-patch", "1")
        ):
            raise ContractError("Flask task requires the locked admitted episode contract")
        config = episode.task.config
        if (
            set(config) != {"base_commit", "admission_receipt_file", "admission_receipt_sha256"}
            or config["base_commit"] != lock.admission_contract()["IMAGE_HEAD"]
        ):
            raise ContractError("Flask task requires mandatory admission evidence")
        if any(
            not isinstance(config[key], str) or not config[key]
            for key in ("admission_receipt_file", "admission_receipt_sha256")
        ):
            raise ContractError("Flask admission reference is invalid")
        path = Path(config["admission_receipt_file"])
        if not path.is_absolute():
            raise ContractError("Flask admission reference must be absolute")
        inference, verification = episode.inference_environment, episode.verification_environment
        if (
            inference.environment_id == verification.environment_id
            or inference.image != verification.image
            or any(
                binding.platform != "linux/amd64" or binding.working_directory != "/testbed"
                for binding in (inference, verification)
            )
        ):
            raise ContractError("Flask requires distinct offline amd64 task Environments")
        receipt = load_flask_admission(
            path, task_image=inference.image, expected_sha256=config["admission_receipt_sha256"]
        )
        expected_metadata = {
            "dataset_identity": lock.admission_contract()["DATASET"],
            "dataset_commit": lock.admission_contract()["DATASET_COMMIT"],
            "dataset_version": lock.admission_contract()["SCHEMA"],
            "official_row_sha256": lock.admission_contract()["ROW_SHA256"],
            "official_row_base_commit": lock.admission_contract()["ROW_BASE_COMMIT"],
            "official_image_head": lock.admission_contract()["IMAGE_HEAD"],
            "official_source_image": lock.admission_contract()["SOURCE_IMAGE"],
            "task_image": inference.image,
            "task_platform": lock.admission_contract()["PLATFORM"],
            "official_instance_scope": "locked-single-instance",
        }
        if episode.metadata != expected_metadata:
            raise ContractError("Flask resolved metadata differs from lock")
        prompt = Path(episode.prompt_file)
        if (
            prompt.is_symlink()
            or not prompt.is_file()
            or hashlib.sha256(prompt.read_bytes()).hexdigest()
            != lock.admission_contract()["PROMPT_SHA256"]
        ):
            raise ContractError("Flask task prompt differs from lock")
        verifier = episode.verifier.config
        validated_flask_verifier_inputs(episode)
        if (
            canonical_digest(
                {
                    "fail_to_pass": verifier.get("fail_to_pass"),
                    "pass_to_pass": verifier.get("pass_to_pass"),
                }
            )
            != lock.admission_contract()["TEST_SELECTION_DIGEST"]
        ):
            raise ContractError("Flask expected test selection differs from lock")
        if episode.harness.identity == "claude-code":
            if resolve_claude_code_spec(episode.harness) != episode.harness:
                raise ContractError("Flask Claude runtime defaults are not materialized")
            if episode.harness.config["working_directory"] != "/testbed" or not {
                "WebFetch",
                "WebSearch",
            }.issubset(episode.harness.config["disallowed_tools"]):
                raise ContractError("Flask Claude requires offline tool restrictions")
            if episode.candidate.config:
                raise ContractError("Flask Claude cannot receive a static candidate")
        elif (episode.harness.identity, episode.harness.version, episode.harness.config) == (
            "static-candidate",
            "1",
            {},
        ):
            if set(episode.candidate.config) != {"source_file"}:
                raise ContractError("Flask static candidate configuration differs")
        else:
            raise ContractError("Flask requires a reviewed static or Claude harness")
        return receipt

    def admission_report(self, episode: ResolvedEpisode) -> dict[str, Any]:
        """Bounded evidence, not hidden signatures or a claim of signed provenance."""
        receipt = self.validate_admission(episode)
        return {
            "schema_version": receipt["schema_version"],
            "receipt_sha256": episode.task.config["admission_receipt_sha256"],
            "source_image": receipt["source_image"],
            "runtime_image": receipt["runtime_image"],
            "platform": receipt["platform"],
            "import_digest": receipt["import_digest"],
            "scanner_sha256": receipt["scanner_sha256"],
            "execution": receipt["execution"],
            "sealed_sha256": receipt["sealed_sha256"],
            "sealed_size_bytes": receipt["sealed_size_bytes"],
            "status": receipt["status"],
            "reason_code": receipt["reason_code"],
            "trust_boundary": "caller-owned-state",
        }

    def qualification_requirements(
        self, episode: ResolvedEpisode, role: str
    ) -> TaskQualificationRequirements:
        self.validate_admission(episode)
        if role not in {"inference", "verification"}:
            raise ContractError("Flask qualification role is invalid")
        return TaskQualificationRequirements(
            mode="git", base_commit=lock.admission_contract()["IMAGE_HEAD"]
        )
