"""Create the frozen M1A-003B PostgreSQL snapshot metadata schema."""

# ruff: noqa: E501  # Frozen CHECK SQL literals must remain exact.

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

SCHEMA = "medevidence"

EXPECTED_CHECK_NAMES = (
    "ck_artifact_hashes",
    "ck_artifact_kind_partition",
    "ck_artifact_size",
    "ck_artifact_media_schema",
    "ck_artifact_path",
    "ck_source_snapshot_identity",
    "ck_source_snapshot_static_values",
    "ck_source_snapshot_outcome",
    "ck_source_snapshot_counts",
    "ck_source_snapshot_times",
    "ck_snapshot_file_ids",
    "ck_snapshot_file_raw_binding",
    "ck_snapshot_file_ordinal",
    "ck_snapshot_file_size_http",
    "ck_snapshot_file_completion",
    "ck_snapshot_file_relative_path",
    "ck_snapshot_file_media",
    "ck_source_snapshot_file_ordinal",
    "ck_snapshot_warning_ordinal",
    "ck_snapshot_warning_code",
    "ck_publication_version_identity",
    "ck_publication_version_status",
    "ck_publication_version_payload",
    "ck_snapshot_publication_identity",
    "ck_artifact_lineage_no_self",
    "ck_artifact_lineage_schema",
    "ck_artifact_lineage_type_shape",
    "ck_research_run_ids",
    "ck_research_run_static",
    "ck_research_run_concepts",
    "ck_research_run_dates",
    "ck_research_run_times",
    "ck_research_run_status",
    "ck_research_run_result",
    "ck_research_run_envelope",
    "ck_research_run_warnings",
    "ck_run_attempt_ids",
    "ck_run_attempt_static",
    "ck_run_attempt_operation",
    "ck_run_attempt_times",
    "ck_run_attempt_outcome",
    "ck_run_attempt_failure",
    "ck_run_attempt_counts",
    "ck_run_attempt_warnings",
    "ck_run_attempt_envelope",
    "ck_research_report_identity",
    "ck_research_report_static",
    "ck_research_report_artifact",
    "ck_research_report_size",
    "ck_research_report_result",
    "ck_integrity_event_hashes",
    "ck_integrity_event_sizes",
    "ck_integrity_event_kind",
    "ck_integrity_event_detail",
    "ck_registration_observation_kind",
    "ck_registration_observation_context",
    "ck_registration_observation_path",
    "ck_registration_observation_hashes",
    "ck_registration_observation_sizes",
    "ck_registration_observation_expected_binding",
    "ck_registration_observation_shape",
    "ck_registration_observation_detail",
)

OUTCOME = """(execution_status, coverage_status, result_status) IN (
 ('succeeded','complete','matches'), ('succeeded','complete','no_match'),
 ('succeeded','partial','matches'), ('succeeded','partial','indeterminate'),
 ('failed','partial','matches'), ('failed','partial','indeterminate'),
 ('failed','unavailable','indeterminate'))"""
UUID4 = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
TOP_KEYS = (
    "schema_version",
    "source_type",
    "pmid",
    "doi",
    "pmcid",
    "title",
    "abstract_sections",
    "canonical_abstract",
    "canonical_abstract_sha256",
    "authors",
    "journal",
    "language",
    "publication_types",
    "publication_date",
    "publication_status",
    "indexing_status",
    "evidence_scope",
    "parse_warnings",
)
STATUS_KEYS = (
    "schema_version",
    "status",
    "status_source",
    "notice_type",
    "relationship",
    "retrieved_as_of",
    "warning_codes",
    "disclosure_text",
    "publication_status_identity",
)
RELATIONSHIP_KEYS = (
    "relationship_type",
    "upstream_relationship_type",
    "related_pmid",
    "notice_id",
    "resolution",
    "content_disposition",
)


def sql_text_array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ",".join(f"'{value}'" for value in values) + "]::text[]"


top = sql_text_array(TOP_KEYS)
status = sql_text_array(STATUS_KEYS)
relationship = sql_text_array(RELATIONSHIP_KEYS)

