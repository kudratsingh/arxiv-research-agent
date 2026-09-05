"""A local content-addressed artifact store: stage, verify, promote, scope.

RFC 10 §7 says an artifact is bytes plus a digest, a byte length, a media
type, a trust class, a data class and a retention policy — and that the
store verifies the first two *on write and on read*, refuses a temporary
signed URL as a locator, and enforces the run's principal scope
independently of possession of the hash.  This module is that store, in
the shape the RFC calls "a local-filesystem test backend": no object
store, no network, no credential.

Three properties are worth stating before the code, because each one is
a rule the tests hold rather than a convenience:

- **Staging comes first.**  Bytes land in a staging namespace, are
  hashed and screened there, and only then are promoted into the
  content-addressed tree.  A promotion that fails leaves nothing behind
  in `cas/`, which is what makes the store's contents trustworthy by
  construction: everything under `cas/` has passed every check.
- **The digest is the identity.**  Two callers who stage the same bytes
  promote to one object with one `artifact:sha256:<hex>` id, and the
  second promotion writes no bytes.  Deduplication is therefore free and
  automatic — and it is also the reason principal scope is a *separate*
  index: a global content hash must not become a cross-principal read
  (RFC 10 §10.2).
- **Refusal is a first-class outcome.**  A signed URL, a secret, raw
  private reasoning or a data-class downgrade is not sanitised, not
  truncated, and not stored "for debugging".  It raises, and the bytes
  are removed from staging.

What this module deliberately does *not* have is a deleter.  Retention
is an interface (`RetentionHook`) and nothing more: RFC 10 §14.2 and the
W09 governance review own the policy, D8 owns whether production content
may be captured at all, and a store that could delete before those exist
would be a policy decision wearing an implementation's clothes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol, TypedDict

from src.contracts.kernel import (
    ContractError,
    ContractErrorCode,
    DataClass,
    RetentionPolicyRef,
)
from src.contracts.trajectory import ArtifactRef, ArtifactRole, TrustClass
from src.observability.logging import get_logger
from src.observability.metrics import record_trajectory_fault

log = get_logger(__name__)

#: Hard ceiling on one artifact, in bytes.  Eight mebibytes is far above
#: anything this product produces (a research briefing is tens of
#: kilobytes) and far below anything that would make a local store a
#: memory hazard.  A caller with genuinely larger content wants a
#: streaming object store, which is exactly the interface this adapter
#: keeps behind it.
MAX_ARTIFACT_BYTES: Final[int] = 8 * 1024 * 1024

#: Media types whose bodies are screened as text.  Binary bodies (a PDF,
#: a PNG) are stored on their digest alone: scanning them for a
#: `sk-`-shaped byte run would be superstition, not a control, and the
#: refusals below are about *text a producer could have redacted*.
_TEXT_MEDIA_PREFIXES: Final[tuple[str, ...]] = (
    "text/",
    "application/json",
    "application/x-ndjson",
    "application/xml",
    "application/yaml",
)

#: A locator that expires.  RFC 10 §7.1 rule 4 forbids one as a
#: `storage_uri`; this store additionally refuses one *inside* an
#: artifact body, because an evidence record that quotes a presigned S3
#: URL has embedded a credential in content that outlives it.
_SIGNED_URL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)[?&]X-Amz-Signature="),
    re.compile(r"(?i)[?&]X-Amz-Credential="),
    re.compile(r"(?i)[?&]GoogleAccessId="),
    re.compile(r"(?i)[?&]Signature=[^&\s]{8,}"),
    re.compile(r"(?i)[?&]sig=[^&\s]{16,}"),
    re.compile(r"(?i)[?&](?:token|access_token|sas)=[^&\s]{16,}"),
)

#: Credential shapes.  Deliberately the same families the trajectory
#: envelope screens for (`src/contracts/trajectory.py`), because a body
#: that may not appear in an event payload may not appear in an artifact
#: either — the artifact is simply where the bigger version of the same
#: content would go.
_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|passwd|secret)\s*[:=]\s*\S{6,}"),
)

#: Private reasoning.  RFC 10 §10.1 excludes "private chain-of-thought,
#: scratchpads, hidden reasoning tokens, or requests to reconstruct
#: them" from events; §7.1 rule 6 routes bodies to artifacts, so without
#: this rule the artifact store would be the loophole that makes the
#: event rule decorative.
_PRIVATE_REASONING_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)</?thinking>"),
    re.compile(r"(?i)</?scratchpad>"),
    re.compile(r"(?i)\bchain[ _-]of[ _-]thought\b"),
    re.compile(r"(?i)\bhidden[ _-]reasoning\b"),
    re.compile(r"(?i)\breasoning_content\b"),
)

#: Data classes that are scoped to the principal who produced them.
#: `public` and `internal` content is system-generated and readable by
#: any authenticated caller of the store; anything user- or
#: learner-derived is not, whoever holds its hash.
_PRINCIPAL_SCOPED: Final[frozenset[DataClass]] = frozenset(
    {DataClass.USER_CONFIDENTIAL, DataClass.LEARNER_SENSITIVE}
)

_PRINCIPAL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:pk_[a-z0-9]{8,64}|synthetic:[a-z0-9][a-z0-9_.:-]{0,127})$"
)


class _RefRecord(TypedDict):
    """The on-disk scope record for one promoted artifact.

    Typed rather than a bare dict so the access check below reads a
    `data_class` and a principal list the type checker has agreed exist:
    an authorization decision made from `record["data_class"]` typed as
    `object` is one `str()` away from always passing.
    """

    artifact_id: str
    digest: str
    byte_length: int
    data_class: str
    principals: list[str]
    ref: str


class ArtifactStoreError(ContractError):
    """A refused or failed artifact operation.

    Carries two codes rather than one.  `code` is the contract's
    machine-readable category (`src.contracts.kernel.ContractErrorCode`);
    `app_error_code` is the member of ADR 0064's closed `ERROR_CODES`
    registry that a runtime surface — a log line, a metric attribute, a
    job row — is allowed to report.  Two vocabularies exist because the
    contract package and the product's error taxonomy are separately
    owned and versioned, and inventing a third would be worse than
    carrying both.
    """

    def __init__(
        self,
        detail: str,
        *,
        code: ContractErrorCode = ContractErrorCode.SCHEMA_INVALID,
        app_error_code: str = "invalid_provenance",
    ) -> None:
        self.app_error_code = app_error_code
        super().__init__(code, detail)


class ArtifactIntegrityError(ArtifactStoreError):
    """The declared digest or byte length does not match the bytes."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            detail,
            code=ContractErrorCode.DIGEST_INVALID,
            app_error_code="invalid_provenance",
        )


