"""Atomic Startup India GOAT research bundle persistence."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .startup_doctor import diagnose_sources, coverage_guidance
from .startup_export import export_json
from .startup_render import render_html, render_markdown
from .startup_schema import StartupProfile, to_dict
from .startup_sources import resolve_source

DEFAULT_STARTUP_MEMORY_DIR = Path.home() / "Documents" / "StartupIndiaGOAT"
_SECRET = re.compile(r"(?:token|secret|password|cookie|authorization|api[_-]?key|access[_-]?token)", re.I)
_SECRET_VALUE = re.compile(r"(?:bearer\s+[A-Za-z0-9._~+/=-]{12,}|(?:gh[pousr]|sk|xox[baprs])_[A-Za-z0-9_-]{12,}|AIza[0-9A-Za-z_-]{20,})", re.I)


def startup_memory_dir(value: str | os.PathLike[str] | None = None) -> Path:
    return Path(value or os.environ.get("STARTUP_GOAT_MEMORY_DIR") or DEFAULT_STARTUP_MEMORY_DIR).expanduser().resolve()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "startup-india-goat"


def _private_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_SECRET.search(str(key)) or _private_value(child) for key, child in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_private_value(child) for child in value)
    return isinstance(value, str) and bool(_SECRET.search(value) or _SECRET_VALUE.search(value))


def _public_profile(profile: StartupProfile) -> bool:
    """Return true only when every cited reference is a known public source."""
    for ref in profile.evidence:
        if not (ref.url or "").startswith("https://"):
            return False
        try:
            if not resolve_source(ref.source or "").public:
                return False
        except (KeyError, AttributeError):
            return False
    return not _private_value(to_dict(profile))


def _publication_safe(run: Any, profiles: list[StartupProfile], *, public_only: bool, private: bool, secret_tainted: bool) -> bool:
    """Fail closed for private, gated, mixed, unknown, or failed evidence."""
    if not public_only or private or secret_tainted or not all(_public_profile(profile) for profile in profiles):
        return False
    for result in getattr(getattr(run, "retrieval", None), "entities", ()):
        for item in getattr(result, "items", ()):
            metadata = getattr(item, "metadata", {}) or {}
            if str(metadata.get("access_state", "public")).casefold() not in {"public", "public-http"}:
                return False
        return False
    request = getattr(run, "request", None)
    for source in getattr(request, "sources", ()):
        try:
            if not resolve_source(source).public:
                return False
        except KeyError:
            return False
    bad_states = {"auth-failed", "login-required", "paywalled", "captcha", "quota-exhausted", "rate-limited", "unreachable", "timeout", "schema-drift", "skipped-unconfigured", "error", "partial"}
    for result in getattr(getattr(run, "retrieval", None), "entities", ()):
        for outcome in getattr(result, "outcomes", {}).values():
            if getattr(outcome, "state", None) in bad_states:
                return False
    return True


def _sanitize(value: Any, *, key: str = "") -> Any:
    if _SECRET.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _sanitize(v, key=str(k)) for k, v in value.items() if not _SECRET.search(str(k))}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize(item, key=key) for item in value]
    if isinstance(value, str) and (_SECRET.search(value) or _SECRET_VALUE.search(value)):
        return "[REDACTED]"
    return value


def _mkdir(path: Path, private: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if private:
        path.chmod(0o700)


def _reserve(directory: Path, stem: str, suffix: str) -> Path:
    for index in range(101):
        tail = "" if index == 0 else f"-{index}"
        candidate = directory / f"{stem}{tail}{suffix}"
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("could not allocate a collision-safe startup artifact path")


def _write(path: Path, content: str, private: bool) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600 if private else 0o644)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class StartupBundle:
    status: str
    directory: Path
    artifacts: dict[str, Path] = field(default_factory=dict)
    manifest: Path | None = None
    publication_allowed: bool = False
    guidance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "directory": str(self.directory), "artifacts": {key: str(path) for key, path in self.artifacts.items()}, "manifest": str(self.manifest) if self.manifest else None, "publication_allowed": self.publication_allowed, "guidance": list(self.guidance)}


def save_bundle(run: Any, *, save_dir: str | os.PathLike[str] | None = None, emit: str = "md,html,json", private: bool | None = None,
                include_private_evidence: bool = False, source_outcomes: Mapping[str, Any] | None = None) -> StartupBundle:
    """Persist a run; the manifest is the final completion marker."""
    if emit == "all": emit = "md,html,json"
    requested = {part.strip().casefold() for part in emit.split(",") if part.strip()}
    unknown = requested - {"md", "html", "json"}
    if unknown: raise ValueError(f"unknown startup emit format(s): {', '.join(sorted(unknown))}")
    if not requested: raise ValueError("at least one startup emit format is required")
    request = getattr(run, "request", None)
    public_only = bool(getattr(request, "public_only", True))
    profiles = list(getattr(run, "profiles", []))
    if not profiles:
        raise ValueError("cannot save a startup bundle without a resolved entity profile")
    private = bool(private) if private is not None else not public_only
    directory = startup_memory_dir(save_dir)
    _mkdir(directory, private)
    stem = _slug(getattr(request, "raw_query", "startup-india-goat"))
    created: list[Path] = []
    bundle = StartupBundle(status="failed", directory=directory)
    try:
        entity_results = {result.identity.entity_id: result for result in getattr(getattr(run, "retrieval", None), "entities", [])}
        outcomes_by_entity = {entity_id: result.outcomes for entity_id, result in entity_results.items()}
        secret_tainted = any(_private_value(to_dict(item)) for result in entity_results.values() for item in getattr(result, "items", []))
        public_artifacts = _publication_safe(run, profiles, public_only=public_only, private=private, secret_tainted=secret_tainted)
        allow_private_export = bool(include_private_evidence and not public_only and private)
        # Per-entity sanitized evidence is useful for audit but is not indexed.
        for profile in profiles:
            entity_dir = directory / "evidence"
            _mkdir(entity_dir, private)
            result = entity_results.get(profile.identity.entity_id)
            allow_private = allow_private_export
            evidence = []
            for ref in profile.evidence:
                try:
                    is_public_source = resolve_source(ref.source or "").public
                except (KeyError, AttributeError):
                    is_public_source = False
                if allow_private or (is_public_source and (ref.url or "").startswith("https://")):
                    evidence.append(ref)
            raw_items = []
            for item in getattr(result, "items", []) if result else []:
                try:
                    capability = resolve_source(item.source)
                except KeyError:
                    continue
                metadata = getattr(item, "metadata", {}) or {}
                access_state = str(metadata.get("access_state", "public")).casefold()
                if not allow_private and (not capability.public or access_state not in {"public", "public-http"}):
                    continue
                raw_items.append(_sanitize(to_dict(item)))
            path = _reserve(entity_dir, f"{_slug(profile.identity.display_name)}-evidence", ".json")
            created.append(path)
            payload = {"entity_id": profile.identity.entity_id, "evidence": [to_dict(ref) for ref in evidence], "raw_items": raw_items}
            _write(path, json.dumps(_sanitize(payload), indent=2, sort_keys=True) + "\n", private)
            bundle.artifacts[f"evidence:{profile.identity.entity_id}"] = path
        value = run.group_profile if len(profiles) > 1 else profiles[0]
        render_kwargs = {"source_outcomes": outcomes_by_entity if len(profiles) > 1 else (next(iter(outcomes_by_entity.values()), {}))}
        if len(profiles) > 1:
            render_kwargs["query"] = getattr(request, "raw_query", None)
        if "md" in requested:
            content = render_markdown(value, **render_kwargs)
            path = _reserve(directory, stem, ".md"); created.append(path); _write(path, content, private); bundle.artifacts["markdown"] = path
        if "html" in requested:
            content = render_html(value, **render_kwargs)
            path = _reserve(directory, stem, ".html"); created.append(path); _write(path, content, private); bundle.artifacts["html"] = path
        if "json" in requested:
            paths = {key: str(path.relative_to(directory)) for key, path in bundle.artifacts.items()}
            retrieval = getattr(run, "retrieval", None)
            incomplete = bool(getattr(retrieval, "warnings", [])) or any(getattr(entity, "partial", False) for entity in getattr(retrieval, "entities", []))
            content = export_json(run, artifact_paths=paths, public_only=not allow_private_export, status="partial" if incomplete else "complete")
            path = _reserve(directory, stem, ".json"); created.append(path); _write(path, content, private); bundle.artifacts["json"] = path
        # Only public markdown is eligible for the scoped library index.
        if public_artifacts and "markdown" in bundle.artifacts:
            try:
                from . import library_index
                library_index.index_brief(bundle.artifacts["markdown"], db_path=directory / ".startup-india-goat-library.db")
            except Exception:
                pass
        statuses = diagnose_sources(public_only=public_only, outcomes=next(iter(outcomes_by_entity.values()), {}))
        bundle.guidance = coverage_guidance(statuses, public_only=public_only)
        bundle.publication_allowed = bool(public_artifacts and not _private_value(bundle.to_dict()))
        retrieval = getattr(run, "retrieval", None)
        bundle.status = "complete" if getattr(retrieval, "complete", False) else "partial"
        manifest_data = {"schema_version": "startup-india-goat-manifest/1.0", "status": bundle.status, "created_at": datetime.now(timezone.utc).isoformat(), "publication_allowed": bundle.publication_allowed, "artifacts": {key: {"path": str(path.relative_to(directory)), "sha256": _hash(path), "mode": oct(path.stat().st_mode & 0o777)} for key, path in bundle.artifacts.items()}, "guidance": bundle.guidance}
        manifest = _reserve(directory, f"{stem}-manifest", ".json"); created.append(manifest); _write(manifest, json.dumps(manifest_data, indent=2, sort_keys=True) + "\n", private); bundle.manifest = manifest
        return bundle
    except BaseException:
        for path in reversed(created):
            try: path.unlink(missing_ok=True)
            except OSError: pass
        bundle.status = "failed"
        raise


def save_startup_bundle(run: Any, **kwargs: Any) -> StartupBundle:
    return save_bundle(run, **kwargs)

__all__ = ["DEFAULT_STARTUP_MEMORY_DIR", "StartupBundle", "save_bundle", "save_startup_bundle", "startup_memory_dir"]
