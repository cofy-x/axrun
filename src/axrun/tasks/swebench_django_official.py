"""Single-instance Django task gate bound to actual-runtime admission."""

from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axrun.adapters.base import TaskQualificationRequirements
from axrun.adapters.swebench_django_official import validated_django_verifier_inputs
from axrun.datasets import swebench_django_official as lock
from axrun.errors import ContractError
from axrun.models import ResolvedEpisode, StageNetworkPolicy
from axrun.tasks.django_admission import load_django_admission


@dataclass(frozen=True, slots=True)
class SweBenchDjangoOfficialTaskAdapter:
    name: str = "swebench-django-official"
    version: str = "1"

    def validate_admission(self, episode: ResolvedEpisode) -> dict[str, Any]:
        if (
            episode.schema_version != 2
            or episode.task_id != lock.INSTANCE
            or (episode.task.identity, episode.task.version) != (self.name, self.version)
            or (episode.verifier.identity, episode.verifier.version) != (self.name, self.version)
            or episode.seed_digest != lock.SEED_DIGEST
            or episode.inference_network != StageNetworkPolicy.DENY_ALL
            or episode.verification_network != StageNetworkPolicy.DENY_ALL
            or (episode.harness.identity, episode.harness.version, episode.harness.config)
            != ("static-candidate", "1", {})
            or (episode.candidate.identity, episode.candidate.version) != ("git-patch", "1")
        ):
            raise ContractError("Django task requires the locked static admitted episode contract")
        config = episode.task.config
        if (
            set(config) != {"base_commit", "admission_receipt_file", "admission_receipt_sha256"}
            or config["base_commit"] != lock.IMAGE_HEAD
            or config["admission_receipt_sha256"] != lock.ADMISSION_RECEIPT_SHA256
        ):
            raise ContractError("Django task requires mandatory admission evidence")
        reference = config["admission_receipt_file"]
        if not isinstance(reference, str) or not Path(reference).is_absolute():
            raise ContractError("Django admission reference must be an absolute file")
        inference, verification = episode.inference_environment, episode.verification_environment
        if (
            inference.environment_id == verification.environment_id
            or inference.image != lock.TASK_IMAGE
            or verification.image != lock.TASK_IMAGE
            or any(
                binding.platform != "linux/amd64" or binding.working_directory != "/testbed"
                for binding in (inference, verification)
            )
        ):
            raise ContractError("Django requires distinct offline amd64 Environments")
        receipt = load_django_admission(
            Path(reference),
            task_image=lock.TASK_IMAGE,
            expected_sha256=lock.ADMISSION_RECEIPT_SHA256,
        )
        expected_metadata = {
            "dataset_identity": lock.DATASET,
            "dataset_commit": lock.DATASET_COMMIT,
            "dataset_version": lock.SCHEMA,
            "official_row_sha256": lock.ROW_SHA256,
            "official_row_base_commit": lock.IMAGE_HEAD,
            "official_image_head": lock.IMAGE_HEAD,
            "official_source_image": lock.SOURCE_IMAGE,
            "task_image": lock.TASK_IMAGE,
            "task_platform": "linux/amd64",
            "official_instance_scope": "locked-single-instance",
        }
        if episode.metadata != expected_metadata:
            raise ContractError("Django resolved metadata differs from lock")
        prompt = Path(episode.prompt_file)
        try:
            if (
                prompt.is_symlink()
                or not stat.S_ISREG(prompt.lstat().st_mode)
                or hashlib.sha256(prompt.read_bytes()).hexdigest() != lock.PROMPT_SHA256
            ):
                raise ContractError("Django task prompt differs from lock")
        except OSError as exc:
            raise ContractError("Django task prompt is unavailable") from exc
        validated_django_verifier_inputs(episode)
        if set(episode.candidate.config) != {"source_file"}:
            raise ContractError("Django static candidate configuration differs")
        candidate = episode.candidate.config["source_file"]
        if not isinstance(candidate, str) or not Path(candidate).is_absolute():
            raise ContractError("Django static candidate source must be absolute")
        try:
            source = Path(candidate)
            if (
                source.is_symlink()
                or not stat.S_ISREG(source.lstat().st_mode)
                or source.stat().st_size > 64 << 20
            ):
                raise ContractError("Django static candidate source must be a regular file")
        except OSError as exc:
            raise ContractError("Django static candidate source is unavailable") from exc
        return receipt

    def admission_report(self, episode: ResolvedEpisode) -> dict[str, Any]:
        receipt = self.validate_admission(episode)
        return {
            "schema_version": receipt["schema_version"],
            "receipt_sha256": lock.ADMISSION_RECEIPT_SHA256,
            "runtime_image": receipt["runtime_image"],
            "scanner_sha256": receipt["scanner_sha256"],
            "execution": receipt["execution"],
            "sealed_sha256": receipt["sealed_sha256"],
            "sealed_size_bytes": receipt["sealed_size_bytes"],
            "status": receipt["status"],
            "reason_code": receipt["reason_code"],
            "cleanup": receipt["cleanup"],
            "trust_boundary": "caller-owned-state",
        }

    def qualification_requirements(
        self, episode: ResolvedEpisode, role: str
    ) -> TaskQualificationRequirements:
        self.validate_admission(episode)
        if role not in {"inference", "verification"}:
            raise ContractError("Django qualification role is invalid")
        return TaskQualificationRequirements(mode="git", base_commit=lock.IMAGE_HEAD)
