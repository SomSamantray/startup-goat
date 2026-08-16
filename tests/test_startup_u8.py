from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from lib import startup_save
from lib.schema import SourceItem
from lib.startup_doctor import coverage_guidance, diagnose_sources
from lib.startup_export import JSON_SCHEMA_VERSION, export_payload
from lib.startup_goat import research
from lib.startup_schema import EvidenceReference, StartupIdentity, StartupProfile


def _run():
    return research("Acme", sources=["startup-india"], mock=True)


def test_json_contract_is_versioned_and_secret_free():
    payload = export_payload(_run(), request={"api_key": "do-not-export"})
    assert payload["schema_version"] == JSON_SCHEMA_VERSION
    dumped = json.dumps(payload)
    assert "do-not-export" not in dumped
    assert {"profiles", "coverage", "artifacts", "request"} <= payload.keys()


def test_secret_like_raw_items_disable_public_publication(tmp_path: Path):
    run = _run()
    run.entities[0].items.append(SourceItem(
        item_id="secret-item", source="startup-india", title="public title",
        body="Bearer ghp_1234567890abcdef", url="https://startupindia.gov.in/acme",
    ))
    bundle = startup_save.save_bundle(run, save_dir=tmp_path, emit="json")
    assert bundle.publication_allowed is False
    evidence = next(path for key, path in bundle.artifacts.items() if key.startswith("evidence:"))
    assert "ghp_1234567890abcdef" not in evidence.read_text()


def test_save_collision_manifest_last_and_hashes(tmp_path: Path):
    first = startup_save.save_bundle(_run(), save_dir=tmp_path, emit="md,html,json")
    second = startup_save.save_bundle(_run(), save_dir=tmp_path, emit="md")
    assert first.status == "complete" and first.manifest and first.manifest.exists()
    assert first.artifacts["markdown"] != second.artifacts["markdown"]
    manifest = json.loads(first.manifest.read_text())
    for item in manifest["artifacts"].values():
        path = tmp_path / item["path"]
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_private_bundle_permissions(tmp_path: Path):
    bundle = startup_save.save_bundle(_run(), save_dir=tmp_path, emit="json", private=True)
    assert (tmp_path.stat().st_mode & 0o777) == 0o700
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in [*bundle.artifacts.values(), bundle.manifest])


def test_render_failure_cleans_incomplete_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(startup_save, "render_markdown", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("render")))
    with pytest.raises(RuntimeError):
        startup_save.save_bundle(_run(), save_dir=tmp_path, emit="md")
    assert not list(tmp_path.glob("*.md"))
    assert not list(tmp_path.glob("*-manifest.json"))


def test_doctor_classifies_public_gated_and_schema_drift():
    report = diagnose_sources(public_only=True, outcomes={"startup-india": {"state": "schema-drift"}})
    statuses = {item["source"]: item["status"] for item in report["sources"]}
    assert statuses["linkedin"] == "gated"
    assert statuses["tracxn"] == "gated"
    assert statuses["startup-india"] == "schema-drift"
    assert any("unavailable" in line for line in coverage_guidance(report))


def test_unknown_private_evidence_is_not_exported():
    identity = StartupIdentity(entity_id="entity1", display_name="Acme", normalized_name="acme", state="resolved", confidence="high")
    profile = StartupProfile(identity=identity, evidence=[EvidenceReference("private", source="tracxn", url="https://tracxn.com/acme")])
    payload = export_payload(profile, public_only=True)
    assert payload["profiles"][0]["evidence"] == []