class ArtifactRefused(ArtifactStoreError):
    """The content or its classification is not permitted to be stored."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            detail,
            code=ContractErrorCode.REDACTION_REQUIRED,
            app_error_code="forbidden",
        )


class ArtifactAccessDenied(ArtifactStoreError):
    """A principal asked for an artifact scoped to a different principal."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            detail,
            code=ContractErrorCode.REF_INVALID,
            app_error_code="forbidden",
        )


class ArtifactNotFound(ArtifactStoreError):
    """The store holds no artifact under that id."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            detail,
            code=ContractErrorCode.REF_INVALID,
            app_error_code="not_found",
        )


class RetentionHook(Protocol):
    """The retention seam, and only the seam.

    RFC 10 §14.2 makes every artifact carry a `retention_policy_ref`
    resolved by an external data-policy registry, and W09/D8 own what
    those policies say.  The store therefore *notifies* a hook and asks
    it for an expiry, and never acts on the answer: nothing in this
    module deletes bytes.  When a policy exists, the deleter is a new
    work order with a decision behind it, not a flag flip here.
    """

    def on_promoted(self, ref: ArtifactRef, *, principal_key_id: str) -> None:
        """Called once per newly promoted artifact, after its bytes land."""

    def expires_at(self, ref: ArtifactRef) -> str | None:
        """The RFC 3339 expiry this policy implies, or `None` for none."""


@dataclass(frozen=True)
class NullRetentionHook:
    """The default hook: records the call, keeps nothing, deletes nothing."""

    seen: list[str] = field(default_factory=list)

    def on_promoted(self, ref: ArtifactRef, *, principal_key_id: str) -> None:
        self.seen.append(ref.artifact_id)

    def expires_at(self, ref: ArtifactRef) -> str | None:
        return None


@dataclass(frozen=True)
class StagedArtifact:
    """Bytes that have been hashed and screened but are not yet promoted.

    Immutable, and holding a path rather than the bytes: the staging file
    *is* the value, so a promotion is a rename rather than a second
    write, and a caller cannot mutate the content between the screen and
    the promote.
    """

    staging_id: str
    path: Path
    digest: str
    byte_length: int
    role: ArtifactRole
    media_type: str
    schema_ref: str
    trust_class: TrustClass
    data_class: DataClass
    retention_policy_ref: RetentionPolicyRef
    principal_key_id: str
    source_artifact_ids: tuple[str, ...]

    @property
    def artifact_id(self) -> str:
        return f"artifact:{self.digest}"


def _is_text(media_type: str) -> bool:
    lowered = media_type.split(";", 1)[0].strip().lower()
    return any(lowered.startswith(prefix) for prefix in _TEXT_MEDIA_PREFIXES)


def _screen_text(body: str) -> None:
    """Refuse a body that may not be stored, naming the rule it broke."""
    for pattern in _SIGNED_URL_PATTERNS:
        if pattern.search(body):
            raise ArtifactRefused(
                "artifact body contains an expiring signed URL; "
                "store a stable locator or the bytes themselves"
            )
    for pattern in _SECRET_PATTERNS:
        if pattern.search(body):
            raise ArtifactRefused(
                "artifact body contains credential-shaped content; "
                "it is refused rather than redacted and is not persisted"
            )
    for pattern in _PRIVATE_REASONING_PATTERNS:
        if pattern.search(body):
            raise ArtifactRefused(
                "artifact body contains raw private reasoning; RFC 10 "
                "§10.1 excludes it from events and artifacts alike"
            )


class LocalArtifactStore:
    """A content-addressed store on the local filesystem.

    Thread-safe by one coarse lock.  The operations are a hash, a rename
    and a small JSON write, so the lock is never held across anything
    slow, and the alternative — per-digest locks over a directory tree —
    would buy nothing measurable while making the promote/dedup race
    genuinely hard to reason about.

    Args:
        root: Directory the store owns.  Created if absent.  Two
            subtrees live under it: `staging/` for unpromoted bytes and
            `cas/sha256/<aa>/<bb>/<hex>` for promoted ones, with the
            reference records under `refs/`.
        scope_data_class: The run's own data class.  An artifact may
            never be promoted *below* it — that is the data-class
            downgrade RFC 10 forbids, and it is checked here rather than
            only at append time so the bytes never land at all.
        retention_hook: Notified on each newly promoted artifact.  The
            default records ids and does nothing else.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        scope_data_class: DataClass = DataClass.INTERNAL,
        retention_hook: RetentionHook | None = None,
    ) -> None:
        self._root = Path(root)
        self._staging = self._root / "staging"
        self._cas = self._root / "cas" / "sha256"
        self._refs = self._root / "refs"
        for directory in (self._staging, self._cas, self._refs):
            directory.mkdir(parents=True, exist_ok=True)
        self._scope_data_class = scope_data_class
        self._retention = retention_hook if retention_hook is not None else NullRetentionHook()
        self._lock = threading.RLock()
        self._promoted = 0
        self._deduplicated = 0

    # -- counters --------------------------------------------------------

    @property
    def promoted_count(self) -> int:
        """Artifacts whose bytes this store actually wrote."""
        return self._promoted

    @property
    def deduplicated_count(self) -> int:
        """Promotions satisfied by bytes the store already held."""
        return self._deduplicated

    @property
    def root(self) -> Path:
        return self._root

    # -- staging ---------------------------------------------------------

    def stage(
        self,
        content: bytes,
        *,
        role: ArtifactRole,
        media_type: str,
        schema_ref: str,
        trust_class: TrustClass,
        data_class: DataClass,
        retention_policy_ref: RetentionPolicyRef,
        principal_key_id: str,
        declared_digest: str | None = None,
        declared_byte_length: int | None = None,
        source_artifact_ids: Sequence[str] = (),
    ) -> StagedArtifact:
        """Hash and screen bytes into the staging namespace.

        `declared_digest` and `declared_byte_length` are the producer's
        claim about its own content.  Supplying them is optional;
        supplying a wrong one is fatal, which is the point — a producer
        that computed a digest over one buffer and handed over another
        has a bug the store can see and the reader never could.

        Raises:
            ArtifactIntegrityError: The declaration and the bytes
                disagree, or the content exceeds `MAX_ARTIFACT_BYTES`.
            ArtifactRefused: The content or classification is not
                storable.
        """
        if not _PRINCIPAL_RE.fullmatch(principal_key_id):
            raise ArtifactRefused(
                "principal must be a hashed key id or a declared synthetic principal"
            )
        byte_length = len(content)
        if byte_length > MAX_ARTIFACT_BYTES:
            raise ArtifactIntegrityError(
                f"artifact of {byte_length} bytes exceeds the {MAX_ARTIFACT_BYTES}-byte ceiling"
            )
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if declared_digest is not None and declared_digest != digest:
            raise ArtifactIntegrityError(
                f"declared digest {declared_digest} does not match the staged bytes"
            )
        if declared_byte_length is not None and declared_byte_length != byte_length:
            raise ArtifactIntegrityError(
                f"declared byte length {declared_byte_length} does not match "
                f"the staged {byte_length} bytes"
            )
        if data_class < self._scope_data_class:
            raise ArtifactRefused(
                f"artifact data class {data_class.value} downgrades the run's "
                f"{self._scope_data_class.value} classification"
            )
        if _is_text(media_type):
            try:
                body = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ArtifactIntegrityError(
                    f"{media_type} artifact is not valid UTF-8"
                ) from exc
            _screen_text(body)
        sources = tuple(source_artifact_ids)
        if len(set(sources)) != len(sources):
            raise ArtifactRefused("source artifact ids must be unique")
        self._check_source_classes(sources, data_class)

        staging_id = uuid.uuid4().hex
        path = self._staging / f"{staging_id}.part"
        path.write_bytes(content)
        return StagedArtifact(
            staging_id=staging_id,
            path=path,
            digest=digest,
            byte_length=byte_length,
            role=role,
            media_type=media_type,
            schema_ref=schema_ref,
            trust_class=trust_class,
            data_class=data_class,
            retention_policy_ref=retention_policy_ref,
            principal_key_id=principal_key_id,
            source_artifact_ids=sources,
        )

    def _check_source_classes(
        self, sources: Iterable[str], data_class: DataClass
    ) -> None:
        """A derived artifact may not be less restricted than its inputs."""
        for source_id in sources:
            record = self._read_ref(source_id)
            if record is None:
                raise ArtifactRefused(
                    f"source artifact {source_id} is not held by this store"
                )
            source_class = DataClass(record["data_class"])
            if data_class < source_class:
                raise ArtifactRefused(
                    f"derived artifact downgrades {source_id} from "
                    f"{source_class.value} to {data_class.value}"
                )

    def discard(self, staged: StagedArtifact) -> None:
        """Remove staged bytes that will never be promoted."""
        staged.path.unlink(missing_ok=True)

    # -- promotion -------------------------------------------------------

    def promote(self, staged: StagedArtifact) -> ArtifactRef:
        """Verify the staged bytes once more and publish them.

        The re-verification is not paranoia about this process: staging
        is a namespace a slow upload writes to *before* the event
        transaction that references it (RFC 10 §11.3), so between stage
        and promote the bytes have been at rest on a filesystem.  Hashing
        them again is what makes "everything under `cas/` has been
        verified" a true statement rather than an assumption.

        Returns:
            The `ArtifactRef` an event may carry.  Identical, field for
            field, whether the bytes were new or already held.

        Raises:
            ArtifactIntegrityError: The staged file is missing or its
                bytes no longer hash to the staged digest.
        """
        with self._lock:
            if not staged.path.exists():
                raise ArtifactIntegrityError(
                    f"staged artifact {staged.staging_id} is missing from staging"
                )
            content = staged.path.read_bytes()
            actual = "sha256:" + hashlib.sha256(content).hexdigest()
            if actual != staged.digest or len(content) != staged.byte_length:
                staged.path.unlink(missing_ok=True)
                raise ArtifactIntegrityError(
                    "staged artifact changed between staging and promotion"
                )
            ref = self._build_ref(staged)
            target = self._object_path(staged.digest)
            if target.exists():
                self._deduplicated += 1
                staged.path.unlink(missing_ok=True)
                log.info(
                    "trajectory_artifact_deduplicated",
                    extra={
                        "artifact_id": ref.artifact_id,
                        "artifact_role": ref.role.value,
                        "byte_length": ref.byte_length,
                    },
                )
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged.path), str(target))
                os.chmod(target, 0o600)
                self._promoted += 1
            self._record_ref(ref, principal_key_id=staged.principal_key_id)
            self._retention.on_promoted(ref, principal_key_id=staged.principal_key_id)
            return ref

    def put(
        self,
        content: bytes,
        *,
        role: ArtifactRole,
        media_type: str,
        schema_ref: str,
        trust_class: TrustClass,
        data_class: DataClass,
        retention_policy_ref: RetentionPolicyRef,
        principal_key_id: str,
        declared_digest: str | None = None,
        declared_byte_length: int | None = None,
        source_artifact_ids: Sequence[str] = (),
    ) -> ArtifactRef:
        """Stage and promote in one call, discarding staging on refusal."""
        staged = self.stage(
            content,
            role=role,
            media_type=media_type,
            schema_ref=schema_ref,
            trust_class=trust_class,
            data_class=data_class,
            retention_policy_ref=retention_policy_ref,
            principal_key_id=principal_key_id,
            declared_digest=declared_digest,
            declared_byte_length=declared_byte_length,
            source_artifact_ids=source_artifact_ids,
        )
        try:
            return self.promote(staged)
        except BaseException:
            self.discard(staged)
            raise

    def _build_ref(self, staged: StagedArtifact) -> ArtifactRef:
        suffix = staged.digest.removeprefix("sha256:")
        return ArtifactRef(
            artifact_id=f"artifact:{staged.digest}",
            role=staged.role,
            digest=staged.digest,
            media_type=staged.media_type,
            byte_length=staged.byte_length,
            schema_ref=staged.schema_ref,
            storage_uri=f"cas://sha256/{suffix}",
            trust_class=staged.trust_class,
            data_class=staged.data_class,
            retention_policy_ref=staged.retention_policy_ref,
            source_artifact_ids=staged.source_artifact_ids,
        )

    # -- reading ---------------------------------------------------------

    def read(self, artifact_id: str, *, principal_key_id: str) -> bytes:
        """Return an artifact's bytes, verifying integrity and scope.

        The digest is recomputed on every read, which RFC 10 §7.1 rule 3
        requires and §12.2 explains: a corrupt object must be reported,
        never silently returned or silently skipped.

        Raises:
            ArtifactNotFound: No such artifact.
            ArtifactAccessDenied: The artifact is principal-scoped and
                this is not its principal.
            ArtifactIntegrityError: The stored bytes no longer match.
        """
        with self._lock:
            record = self._require_ref(artifact_id)
            self._authorize(record, principal_key_id)
            path = self._object_path(record["digest"])
            if not path.exists():
                raise ArtifactNotFound(f"artifact bytes for {artifact_id} are unavailable")
            content = path.read_bytes()
            actual = "sha256:" + hashlib.sha256(content).hexdigest()
            if actual != record["digest"] or len(content) != int(record["byte_length"]):
                raise ArtifactIntegrityError(
                    f"stored artifact {artifact_id} failed its read-time integrity check"
                )
            return content

    def ref(self, artifact_id: str, *, principal_key_id: str) -> ArtifactRef:
        """The stored reference, subject to the same scope check as `read`."""
        with self._lock:
            record = self._require_ref(artifact_id)
            self._authorize(record, principal_key_id)
            return ArtifactRef.model_validate_json(record["ref"])

    def contains(self, artifact_id: str) -> bool:
        """Whether the store holds this artifact, ignoring scope.

        Membership is not content: a caller who already knows the digest
        learns nothing from the answer, and `read` still refuses.
        """
        with self._lock:
            return self._read_ref(artifact_id) is not None

    def principals(self, artifact_id: str) -> tuple[str, ...]:
        """Principals that have promoted these exact bytes."""
        with self._lock:
            record = self._require_ref(artifact_id)
            return tuple(record["principals"])

    def expires_at(self, artifact_id: str) -> str | None:
        """Ask the retention hook when this artifact would expire."""
        with self._lock:
            record = self._require_ref(artifact_id)
            return self._retention.expires_at(
                ArtifactRef.model_validate_json(record["ref"])
            )

    # -- reference records ----------------------------------------------

    def _authorize(self, record: _RefRecord, principal_key_id: str) -> None:
        data_class = DataClass(record["data_class"])
        if data_class not in _PRINCIPAL_SCOPED:
            return
        if principal_key_id not in record["principals"]:
            # Logged and counted here rather than at the call site,
            # because a refused read is an operational fact whichever
            # caller made it, and a store that raised silently would put
            # the burden of noticing on every reader in turn.  The line
            # carries the artifact id and its class and nothing else: the
            # requesting principal is exactly what must not be widened
            # into a metric label or a searchable field.
            record_trajectory_fault(stage="artifact_access", error_type="forbidden")
            log.warning(
                "trajectory_artifact_access_denied",
                extra={
                    "artifact_id": str(record["artifact_id"]),
                    "data_class": data_class.value,
                    "error_type": "forbidden",
                },
            )
            raise ArtifactAccessDenied(
                f"{data_class.value} artifact is scoped to another principal; "
                "possessing the content hash grants no access"
            )

    def _ref_path(self, artifact_id: str) -> Path:
        suffix = artifact_id.removeprefix("artifact:sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", suffix):
            raise ArtifactNotFound(f"{artifact_id!r} is not a content-addressed id")
        return self._refs / f"{suffix}.json"

    def _object_path(self, digest: str) -> Path:
        suffix = digest.removeprefix("sha256:")
        return self._cas / suffix[:2] / suffix[2:4] / suffix

    def _read_ref(self, artifact_id: str) -> _RefRecord | None:
        path = self._ref_path(artifact_id)
        if not path.exists():
            return None
        loaded: _RefRecord = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def _require_ref(self, artifact_id: str) -> _RefRecord:
        record = self._read_ref(artifact_id)
        if record is None:
            raise ArtifactNotFound(f"no artifact {artifact_id} in this store")
        return record

    def _record_ref(self, ref: ArtifactRef, *, principal_key_id: str) -> None:
        """Write or extend the scope record for one artifact.

        Extending rather than replacing is what makes deduplication safe
        across principals: two learners whose sessions produced
        byte-identical summaries share one object and each stays on its
        own access list, and neither gains a read of anything it did not
        already hold.
        """
        path = self._ref_path(ref.artifact_id)
        existing = self._read_ref(ref.artifact_id)
        principals: list[str] = list(existing["principals"]) if existing else []
        if principal_key_id not in principals:
            principals.append(principal_key_id)
        if existing is not None:
            stored = ArtifactRef.model_validate_json(existing["ref"])
            if stored.data_class != ref.data_class:
                # Same bytes, different classification: keep the stricter
                # one.  A downgrade must never be reachable by restaging
                # content that is already held at a higher class.
                ref = ref.model_copy(
                    update={
                        "data_class": DataClass.most_restrictive(
                            stored.data_class, ref.data_class
                        )
                    }
                )
        path.write_text(
            json.dumps(
                {
                    "artifact_id": ref.artifact_id,
                    "digest": ref.digest,
                    "byte_length": ref.byte_length,
                    "data_class": ref.data_class.value,
                    "principals": sorted(principals),
                    "ref": ref.model_dump_json(),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )


__all__ = [
    "MAX_ARTIFACT_BYTES",
    "ArtifactAccessDenied",
    "ArtifactIntegrityError",
    "ArtifactNotFound",
    "ArtifactRefused",
    "ArtifactStoreError",
    "LocalArtifactStore",
    "NullRetentionHook",
    "RetentionHook",
    "StagedArtifact",
]
