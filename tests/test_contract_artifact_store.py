"""No-cost qualification for the local content-addressed artifact store (P0-WO08).

The store's job is to be the place bodies go so events can stay bounded,
and every assertion here is about one of the four ways that job can be
done badly: storing bytes that do not match their claimed digest, storing
content that must never be persisted at all, letting a global content
hash become a cross-principal read, or letting a derived artifact be
classified below what it was derived from.

Nothing here touches a network, a provider or a model. The store is a
directory.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.contracts.artifact_store import (
    MAX_ARTIFACT_BYTES,
    ArtifactAccessDenied,
    ArtifactIntegrityError,
    ArtifactNotFound,
    ArtifactRefused,
    LocalArtifactStore,
    NullRetentionHook,
)
from src.contracts.kernel import DataClass
from src.contracts.research_binding import retention_policy_ref
from src.contracts.trajectory import ArtifactRole, TrustClass

pytestmark = [pytest.mark.unit, pytest.mark.contract]

ALICE = "pk_alicealicealice"
BOB = "pk_bobbobbobbobbob"


def store(tmp_path: Path, data_class: DataClass = DataClass.INTERNAL) -> LocalArtifactStore:
    return LocalArtifactStore(tmp_path / "cas-root", scope_data_class=data_class)


def put(
    subject: LocalArtifactStore,
    body: bytes,
    *,
    principal: str = ALICE,
    data_class: DataClass = DataClass.INTERNAL,
    role: ArtifactRole = ArtifactRole.SOURCE_SPAN,
    media_type: str = "text/plain",
    **extra: object,
) -> object:
    return subject.put(
        body,
        role=role,
        media_type=media_type,
        schema_ref="source-span/1.0.0",
        trust_class=TrustClass.SYSTEM_GENERATED,
        data_class=data_class,
        retention_policy_ref=retention_policy_ref(),
        principal_key_id=principal,
        **extra,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


class TestIntegrity:
    def test_a_promoted_artifact_reads_back_byte_for_byte(self, tmp_path: Path) -> None:
        subject = store(tmp_path)
        ref = put(subject, b"an abstract span")
        assert subject.read(ref.artifact_id, principal_key_id=ALICE) == b"an abstract span"  # type: ignore[attr-defined]

    def test_the_reference_carries_its_own_digest_in_every_identity_field(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path)
        body = b"an abstract span"
        ref = put(subject, body)
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        assert ref.digest == digest  # type: ignore[attr-defined]
        assert ref.artifact_id == f"artifact:{digest}"  # type: ignore[attr-defined]
        assert ref.storage_uri == f"cas://sha256/{digest.removeprefix('sha256:')}"  # type: ignore[attr-defined]

    def test_a_wrong_declared_digest_fails_the_stage(self, tmp_path: Path) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactIntegrityError, match="declared digest"):
            put(subject, b"body", declared_digest="sha256:" + "0" * 64)

    def test_a_wrong_declared_byte_length_fails_the_stage(self, tmp_path: Path) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactIntegrityError, match="byte length"):
            put(subject, b"body", declared_byte_length=999)

    def test_a_failed_declaration_leaves_nothing_in_the_store(
        self, tmp_path: Path
    ) -> None:
        """The property that makes `cas/` trustworthy: refusals leave no bytes."""
        subject = store(tmp_path)
        with pytest.raises(ArtifactIntegrityError):
            put(subject, b"body", declared_byte_length=999)
        assert subject.promoted_count == 0
        assert [p for p in (subject.root / "cas").rglob("*") if p.is_file()] == []
        assert list((subject.root / "staging").glob("*.part")) == []

    def test_an_oversized_artifact_is_refused_by_length(self, tmp_path: Path) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactIntegrityError, match="ceiling"):
            put(subject, b"x" * (MAX_ARTIFACT_BYTES + 1))

    def test_a_corrupted_object_fails_its_read_time_check(self, tmp_path: Path) -> None:
        """RFC 10 §12.2: a corrupt row is reported, never silently returned."""
        subject = store(tmp_path)
        ref = put(subject, b"an abstract span")
        suffix = ref.digest.removeprefix("sha256:")  # type: ignore[attr-defined]
        (subject.root / "cas" / "sha256" / suffix[:2] / suffix[2:4] / suffix).write_bytes(
            b"tampered"
        )
        with pytest.raises(ArtifactIntegrityError, match="read-time integrity"):
            subject.read(ref.artifact_id, principal_key_id=ALICE)  # type: ignore[attr-defined]

    def test_a_promotion_whose_staged_bytes_changed_is_refused(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path)
        staged = subject.stage(
            b"an abstract span",
            role=ArtifactRole.SOURCE_SPAN,
            media_type="text/plain",
            schema_ref="source-span/1.0.0",
            trust_class=TrustClass.SYSTEM_GENERATED,
            data_class=DataClass.INTERNAL,
            retention_policy_ref=retention_policy_ref(),
            principal_key_id=ALICE,
        )
        staged.path.write_bytes(b"different bytes entirely")
        with pytest.raises(ArtifactIntegrityError, match="changed between staging"):
            subject.promote(staged)

    def test_an_unknown_artifact_is_not_found_rather_than_empty(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactNotFound):
            subject.read("artifact:sha256:" + "a" * 64, principal_key_id=ALICE)

    def test_a_malformed_id_is_rejected_before_it_reaches_the_filesystem(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactNotFound, match="content-addressed id"):
            subject.read("artifact:sha256:../../etc/passwd", principal_key_id=ALICE)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    @pytest.mark.parametrize(
        "body",
        [
            b"see https://bucket.s3.amazonaws.com/p.pdf?X-Amz-Signature=deadbeefcafe",
            b"https://store.example/x?GoogleAccessId=svc@p.iam&Expires=1&Signature=abcdefgh",
            b"https://cdn.example/f?sas=1&token=abcdefghijklmnopqrstuvwxyz",
        ],
    )
    def test_a_signed_url_in_the_body_is_refused(
        self, tmp_path: Path, body: bytes
    ) -> None:
        """A presigned URL in an evidence record is a credential in content."""
        subject = store(tmp_path)
        with pytest.raises(ArtifactRefused, match="signed URL"):
            put(subject, body)

    @pytest.mark.parametrize(
        "body",
        [
            b"key sk-abcdefghijklmnopqrstuvwx here",
            b"AKIAIOSFODNN7EXAMPLE",
            b"Authorization: Bearer abcdefghijklmnop",
            b"-----BEGIN PRIVATE KEY-----",
            b"api_key = hunter2hunter2",
        ],
    )
    def test_credential_shaped_content_is_refused_not_redacted(
        self, tmp_path: Path, body: bytes
    ) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactRefused, match="credential-shaped"):
            put(subject, body)

    @pytest.mark.parametrize(
        "body",
        [
            b"<thinking>the user probably means...</thinking>",
            b"<scratchpad>step 1</scratchpad>",
            b"chain-of-thought: first I considered",
            b'{"reasoning_content": "..."}',
        ],
    )
    def test_raw_private_reasoning_is_refused(
        self, tmp_path: Path, body: bytes
    ) -> None:
        """RFC 10 §10.1 excludes it from events; §7.1 must not be the loophole."""
        subject = store(tmp_path)
        with pytest.raises(ArtifactRefused, match="private reasoning"):
            put(subject, body)

    def test_a_refused_body_is_never_persisted_for_debugging(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactRefused):
            put(subject, b"key sk-abcdefghijklmnopqrstuvwx here")
        remaining = [
            path
            for path in subject.root.rglob("*")
            if path.is_file()
        ]
        assert remaining == []

    def test_a_binary_body_is_not_screened_as_text(self, tmp_path: Path) -> None:
        """A byte run that looks like a key inside a PDF is not a key."""
        subject = store(tmp_path)
        ref = put(
            subject,
            b"%PDF-1.4\x00sk-abcdefghijklmnopqrstuvwx\x00",
            media_type="application/pdf",
            role=ArtifactRole.SOURCE_DOCUMENT,
        )
        assert subject.contains(ref.artifact_id)  # type: ignore[attr-defined]

    def test_non_utf8_text_is_an_integrity_failure_not_a_silent_store(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactIntegrityError, match="not valid UTF-8"):
            put(subject, b"\xff\xfe not utf-8")

    def test_an_unhashed_principal_is_refused(self, tmp_path: Path) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactRefused, match="principal"):
            put(subject, b"body", principal="user@example.com")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_an_artifact_below_the_run_class_is_refused(self, tmp_path: Path) -> None:
        subject = store(tmp_path, DataClass.USER_CONFIDENTIAL)
        with pytest.raises(ArtifactRefused, match="downgrades"):
            put(subject, b"body", data_class=DataClass.INTERNAL)

    def test_an_artifact_at_or_above_the_run_class_is_accepted(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path, DataClass.USER_CONFIDENTIAL)
        ref = put(
            subject,
            b"body",
            data_class=DataClass.LEARNER_SENSITIVE,
            principal=ALICE,
        )
        assert subject.contains(ref.artifact_id)  # type: ignore[attr-defined]

    def test_a_derived_artifact_cannot_be_classified_below_its_source(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path, DataClass.INTERNAL)
        source = put(
            subject,
            b"confidential source",
            data_class=DataClass.USER_CONFIDENTIAL,
        )
        with pytest.raises(ArtifactRefused, match="downgrades"):
            put(
                subject,
                b"derived summary",
                data_class=DataClass.INTERNAL,
                source_artifact_ids=(source.artifact_id,),  # type: ignore[attr-defined]
            )

    def test_a_source_the_store_does_not_hold_is_refused(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path)
        with pytest.raises(ArtifactRefused, match="not held by this store"):
            put(
                subject,
                b"derived",
                source_artifact_ids=("artifact:sha256:" + "e" * 64,),
            )

    def test_duplicate_source_ids_are_refused(self, tmp_path: Path) -> None:
        subject = store(tmp_path)
        source = put(subject, b"source")
        with pytest.raises(ArtifactRefused, match="unique"):
            put(
                subject,
                b"derived",
                source_artifact_ids=(
                    source.artifact_id,  # type: ignore[attr-defined]
                    source.artifact_id,  # type: ignore[attr-defined]
                ),
            )

    def test_restaging_at_a_lower_class_does_not_downgrade_the_record(
        self, tmp_path: Path
    ) -> None:
        """Deduplication must not become a downgrade path."""
        subject = store(tmp_path, DataClass.PUBLIC)
        body = b"the very same bytes"
        put(subject, body, data_class=DataClass.USER_CONFIDENTIAL, principal=ALICE)
        ref = put(subject, body, data_class=DataClass.PUBLIC, principal=BOB)
        stored = subject.ref(ref.artifact_id, principal_key_id=BOB)  # type: ignore[attr-defined]
        assert stored.data_class is DataClass.USER_CONFIDENTIAL


# ---------------------------------------------------------------------------
# Deduplication and principal scope
# ---------------------------------------------------------------------------


class TestDeduplicationAndScope:
    def test_identical_bytes_promote_once(self, tmp_path: Path) -> None:
        subject = store(tmp_path)
        first = put(subject, b"the very same bytes")
        second = put(subject, b"the very same bytes")
        assert first.artifact_id == second.artifact_id  # type: ignore[attr-defined]
        assert subject.promoted_count == 1
        assert subject.deduplicated_count == 1

    def test_deduplication_produces_a_field_identical_reference(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path)
        first = put(subject, b"the very same bytes")
        second = put(subject, b"the very same bytes")
        assert first.model_dump() == second.model_dump()  # type: ignore[attr-defined]

    def test_a_content_hash_is_not_a_cross_principal_read(
        self, tmp_path: Path
    ) -> None:
        """Zero tolerance: RFC 10 §10.2, "global content hashes do not grant access"."""
        subject = store(tmp_path, DataClass.USER_CONFIDENTIAL)
        ref = put(subject, b"alice's report", data_class=DataClass.USER_CONFIDENTIAL)
        with pytest.raises(ArtifactAccessDenied, match="another principal"):
            subject.read(ref.artifact_id, principal_key_id=BOB)  # type: ignore[attr-defined]

    def test_the_reference_read_is_scoped_exactly_like_the_byte_read(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path, DataClass.LEARNER_SENSITIVE)
        ref = put(subject, b"a learner summary", data_class=DataClass.LEARNER_SENSITIVE)
        with pytest.raises(ArtifactAccessDenied):
            subject.ref(ref.artifact_id, principal_key_id=BOB)  # type: ignore[attr-defined]
        assert subject.ref(ref.artifact_id, principal_key_id=ALICE) is not None  # type: ignore[attr-defined]

    def test_internal_content_is_readable_by_any_authenticated_principal(
        self, tmp_path: Path
    ) -> None:
        """System-generated internal content is not principal-scoped."""
        subject = store(tmp_path)
        ref = put(subject, b"a plan", data_class=DataClass.INTERNAL)
        assert subject.read(ref.artifact_id, principal_key_id=BOB) == b"a plan"  # type: ignore[attr-defined]

    def test_dedup_across_principals_grants_neither_the_other_s_access(
        self, tmp_path: Path
    ) -> None:
        """B promoting the same bytes learns nothing it did not already hold."""
        subject = store(tmp_path, DataClass.USER_CONFIDENTIAL)
        body = b"a byte-identical summary"
        ref = put(subject, body, data_class=DataClass.USER_CONFIDENTIAL, principal=ALICE)
        put(subject, body, data_class=DataClass.USER_CONFIDENTIAL, principal=BOB)
        assert subject.principals(ref.artifact_id) == (ALICE, BOB)  # type: ignore[attr-defined]
        assert subject.promoted_count == 1
        third = "pk_carolcarolcarol"
        with pytest.raises(ArtifactAccessDenied):
            subject.read(ref.artifact_id, principal_key_id=third)  # type: ignore[attr-defined]

    def test_a_refused_read_is_logged_where_the_store_can_see_it(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A refusal every reader would otherwise have to notice for itself."""
        subject = store(tmp_path, DataClass.USER_CONFIDENTIAL)
        ref = put(subject, b"alice's report", data_class=DataClass.USER_CONFIDENTIAL)
        with caplog.at_level("WARNING"), pytest.raises(ArtifactAccessDenied):
            subject.read(ref.artifact_id, principal_key_id=BOB)  # type: ignore[attr-defined]
        denied = [
            record
            for record in caplog.records
            if record.message == "trajectory_artifact_access_denied"
        ]
        assert len(denied) == 1
        assert denied[0].error_type == "forbidden"
        assert not hasattr(denied[0], "principal_key_id")

    def test_a_deduplicated_promotion_says_so(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        subject = store(tmp_path)
        put(subject, b"the very same bytes")
        with caplog.at_level("INFO"):
            put(subject, b"the very same bytes")
        assert [
            record.message
            for record in caplog.records
            if record.message == "trajectory_artifact_deduplicated"
        ] == ["trajectory_artifact_deduplicated"]

    def test_both_artifact_event_names_are_registered(self) -> None:
        from src.observability.logging import KNOWN_EVENTS

        assert {
            "trajectory_artifact_access_denied",
            "trajectory_artifact_deduplicated",
            "trajectory_artifact_promoted",
            "trajectory_artifact_rejected",
        } <= KNOWN_EVENTS

    def test_membership_is_answerable_without_granting_a_read(
        self, tmp_path: Path
    ) -> None:
        subject = store(tmp_path, DataClass.USER_CONFIDENTIAL)
        ref = put(subject, b"alice's report", data_class=DataClass.USER_CONFIDENTIAL)
        assert subject.contains(ref.artifact_id) is True  # type: ignore[attr-defined]
        with pytest.raises(ArtifactAccessDenied):
            subject.read(ref.artifact_id, principal_key_id=BOB)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


class TestRetention:
    def test_the_hook_sees_every_newly_promoted_artifact(self, tmp_path: Path) -> None:
        hook = NullRetentionHook()
        subject = LocalArtifactStore(tmp_path / "root", retention_hook=hook)
        ref = put(subject, b"a plan")
        assert hook.seen == [ref.artifact_id]  # type: ignore[attr-defined]

    def test_the_default_hook_expires_nothing(self, tmp_path: Path) -> None:
        """Until D8 rules, "when does this expire" has one honest answer."""
        subject = store(tmp_path)
        ref = put(subject, b"a plan")
        assert subject.expires_at(ref.artifact_id) is None  # type: ignore[attr-defined]

    def test_the_store_exposes_no_deleter(self, tmp_path: Path) -> None:
        subject = store(tmp_path)
        assert not [name for name in dir(subject) if "delete" in name or "purge" in name]