CHECK_SQL = {
    "ck_artifact_hashes": "artifact_id ~ '^sha256:[0-9a-f]{64}$' AND content_hash ~ '^sha256:[0-9a-f]{64}$' AND artifact_id = content_hash",
    "ck_artifact_kind_partition": "(artifact_kind,source_partition) IN (('pubmed_http_response','pubmed'),('snapshot_manifest','pubmed'),('publication_record','pubmed'),('acquisition_registration_envelope','pubmed'),('run_registration_envelope','global'),('research_report','global'))",
    "ck_artifact_size": "(artifact_kind='pubmed_http_response' AND byte_size BETWEEN 0 AND 5242880) OR (artifact_kind='snapshot_manifest' AND byte_size BETWEEN 1 AND 1048576) OR (artifact_kind='publication_record' AND byte_size BETWEEN 1 AND 31457280) OR (artifact_kind='acquisition_registration_envelope' AND byte_size BETWEEN 1 AND 1048576) OR (artifact_kind='run_registration_envelope' AND byte_size BETWEEN 1 AND 1048576) OR (artifact_kind='research_report' AND byte_size BETWEEN 1 AND 4294967296)",
    "ck_artifact_media_schema": "artifact_schema_version='1.0' AND char_length(btrim(media_type)) BETWEEN 1 AND 128 AND (artifact_kind='pubmed_http_response' OR (artifact_kind IN ('snapshot_manifest','publication_record','acquisition_registration_envelope','run_registration_envelope','research_report') AND media_type='application/json'))",
    "ck_artifact_path": "char_length(relative_storage_path) BETWEEN 1 AND 1024 AND left(relative_storage_path,1)<>'/' AND position(chr(92) IN relative_storage_path)=0 AND relative_storage_path !~ '(^|/)\\.{1,2}(/|$)'",
    "ck_source_snapshot_identity": "snapshot_id ~ '^sha256:[0-9a-f]{64}$' AND acquisition_intent_id ~ '^acquisition-intent:sha256:[0-9a-f]{64}$' AND char_length(request_identity) BETWEEN 1 AND 512 AND snapshot_id=manifest_artifact_id AND manifest_artifact_id=manifest_content_hash",
    "ck_source_snapshot_static_values": "source='pubmed' AND manifest_artifact_kind='snapshot_manifest' AND manifest_source_partition='pubmed' AND connector_name='medevidence.connectors.pubmed' AND connector_version='m1a-002' AND manifest_schema_version='1.0' AND source_record_schema_version='1.0' AND code_revision ~ '^[0-9a-f]{40}$' AND retention_policy_id='M1A-LIVE-RETENTION-v1'",
    "ck_source_snapshot_outcome": OUTCOME,
    "ck_source_snapshot_counts": "((result_status='matches' AND record_count BETWEEN 1 AND 100) OR (result_status='no_match' AND record_count=0) OR (result_status='indeterminate' AND record_count=0)) AND attempts_used BETWEEN 1 AND 2 AND pages_completed BETWEEN 0 AND 1 AND (coverage_status<>'unavailable' OR (record_count=0 AND pages_completed=0)) AND (coverage_status<>'complete' OR (truncated=false AND pages_completed=1))",
    "ck_source_snapshot_times": "completed_at_utc >= started_at_utc",
    "ck_snapshot_file_ids": "link_id ~ '^artifact-link:sha256:[0-9a-f]{64}$' AND acquisition_intent_id ~ '^acquisition-intent:sha256:[0-9a-f]{64}$'",
    "ck_snapshot_file_raw_binding": "raw_artifact_id=raw_content_hash AND raw_artifact_kind='pubmed_http_response' AND raw_source_partition='pubmed'",
    "ck_snapshot_file_ordinal": "ordinal BETWEEN 0 AND 3",
    "ck_snapshot_file_size_http": "byte_size BETWEEN 0 AND 5242880 AND http_status BETWEEN 100 AND 599",
    "ck_snapshot_file_completion": "body_complete=(termination_reason='complete_response') AND termination_reason IN ('complete_response','payload_limit','stream_error','deadline_exceeded')",
    "ck_snapshot_file_relative_path": "relative_storage_path='pubmed/sha256/' || substring(raw_artifact_id FROM 8 FOR 2) || '/' || substring(raw_artifact_id FROM 8) || '.bin'",
    "ck_snapshot_file_media": "char_length(btrim(media_type)) BETWEEN 1 AND 128 AND (content_encoding IS NULL OR char_length(btrim(content_encoding)) BETWEEN 1 AND 128) AND schema_version='1.0'",
    "ck_source_snapshot_file_ordinal": "ordinal BETWEEN 0 AND 3",
    "ck_snapshot_warning_ordinal": "warning_ordinal BETWEEN 0 AND 127",
    "ck_snapshot_warning_code": "warning_code ~ '^[a-z][a-z0-9_]{0,127}$'",
    "ck_publication_version_identity": "source='pubmed' AND pmid ~ '^[1-9][0-9]{0,15}$' AND content_hash ~ '^sha256:[0-9a-f]{64}$' AND publication_artifact_id=publication_artifact_hash AND publication_artifact_hash=content_hash AND publication_artifact_kind='publication_record' AND publication_source_partition='pubmed' AND publication_version_id='pubmed:' || pmid || ':sha256:' || substring(content_hash FROM 8)",
    "ck_publication_version_status": "publication_status_identity ~ '^publication-status:sha256:[0-9a-f]{64}$' AND publication_status IN ('current_or_no_known_notice','corrected','retracted','expression_of_concern','unknown_or_unverified')",
    "ck_snapshot_publication_identity": "publication_ordinal BETWEEN 0 AND 99 AND pmid ~ '^[1-9][0-9]{0,15}$' AND publication_content_hash ~ '^sha256:[0-9a-f]{64}$' AND source='pubmed' AND publication_version_id='pubmed:' || pmid || ':sha256:' || substring(publication_content_hash FROM 8)",
    "ck_artifact_lineage_no_self": "(parent_artifact_id,parent_artifact_kind,parent_source_partition,parent_content_hash)<>(child_artifact_id,child_artifact_kind,child_source_partition,child_content_hash)",
    "ck_artifact_lineage_schema": "schema_version='1.0' AND lineage_ordinal BETWEEN 0 AND 100",
    "ck_artifact_lineage_type_shape": "lineage_type IN ('manifest_to_raw_response','publication_to_manifest','acquisition_envelope_to_manifest','acquisition_envelope_to_raw_response','acquisition_envelope_to_publication','report_to_publication','run_envelope_to_report')",
    "ck_research_run_ids": f"run_id ~ '^run:{UUID4}$' AND run_intent_id ~ '^run-intent:sha256:[0-9a-f]{{64}}$' AND request_id ~ '^request:{UUID4}$' AND scope_id ~ '^scope:sha256:[0-9a-f]{{64}}$' AND report_id ~ '^report:sha256:[0-9a-f]{{64}}$'",
    "ck_research_run_static": "code_revision ~ '^[0-9a-f]{40}$' AND execution_profile_id='M1A_CONSTRAINED_V1' AND catalog_version='m1a-concepts-v1' AND catalog_content_hash='sha256:eaffc3ee01ecd46a134578838b0304474642bf5e4a0c6e87302825d52be7682e' AND source='pubmed' AND char_length(pubmed_query) BETWEEN 1 AND 512",
    "ck_research_run_concepts": "cardinality(drug_concept_ids) BETWEEN 1 AND 4 AND cardinality(adverse_event_concept_ids) BETWEEN 1 AND 4 AND array_position(drug_concept_ids,NULL) IS NULL AND array_position(adverse_event_concept_ids,NULL) IS NULL",
    "ck_research_run_dates": "(start_date IS NULL AND end_date IS NULL) OR (start_date IS NOT NULL AND end_date IS NOT NULL AND start_date<=end_date)",
    "ck_research_run_times": "completed_at_utc >= started_at_utc",
    "ck_research_run_status": "(run_status='completed' AND coverage_status='complete') OR (run_status='degraded' AND coverage_status IN ('partial','unavailable'))",
    "ck_research_run_result": "NOT (coverage_status='complete' AND result_status='indeterminate') AND NOT (result_status='no_match' AND coverage_status<>'complete') AND NOT (coverage_status='unavailable' AND result_status<>'indeterminate')",
    "ck_research_run_envelope": "registration_envelope_id ~ '^registration-envelope:run:sha256:[0-9a-f]{64}$' AND envelope_artifact_id=envelope_content_hash AND envelope_artifact_kind='run_registration_envelope' AND envelope_source_partition='global'",
    "ck_research_run_warnings": "cardinality(warning_codes)<=128 AND array_position(warning_codes,NULL) IS NULL",
    "ck_run_attempt_ids": f"attempt_id ~ '^attempt:{UUID4}$' AND run_id ~ '^run:{UUID4}$' AND acquisition_intent_id ~ '^acquisition-intent:sha256:[0-9a-f]{{64}}$' AND registration_envelope_id ~ '^registration-envelope:acquisition:sha256:[0-9a-f]{{64}}$' AND manifest_id ~ '^sha256:[0-9a-f]{{64}}$'",
    "ck_run_attempt_static": "source='pubmed' AND execution_profile_id='M1A_CONSTRAINED_V1' AND registration_state='ready_for_insert' AND intent_schema_version='1.0' AND envelope_schema_version='1.0' AND char_length(request_identity) BETWEEN 1 AND 1024",
    "ck_run_attempt_operation": "(operation='search' AND acquisition_ordinal=0) OR (operation='fetch' AND acquisition_ordinal BETWEEN 1 AND 100)",
    "ck_run_attempt_times": "completed_at_utc >= started_at_utc",
    "ck_run_attempt_outcome": OUTCOME,
    "ck_run_attempt_failure": "(execution_status='failed')=(failure_code IS NOT NULL AND redacted_detail IS NOT NULL)",
    "ck_run_attempt_counts": "((result_status='matches' AND valid_result_count BETWEEN 1 AND 100) OR (result_status='no_match' AND valid_result_count=0) OR (result_status='indeterminate' AND valid_result_count=0)) AND pages_completed BETWEEN 0 AND 1 AND attempts_used BETWEEN 1 AND 2 AND (coverage_status<>'unavailable' OR (valid_result_count=0 AND pages_completed=0)) AND (coverage_status<>'complete' OR (truncated=false AND pages_completed=1))",
    "ck_run_attempt_warnings": "cardinality(warning_codes)<=128 AND array_position(warning_codes,NULL) IS NULL",
    "ck_run_attempt_envelope": "envelope_artifact_id=envelope_content_hash AND envelope_artifact_kind='acquisition_registration_envelope' AND envelope_source_partition='pubmed'",
    "ck_research_report_identity": f"report_id ~ '^report:sha256:[0-9a-f]{{64}}$' AND run_id ~ '^run:{UUID4}$'",
    "ck_research_report_static": "report_status='draft' AND schema_version='1.0'",
    "ck_research_report_artifact": "report_artifact_id=report_content_hash AND report_artifact_kind='research_report' AND report_source_partition='global' AND report_media_type='application/json'",
    "ck_research_report_size": "report_byte_size BETWEEN 0 AND 4294967296",
    "ck_research_report_result": "NOT (coverage_status='complete' AND result_status='indeterminate') AND NOT (result_status='no_match' AND coverage_status<>'complete') AND NOT (coverage_status='unavailable' AND result_status<>'indeterminate')",
    "ck_integrity_event_hashes": "subject_artifact_id=subject_content_hash AND expected_content_hash ~ '^sha256:[0-9a-f]{64}$' AND observed_content_hash ~ '^sha256:[0-9a-f]{64}$'",
    "ck_integrity_event_sizes": "expected_byte_size>=0 AND observed_byte_size>=0",
    "ck_integrity_event_kind": "event_kind ~ '^[a-z][a-z0-9_]{0,39}$'",
    "ck_integrity_event_detail": "char_length(btrim(redacted_detail)) BETWEEN 1 AND 512",
    "ck_registration_observation_kind": "observation_kind IN ('missing_expected_artifact','corrupt_content','invalid_envelope','unregistered_orphan')",
    "ck_registration_observation_context": "attempt_id IS NULL OR run_id IS NOT NULL",
    "ck_registration_observation_path": "(observed_relative_path IS NULL AND observed_relative_path_hash IS NULL) OR (observed_relative_path IS NOT NULL AND observed_relative_path_hash IS NOT NULL AND observed_relative_path_hash ~ '^sha256:[0-9a-f]{64}$' AND char_length(observed_relative_path) BETWEEN 1 AND 1024 AND left(observed_relative_path,1)<>'/' AND position(chr(92) IN observed_relative_path)=0 AND observed_relative_path !~ '(^|/)\\.{1,2}(/|$)')",
    "ck_registration_observation_hashes": "(expected_artifact_id IS NULL OR expected_artifact_id ~ '^sha256:[0-9a-f]{64}$') AND (expected_content_hash IS NULL OR expected_content_hash ~ '^sha256:[0-9a-f]{64}$') AND (observed_artifact_id IS NULL OR observed_artifact_id ~ '^sha256:[0-9a-f]{64}$') AND (observed_content_hash IS NULL OR observed_content_hash ~ '^sha256:[0-9a-f]{64}$')",
    "ck_registration_observation_sizes": "(expected_byte_size IS NULL OR expected_byte_size>=0) AND (observed_byte_size IS NULL OR observed_byte_size>=0)",
    "ck_registration_observation_expected_binding": "(expected_artifact_id IS NULL AND expected_content_hash IS NULL AND expected_artifact_kind IS NULL AND expected_source_partition IS NULL) OR (expected_artifact_id IS NOT NULL AND expected_content_hash IS NOT NULL AND expected_artifact_kind IS NOT NULL AND expected_source_partition IS NOT NULL AND expected_artifact_id=expected_content_hash AND (expected_artifact_kind,expected_source_partition) IN (('pubmed_http_response','pubmed'),('snapshot_manifest','pubmed'),('publication_record','pubmed'),('acquisition_registration_envelope','pubmed'),('run_registration_envelope','global'),('research_report','global')))",
    "ck_registration_observation_shape": "(observation_kind='missing_expected_artifact' AND observed_relative_path IS NOT NULL AND expected_artifact_id IS NOT NULL AND expected_artifact_kind IS NOT NULL AND expected_source_partition IS NOT NULL AND expected_content_hash IS NOT NULL AND expected_byte_size IS NOT NULL AND expected_envelope_id IS NULL AND observed_artifact_id IS NULL AND observed_envelope_id IS NULL AND observed_content_hash IS NULL AND observed_byte_size IS NULL) OR (observation_kind='corrupt_content' AND observed_relative_path IS NOT NULL AND expected_artifact_id IS NOT NULL AND expected_artifact_kind IS NOT NULL AND expected_source_partition IS NOT NULL AND expected_content_hash IS NOT NULL AND expected_byte_size IS NOT NULL AND observed_artifact_id IS NOT NULL AND observed_content_hash IS NOT NULL AND observed_byte_size IS NOT NULL AND observed_artifact_id=observed_content_hash AND (expected_content_hash<>observed_content_hash OR expected_byte_size<>observed_byte_size) AND expected_envelope_id IS NULL AND observed_envelope_id IS NULL) OR (observation_kind='invalid_envelope' AND observed_relative_path IS NOT NULL AND expected_artifact_id IS NULL AND expected_artifact_kind IS NULL AND expected_source_partition IS NULL AND expected_content_hash IS NULL AND observed_artifact_id IS NULL AND observed_content_hash IS NULL AND expected_byte_size IS NULL AND observed_byte_size IS NULL) OR (observation_kind='unregistered_orphan' AND observed_relative_path IS NOT NULL AND expected_artifact_id IS NULL AND expected_artifact_kind IS NULL AND expected_source_partition IS NULL AND expected_content_hash IS NULL AND expected_envelope_id IS NULL AND observed_content_hash IS NOT NULL AND observed_byte_size IS NOT NULL AND NOT (observed_artifact_id IS NOT NULL AND observed_envelope_id IS NOT NULL) AND (observed_artifact_id IS NULL OR observed_artifact_id=observed_content_hash))",
    "ck_registration_observation_detail": "char_length(btrim(redacted_detail)) BETWEEN 1 AND 512",
}

