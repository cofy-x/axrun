import json

import pytest
from test_programbench_official_verifier import OfficialBackend, _episode

from axrun.catalog import resolve_adapters
from axrun.errors import InfrastructureError
from axrun.runner import EpisodeRunner
from axrun.store import EpisodeStore


@pytest.mark.parametrize("variant", ["gold", "empty", "partial", "missing-dependency"])
def test_seqtk_uses_existing_compile_snapshot_branch_and_cleanup_contract(tmp_path, variant):
    episode = _episode(tmp_path, variant, "seqtk")
    # Official ProgramBench fixes CPU concurrency, not a memory hard-limit capability.
    assert episode.verification_resources.limit_memory == ""
    selection = resolve_adapters(episode)
    for role in ("inference", "verification"):
        assert selection.task.qualification_requirements(episode, role).mode == "prepared_contains"
    backend = OfficialBackend(variant=variant, case="seqtk")
    store = EpisodeStore(tmp_path / "state")
    runner = EpisodeRunner(backend=backend, store=store)
    kwargs = dict(
        inference=selection.inference, candidate=selection.candidate, verifier=selection.verifier
    )
    if variant == "missing-dependency":
        with pytest.raises(InfrastructureError, match="evaluator_environment_invalid"):
            runner.run(episode, **kwargs)
        assert not list((store.root / "verification-details").rglob("programbench.json"))
    else:
        result = runner.run(episode, **kwargs)
        assert result.details["active_test_count"] == 429
        assert result.details["not_run"] == (429 if variant == "empty" else 0)
        assert result.verdict == ("passed" if variant == "gold" else "failed")
        details = list((store.root / "verification-details").rglob("programbench.json"))
        assert len(details) == 1
        value = json.loads(details[0].read_text())
        assert value["instance_id"] == "lh3__seqtk.94e7070"
        assert value["evaluator_contract"] == "programbench-1.2.4-axrun-seqtk-v1"
        assert len(backend.created) == (2 if variant == "empty" else 4)
    assert backend.deleted_environments == ([] if variant == "empty" else [f"derived-{variant}"])