CHECK_SQL["ck_publication_version_payload"] = f"""
jsonb_typeof(version_payload)='object'
AND version_payload ?& {top}
AND (version_payload - {top})='{{}}'::jsonb
AND jsonb_typeof(version_payload->'schema_version')='string'
AND jsonb_typeof(version_payload->'source_type')='string'
AND jsonb_typeof(version_payload->'pmid')='string'
AND jsonb_typeof(version_payload->'doi') IN ('string','null')
AND jsonb_typeof(version_payload->'pmcid') IN ('string','null')
AND jsonb_typeof(version_payload->'title')='string'
AND jsonb_typeof(version_payload->'abstract_sections')='array'
AND jsonb_typeof(version_payload->'canonical_abstract') IN ('string','null')
AND jsonb_typeof(version_payload->'canonical_abstract_sha256') IN ('string','null')
AND jsonb_typeof(version_payload->'authors')='array'
AND jsonb_typeof(version_payload->'journal')='string'
AND jsonb_typeof(version_payload->'language')='string'
AND jsonb_typeof(version_payload->'publication_types')='array'
AND jsonb_typeof(version_payload->'publication_date') IN ('object','null')
AND jsonb_typeof(version_payload->'publication_status')='object'
AND jsonb_typeof(version_payload->'indexing_status')='string'
AND jsonb_typeof(version_payload->'evidence_scope')='string'
AND jsonb_typeof(version_payload->'parse_warnings')='array'
AND version_payload->>'schema_version'=schema_version
AND version_payload->>'source_type'=source
AND version_payload->>'pmid'=pmid
AND (version_payload->'publication_status') ?& {status}
AND ((version_payload->'publication_status') - {status})='{{}}'::jsonb
AND jsonb_typeof(version_payload#>'{{publication_status,schema_version}}')='string'
AND jsonb_typeof(version_payload#>'{{publication_status,status}}')='string'
AND jsonb_typeof(version_payload#>'{{publication_status,status_source}}')='string'
AND jsonb_typeof(version_payload#>'{{publication_status,notice_type}}') IN ('string','null')
AND jsonb_typeof(version_payload#>'{{publication_status,retrieved_as_of}}')='string'
AND jsonb_typeof(version_payload#>'{{publication_status,warning_codes}}')='array'
AND jsonb_typeof(version_payload#>'{{publication_status,disclosure_text}}')='string'
AND jsonb_typeof(version_payload#>'{{publication_status,publication_status_identity}}')='string'
AND version_payload#>>'{{publication_status,schema_version}}'='1.0'
AND version_payload#>>'{{publication_status,status}}'=publication_status
AND version_payload#>>'{{publication_status,publication_status_identity}}'=publication_status_identity
AND version_payload#>>'{{publication_status,retrieved_as_of}}'=to_char(status_retrieved_at_utc AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
AND ((version_payload#>'{{publication_status,relationship}}')='null'::jsonb OR
 (jsonb_typeof(version_payload#>'{{publication_status,relationship}}')='object'
  AND (version_payload#>'{{publication_status,relationship}}') ?& {relationship}
  AND ((version_payload#>'{{publication_status,relationship}}') - {relationship})='{{}}'::jsonb
  AND jsonb_typeof(version_payload#>'{{publication_status,relationship,relationship_type}}')='string'
  AND jsonb_typeof(version_payload#>'{{publication_status,relationship,upstream_relationship_type}}') IN ('string','null')
  AND jsonb_typeof(version_payload#>'{{publication_status,relationship,related_pmid}}') IN ('string','null')
  AND jsonb_typeof(version_payload#>'{{publication_status,relationship,notice_id}}') IN ('string','null')
  AND jsonb_typeof(version_payload#>'{{publication_status,relationship,resolution}}')='string'
  AND jsonb_typeof(version_payload#>'{{publication_status,relationship,content_disposition}}')='string'))
AND schema_version='1.0'
"""

assert len(CHECK_SQL) == 62


def ck(name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(CHECK_SQL[name], name=name)


def fk(
    local: list[str], remote: list[str], name: str, *, deferred: bool = False
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        local,
        [f"{SCHEMA}.{target}" for target in remote],
        name=name,
        onupdate="RESTRICT",
        ondelete="RESTRICT",
        deferrable=True if deferred else None,
        initially="DEFERRED" if deferred else None,
    )


_metadata = sa.MetaData()

artifact = sa.Table(
    "artifact",
    _metadata,
    sa.Column("artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("artifact_kind", sa.String(40), nullable=False),
    sa.Column("source_partition", sa.String(16), nullable=False),
    sa.Column("content_hash", sa.CHAR(71), nullable=False),
    sa.Column("byte_size", sa.BigInteger(), nullable=False),
    sa.Column("media_type", sa.String(128), nullable=False),
    sa.Column("relative_storage_path", sa.String(1024), nullable=False),
    sa.Column("artifact_schema_version", sa.String(32), nullable=False),
    sa.PrimaryKeyConstraint("artifact_id", name="pk_artifact"),
    sa.UniqueConstraint(
        "artifact_id",
        "artifact_kind",
        "source_partition",
        "content_hash",
        name="uq_artifact_identity",
    ),
    sa.UniqueConstraint("relative_storage_path", name="uq_artifact_path"),
    *(ck(name) for name in EXPECTED_CHECK_NAMES[0:5]),
    schema=SCHEMA,
)

source_snapshot = sa.Table(
    "source_snapshot",
    _metadata,
    sa.Column("snapshot_id", sa.CHAR(71), nullable=False),
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("acquisition_intent_id", sa.String(128), nullable=False),
    sa.Column("request_identity", sa.String(512), nullable=False),
    sa.Column("execution_status", sa.String(16), nullable=False),
    sa.Column("coverage_status", sa.String(16), nullable=False),
    sa.Column("result_status", sa.String(16), nullable=False),
    sa.Column("record_count", sa.SmallInteger(), nullable=False),
    sa.Column("attempts_used", sa.SmallInteger(), nullable=False),
    sa.Column("pages_completed", sa.SmallInteger(), nullable=False),
    sa.Column("truncated", sa.Boolean(), nullable=False),
    sa.Column("manifest_artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("manifest_artifact_kind", sa.String(40), nullable=False),
    sa.Column("manifest_source_partition", sa.String(16), nullable=False),
    sa.Column("manifest_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("connector_name", sa.String(128), nullable=False),
    sa.Column("connector_version", sa.String(64), nullable=False),
    sa.Column("manifest_schema_version", sa.String(16), nullable=False),
    sa.Column("source_record_schema_version", sa.String(16), nullable=False),
    sa.Column("code_revision", sa.CHAR(40), nullable=False),
    sa.Column("retention_policy_id", sa.String(64), nullable=False),
    sa.PrimaryKeyConstraint("snapshot_id", name="pk_source_snapshot"),
    sa.UniqueConstraint("acquisition_intent_id", name="uq_source_snapshot_acquisition"),
    sa.UniqueConstraint("snapshot_id", "acquisition_intent_id", name="uq_source_snapshot_id_acq"),
    fk(
        [
            "manifest_artifact_id",
            "manifest_artifact_kind",
            "manifest_source_partition",
            "manifest_content_hash",
        ],
        [
            "artifact.artifact_id",
            "artifact.artifact_kind",
            "artifact.source_partition",
            "artifact.content_hash",
        ],
        "fk_source_snapshot_manifest_artifact",
    ),
    *(ck(name) for name in EXPECTED_CHECK_NAMES[5:10]),
    schema=SCHEMA,
)

snapshot_file = sa.Table(
    "snapshot_file",
    _metadata,
    sa.Column("link_id", sa.String(128), nullable=False),
    sa.Column("acquisition_intent_id", sa.String(128), nullable=False),
    sa.Column("ordinal", sa.SmallInteger(), nullable=False),
    sa.Column("raw_artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("raw_artifact_kind", sa.String(40), nullable=False),
    sa.Column("raw_source_partition", sa.String(16), nullable=False),
    sa.Column("raw_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("relative_storage_path", sa.String(1024), nullable=False),
    sa.Column("byte_size", sa.BigInteger(), nullable=False),
    sa.Column("media_type", sa.String(128), nullable=False),
    sa.Column("content_encoding", sa.String(128), nullable=True),
    sa.Column("http_status", sa.SmallInteger(), nullable=False),
    sa.Column("body_complete", sa.Boolean(), nullable=False),
    sa.Column("termination_reason", sa.String(32), nullable=False),
    sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("schema_version", sa.String(16), nullable=False),
    sa.PrimaryKeyConstraint("link_id", name="pk_snapshot_file"),
    sa.UniqueConstraint("acquisition_intent_id", "ordinal", name="uq_snapshot_file_acq_ordinal"),
    sa.UniqueConstraint(
        "link_id", "acquisition_intent_id", "ordinal", name="uq_snapshot_file_link_acq_ord"
    ),
    fk(
        ["raw_artifact_id", "raw_artifact_kind", "raw_source_partition", "raw_content_hash"],
        [
            "artifact.artifact_id",
            "artifact.artifact_kind",
            "artifact.source_partition",
            "artifact.content_hash",
        ],
        "fk_snapshot_file_raw_artifact",
    ),
    *(ck(name) for name in EXPECTED_CHECK_NAMES[10:17]),
    schema=SCHEMA,
)

source_snapshot_file = sa.Table(
    "source_snapshot_file",
    _metadata,
    sa.Column("snapshot_id", sa.CHAR(71), nullable=False),
    sa.Column("acquisition_intent_id", sa.String(128), nullable=False),
    sa.Column("ordinal", sa.SmallInteger(), nullable=False),
    sa.Column("link_id", sa.String(128), nullable=False),
    sa.PrimaryKeyConstraint("snapshot_id", "ordinal", name="pk_source_snapshot_file"),
    sa.UniqueConstraint("snapshot_id", "link_id", name="uq_source_snapshot_file_snapshot_link"),
    sa.UniqueConstraint("link_id", name="uq_source_snapshot_file_link"),
    fk(
        ["snapshot_id", "acquisition_intent_id"],
        ["source_snapshot.snapshot_id", "source_snapshot.acquisition_intent_id"],
        "fk_snapshot_member_snapshot",
    ),
    fk(
        ["link_id", "acquisition_intent_id", "ordinal"],
        ["snapshot_file.link_id", "snapshot_file.acquisition_intent_id", "snapshot_file.ordinal"],
        "fk_snapshot_member_file",
    ),
    ck("ck_source_snapshot_file_ordinal"),
    schema=SCHEMA,
)

snapshot_warning = sa.Table(
    "snapshot_warning",
    _metadata,
    sa.Column("snapshot_id", sa.CHAR(71), nullable=False),
    sa.Column("warning_ordinal", sa.SmallInteger(), nullable=False),
    sa.Column("warning_code", sa.String(128), nullable=False),
    sa.PrimaryKeyConstraint("snapshot_id", "warning_ordinal", name="pk_snapshot_warning"),
    sa.UniqueConstraint("snapshot_id", "warning_code", name="uq_snapshot_warning_code"),
    fk(["snapshot_id"], ["source_snapshot.snapshot_id"], "fk_snapshot_warning_snapshot"),
    ck("ck_snapshot_warning_ordinal"),
    ck("ck_snapshot_warning_code"),
    schema=SCHEMA,
)

publication_version = sa.Table(
    "publication_version",
    _metadata,
    sa.Column("publication_version_id", sa.String(128), nullable=False),
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("pmid", sa.String(16), nullable=False),
    sa.Column("content_hash", sa.CHAR(71), nullable=False),
    sa.Column("publication_status_identity", sa.String(128), nullable=False),
    sa.Column("publication_status", sa.String(40), nullable=False),
    sa.Column("status_retrieved_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("version_payload", postgresql.JSONB(), nullable=False),
    sa.Column("publication_artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("publication_artifact_kind", sa.String(40), nullable=False),
    sa.Column("publication_source_partition", sa.String(16), nullable=False),
    sa.Column("publication_artifact_hash", sa.CHAR(71), nullable=False),
    sa.Column("schema_version", sa.String(16), nullable=False),
    sa.PrimaryKeyConstraint("publication_version_id", name="pk_publication_version"),
    sa.UniqueConstraint("source", "pmid", "content_hash", name="uq_publication_version_identity"),
    sa.UniqueConstraint(
        "publication_version_id",
        "source",
        "pmid",
        "content_hash",
        name="uq_publication_version_binding",
    ),
    fk(
        [
            "publication_artifact_id",
            "publication_artifact_kind",
            "publication_source_partition",
            "publication_artifact_hash",
        ],
        [
            "artifact.artifact_id",
            "artifact.artifact_kind",
            "artifact.source_partition",
            "artifact.content_hash",
        ],
        "fk_publication_version_artifact",
    ),
    ck("ck_publication_version_identity"),
    ck("ck_publication_version_status"),
    ck("ck_publication_version_payload"),
    schema=SCHEMA,
)

source_snapshot_publication = sa.Table(
    "source_snapshot_publication",
    _metadata,
    sa.Column("snapshot_id", sa.CHAR(71), nullable=False),
    sa.Column("publication_ordinal", sa.SmallInteger(), nullable=False),
    sa.Column("pmid", sa.String(16), nullable=False),
    sa.Column("publication_version_id", sa.String(128), nullable=False),
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("publication_content_hash", sa.CHAR(71), nullable=False),
    sa.PrimaryKeyConstraint(
        "snapshot_id", "publication_ordinal", name="pk_source_snapshot_publication"
    ),
    sa.UniqueConstraint("snapshot_id", "pmid", name="uq_snapshot_publication_pmid"),
    sa.UniqueConstraint(
        "snapshot_id", "publication_version_id", name="uq_snapshot_publication_version"
    ),
    fk(["snapshot_id"], ["source_snapshot.snapshot_id"], "fk_snapshot_publication_snapshot"),
    fk(
        ["publication_version_id", "source", "pmid", "publication_content_hash"],
        [
            "publication_version.publication_version_id",
            "publication_version.source",
            "publication_version.pmid",
            "publication_version.content_hash",
        ],
        "fk_snapshot_publication_version",
    ),
    ck("ck_snapshot_publication_identity"),
    schema=SCHEMA,
)

artifact_lineage = sa.Table(
    "artifact_lineage",
    _metadata,
    sa.Column("parent_artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("parent_artifact_kind", sa.String(40), nullable=False),
    sa.Column("parent_source_partition", sa.String(16), nullable=False),
    sa.Column("parent_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("child_artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("child_artifact_kind", sa.String(40), nullable=False),
    sa.Column("child_source_partition", sa.String(16), nullable=False),
    sa.Column("child_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("lineage_type", sa.String(64), nullable=False),
    sa.Column("lineage_ordinal", sa.SmallInteger(), nullable=False),
    sa.Column("schema_version", sa.String(16), nullable=False),
    sa.PrimaryKeyConstraint(
        "parent_artifact_id",
        "parent_artifact_kind",
        "parent_source_partition",
        "parent_content_hash",
        "child_artifact_id",
        "child_artifact_kind",
        "child_source_partition",
        "child_content_hash",
        "lineage_type",
        "lineage_ordinal",
        name="pk_artifact_lineage",
    ),
    fk(
        [
            "parent_artifact_id",
            "parent_artifact_kind",
            "parent_source_partition",
            "parent_content_hash",
        ],
        [
            "artifact.artifact_id",
            "artifact.artifact_kind",
            "artifact.source_partition",
            "artifact.content_hash",
        ],
        "fk_lineage_parent_artifact",
    ),
    fk(
        [
            "child_artifact_id",
            "child_artifact_kind",
            "child_source_partition",
            "child_content_hash",
        ],
        [
            "artifact.artifact_id",
            "artifact.artifact_kind",
            "artifact.source_partition",
            "artifact.content_hash",
        ],
        "fk_lineage_child_artifact",
    ),
    ck("ck_artifact_lineage_no_self"),
    ck("ck_artifact_lineage_schema"),
    ck("ck_artifact_lineage_type_shape"),
    schema=SCHEMA,
)

research_run = sa.Table(
    "research_run",
    _metadata,
    sa.Column("run_id", sa.String(128), nullable=False),
    sa.Column("run_intent_id", sa.String(128), nullable=False),
    sa.Column("request_id", sa.String(128), nullable=False),
    sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("code_revision", sa.CHAR(40), nullable=False),
    sa.Column("scope_id", sa.String(128), nullable=False),
    sa.Column("execution_profile_id", sa.String(32), nullable=False),
    sa.Column("catalog_version", sa.String(64), nullable=False),
    sa.Column("catalog_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("drug_concept_ids", postgresql.ARRAY(sa.String(128)), nullable=False),
    sa.Column("adverse_event_concept_ids", postgresql.ARRAY(sa.String(128)), nullable=False),
    sa.Column("start_date", sa.Date(), nullable=True),
    sa.Column("end_date", sa.Date(), nullable=True),
    sa.Column("pubmed_query", sa.String(512), nullable=False),
    sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("run_status", sa.String(16), nullable=False),
    sa.Column("coverage_status", sa.String(16), nullable=False),
    sa.Column("result_status", sa.String(16), nullable=False),
    sa.Column("registration_envelope_id", sa.String(128), nullable=False),
    sa.Column("envelope_artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("envelope_artifact_kind", sa.String(40), nullable=False),
    sa.Column("envelope_source_partition", sa.String(16), nullable=False),
    sa.Column("envelope_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("report_id", sa.String(128), nullable=False),
    sa.Column("warning_codes", postgresql.ARRAY(sa.String(128)), nullable=False),
    sa.PrimaryKeyConstraint("run_id", name="pk_research_run"),
    sa.UniqueConstraint("run_intent_id", name="uq_research_run_intent"),
    sa.UniqueConstraint("request_id", name="uq_research_run_request"),
    fk(
        [
            "envelope_artifact_id",
            "envelope_artifact_kind",
            "envelope_source_partition",
            "envelope_content_hash",
        ],
        [
            "artifact.artifact_id",
            "artifact.artifact_kind",
            "artifact.source_partition",
            "artifact.content_hash",
        ],
        "fk_research_run_envelope_artifact",
    ),
    *(ck(name) for name in EXPECTED_CHECK_NAMES[27:36]),
    schema=SCHEMA,
)

research_run_attempt = sa.Table(
    "research_run_attempt",
    _metadata,
    sa.Column("attempt_id", sa.String(128), nullable=False),
    sa.Column("run_id", sa.String(128), nullable=False),
    sa.Column("acquisition_ordinal", sa.SmallInteger(), nullable=False),
    sa.Column("acquisition_intent_id", sa.String(128), nullable=False),
    sa.Column("registration_envelope_id", sa.String(128), nullable=False),
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("operation", sa.String(16), nullable=False),
    sa.Column("intent_created_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("request_identity", sa.String(1024), nullable=False),
    sa.Column("execution_profile_id", sa.String(32), nullable=False),
    sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("execution_status", sa.String(16), nullable=False),
    sa.Column("coverage_status", sa.String(16), nullable=False),
    sa.Column("result_status", sa.String(16), nullable=False),
    sa.Column("valid_result_count", sa.SmallInteger(), nullable=False),
    sa.Column("pages_completed", sa.SmallInteger(), nullable=False),
    sa.Column("attempts_used", sa.SmallInteger(), nullable=False),
    sa.Column("truncated", sa.Boolean(), nullable=False),
    sa.Column("warning_codes", postgresql.ARRAY(sa.String(128)), nullable=False),
    sa.Column("failure_code", sa.String(64), nullable=True),
    sa.Column("redacted_detail", sa.String(512), nullable=True),
    sa.Column("registration_state", sa.String(32), nullable=False),
    sa.Column("manifest_id", sa.CHAR(71), nullable=False),
    sa.Column("envelope_artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("envelope_artifact_kind", sa.String(40), nullable=False),
    sa.Column("envelope_source_partition", sa.String(16), nullable=False),
    sa.Column("envelope_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("intent_schema_version", sa.String(16), nullable=False),
    sa.Column("envelope_schema_version", sa.String(16), nullable=False),
    sa.PrimaryKeyConstraint("attempt_id", name="pk_research_run_attempt"),
    sa.UniqueConstraint("acquisition_intent_id", name="uq_run_attempt_intent"),
    sa.UniqueConstraint("registration_envelope_id", name="uq_run_attempt_envelope"),
    sa.UniqueConstraint("run_id", "acquisition_ordinal", name="uq_run_attempt_ordinal"),
    fk(
        ["manifest_id", "acquisition_intent_id"],
        ["source_snapshot.snapshot_id", "source_snapshot.acquisition_intent_id"],
        "fk_run_attempt_manifest",
    ),
    fk(
        [
            "envelope_artifact_id",
            "envelope_artifact_kind",
            "envelope_source_partition",
            "envelope_content_hash",
        ],
        [
            "artifact.artifact_id",
            "artifact.artifact_kind",
            "artifact.source_partition",
            "artifact.content_hash",
        ],
        "fk_run_attempt_envelope_artifact",
    ),
    *(ck(name) for name in EXPECTED_CHECK_NAMES[36:45]),
    schema=SCHEMA,
)

research_report = sa.Table(
    "research_report",
    _metadata,
    sa.Column("report_id", sa.String(128), nullable=False),
    sa.Column("run_id", sa.String(128), nullable=False),
    sa.Column("report_status", sa.String(16), nullable=False),
    sa.Column("report_artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("report_artifact_kind", sa.String(40), nullable=False),
    sa.Column("report_source_partition", sa.String(16), nullable=False),
    sa.Column("report_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("report_byte_size", sa.BigInteger(), nullable=False),
    sa.Column("report_media_type", sa.String(128), nullable=False),
    sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.Column("schema_version", sa.String(16), nullable=False),
    sa.Column("coverage_status", sa.String(16), nullable=False),
    sa.Column("result_status", sa.String(16), nullable=False),
    sa.PrimaryKeyConstraint("report_id", name="pk_research_report"),
    sa.UniqueConstraint("run_id", name="uq_research_report_run"),
    sa.UniqueConstraint("report_id", "run_id", name="uq_research_report_id_run"),
    fk(["run_id"], ["research_run.run_id"], "fk_research_report_run"),
    fk(
        [
            "report_artifact_id",
            "report_artifact_kind",
            "report_source_partition",
            "report_content_hash",
        ],
        [
            "artifact.artifact_id",
            "artifact.artifact_kind",
            "artifact.source_partition",
            "artifact.content_hash",
        ],
        "fk_research_report_artifact",
    ),
    *(ck(name) for name in EXPECTED_CHECK_NAMES[45:50]),
    schema=SCHEMA,
)

# Added only after research_report exists; it closes the frozen cycle.
research_run.append_constraint(
    fk(
        ["report_id", "run_id"],
        ["research_report.report_id", "research_report.run_id"],
        "fk_research_run_report",
        deferred=True,
    )
)

artifact_integrity_event = sa.Table(
    "artifact_integrity_event",
    _metadata,
    sa.Column("integrity_event_id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column("event_kind", sa.String(40), nullable=False),
    sa.Column("subject_artifact_id", sa.CHAR(71), nullable=False),
    sa.Column("subject_artifact_kind", sa.String(40), nullable=False),
    sa.Column("subject_source_partition", sa.String(16), nullable=False),
    sa.Column("subject_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("expected_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("observed_content_hash", sa.CHAR(71), nullable=False),
    sa.Column("expected_byte_size", sa.BigInteger(), nullable=False),
    sa.Column("observed_byte_size", sa.BigInteger(), nullable=False),
    sa.Column("redacted_detail", sa.String(512), nullable=False),
    sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("integrity_event_id", name="pk_artifact_integrity_event"),
    sa.UniqueConstraint(
        "subject_artifact_id",
        "subject_artifact_kind",
        "subject_source_partition",
        "subject_content_hash",
        "event_kind",
        "observed_content_hash",
        "observed_byte_size",
        "observed_at_utc",
        name="uq_integrity_event_natural",
    ),
    fk(
        [
            "subject_artifact_id",
            "subject_artifact_kind",
            "subject_source_partition",
            "subject_content_hash",
        ],
        [
            "artifact.artifact_id",
            "artifact.artifact_kind",
            "artifact.source_partition",
            "artifact.content_hash",
        ],
        "fk_integrity_event_artifact",
    ),
    *(ck(name) for name in EXPECTED_CHECK_NAMES[50:54]),
    schema=SCHEMA,
)

registration_observation = sa.Table(
    "registration_observation",
    _metadata,
    sa.Column("observation_id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column("observation_kind", sa.String(40), nullable=False),
    sa.Column("source_partition", sa.String(16), nullable=True),
    sa.Column("run_id", sa.String(128), nullable=True),
    sa.Column("attempt_id", sa.String(128), nullable=True),
    sa.Column("observed_relative_path", sa.String(1024), nullable=True),
    sa.Column("observed_relative_path_hash", sa.CHAR(71), nullable=True),
    sa.Column("expected_artifact_id", sa.CHAR(71), nullable=True),
    sa.Column("expected_artifact_kind", sa.String(40), nullable=True),
    sa.Column("expected_source_partition", sa.String(16), nullable=True),
    sa.Column("expected_content_hash", sa.CHAR(71), nullable=True),
    sa.Column("expected_envelope_id", sa.String(128), nullable=True),
    sa.Column("observed_artifact_id", sa.CHAR(71), nullable=True),
    sa.Column("observed_envelope_id", sa.String(128), nullable=True),
    sa.Column("observed_content_hash", sa.CHAR(71), nullable=True),
    sa.Column("expected_byte_size", sa.BigInteger(), nullable=True),
    sa.Column("observed_byte_size", sa.BigInteger(), nullable=True),
    sa.Column("redacted_detail", sa.String(512), nullable=False),
    sa.Column("observed_at_utc", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("observation_id", name="pk_registration_observation"),
    sa.UniqueConstraint(
        "observation_kind",
        "source_partition",
        "run_id",
        "attempt_id",
        "observed_relative_path_hash",
        "expected_artifact_id",
        "expected_artifact_kind",
        "expected_source_partition",
        "expected_content_hash",
        "expected_envelope_id",
        "observed_artifact_id",
        "observed_envelope_id",
        "observed_content_hash",
        "expected_byte_size",
        "observed_byte_size",
        "observed_at_utc",
        name="uq_registration_observation_natural",
        postgresql_nulls_not_distinct=True,
    ),
    *(ck(name) for name in EXPECTED_CHECK_NAMES[54:62]),
    schema=SCHEMA,
)

sa.Index(
    "ix_artifact_kind_partition", artifact.c.artifact_kind.asc(), artifact.c.source_partition.asc()
)
sa.Index(
    "ix_source_snapshot_completed",
    source_snapshot.c.completed_at_utc.desc(),
    source_snapshot.c.snapshot_id.asc(),
)
sa.Index(
    "ix_snapshot_file_raw_artifact",
    snapshot_file.c.raw_artifact_id.asc(),
    snapshot_file.c.raw_artifact_kind.asc(),
    snapshot_file.c.raw_source_partition.asc(),
    snapshot_file.c.raw_content_hash.asc(),
)
sa.Index(
    "ix_snapshot_warning_code",
    snapshot_warning.c.warning_code.asc(),
    snapshot_warning.c.snapshot_id.asc(),
)
sa.Index(
    "ix_publication_version_pmid_time",
    publication_version.c.source.asc(),
    publication_version.c.pmid.asc(),
    publication_version.c.status_retrieved_at_utc.desc(),
)
sa.Index(
    "ix_snapshot_publication_version",
    source_snapshot_publication.c.publication_version_id.asc(),
    source_snapshot_publication.c.snapshot_id.asc(),
)
sa.Index(
    "ix_artifact_lineage_child",
    artifact_lineage.c.child_artifact_id.asc(),
    artifact_lineage.c.child_artifact_kind.asc(),
    artifact_lineage.c.child_source_partition.asc(),
    artifact_lineage.c.child_content_hash.asc(),
)
sa.Index(
    "ix_research_run_completed", research_run.c.completed_at_utc.desc(), research_run.c.run_id.asc()
)
sa.Index(
    "ix_run_attempt_manifest",
    research_run_attempt.c.manifest_id.asc(),
    research_run_attempt.c.acquisition_intent_id.asc(),
)
sa.Index(
    "ix_research_report_artifact",
    research_report.c.report_artifact_id.asc(),
    research_report.c.report_artifact_kind.asc(),
    research_report.c.report_source_partition.asc(),
    research_report.c.report_content_hash.asc(),
)
sa.Index(
    "ix_integrity_event_subject_time",
    artifact_integrity_event.c.subject_artifact_id.asc(),
    artifact_integrity_event.c.observed_at_utc.desc(),
)
sa.Index(
    "ix_registration_observation_context",
    registration_observation.c.run_id.asc().nulls_last(),
    registration_observation.c.attempt_id.asc().nulls_last(),
    registration_observation.c.observed_at_utc.desc(),
)


revision = "m1a003b0001"
down_revision = None
branch_labels = None
depends_on = None

_ORDER = (
    "artifact",
    "source_snapshot",
    "snapshot_file",
    "source_snapshot_file",
    "snapshot_warning",
    "publication_version",
    "source_snapshot_publication",
    "artifact_lineage",
    "research_run",
    "research_run_attempt",
    "research_report",
    "artifact_integrity_event",
    "registration_observation",
)


def _table(name: str) -> sa.Table:
    return _metadata.tables[f"medevidence.{name}"]


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(sa.text("CREATE SCHEMA medevidence"))

    deferred = next(
        constraint
        for constraint in _table("research_run").foreign_key_constraints
        if constraint.name == "fk_research_run_report"
    )
    for name in _ORDER:
        table = _table(name)
        included_fks = [
            constraint
            for constraint in table.foreign_key_constraints
            if constraint.name != "fk_research_run_report"
        ]
        bind.execute(
            sa.schema.CreateTable(
                table,
                include_foreign_key_constraints=included_fks,
            )
        )

    bind.execute(sa.schema.AddConstraint(deferred))

    for name in _ORDER:
        for index in sorted(_table(name).indexes, key=lambda item: item.name or ""):
            bind.execute(sa.schema.CreateIndex(index))


def downgrade() -> None:
    bind = op.get_bind()
    deferred = next(
        constraint
        for constraint in _table("research_run").foreign_key_constraints
        if constraint.name == "fk_research_run_report"
    )
    bind.execute(sa.schema.DropConstraint(deferred))

    for name in reversed(_ORDER):
        for index in sorted(
            _table(name).indexes,
            key=lambda item: item.name or "",
            reverse=True,
        ):
            bind.execute(sa.schema.DropIndex(index))

    for name in reversed(_ORDER):
        bind.execute(sa.schema.DropTable(_table(name)))

    op.execute(sa.text("DROP SCHEMA medevidence RESTRICT"))
