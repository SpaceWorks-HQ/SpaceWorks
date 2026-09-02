"""Executable enumeration of every phase 1-9 model transport decision."""

from apps.data_export.classification import (
    EXPORTED_MODELS,
    GLOBAL_MODELS,
    OMITTED_MODELS,
)
from apps.data_export.datasets import DATASET_SPECS
from apps.data_export.guards import validate_all
from apps.tenant_migration.tenant_dump_catalog import validate_catalog
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from apps.tenant_migration.tenant_dump_types import ModelDisposition
from apps.makerspaces.module_registry import BY_KEY as MODULES


PROJECT = {
    "events.EventSeries",
    "events.Event",
    "events.EventRegistration",
    "events.EventCheckInEvent",
    "events.EventFeedbackSurvey",
    "events.EventFeedbackResponse",
    "events.EventAttendanceCertificate",
    "evidence.EvidencePhoto",
    "evidence.EvidenceRetentionPolicy",
    "evidence.EvidenceObjectRetentionState",
    "operations.ReportMetricRollup",
}

DROP = {
    "events.EventSeriesCollaborator",
    "events.EventCollaborator",
    "events.EventSeriesOrganizer",
    "events.EventOrganizer",
    "events.MemberCalendarFeed",
    "events.EventCheckInStationCredential",
    "organizations.Organization",
    "organizations.OrganizationMakerspace",
    "organizations.OrganizationMembership",
    "organizations.OrganizationInvitation",
    "operations.ReportRollupCursor",
}

EXPORTED_THEN_DROPPED = {
    "events.EventSeriesCollaborator",
    "events.EventCollaborator",
}


def test_every_programme_model_has_the_reviewed_export_and_lane_d_contract():
    validate_all()
    validate_catalog()

    assert PROJECT <= EXPORTED_MODELS
    assert PROJECT <= set(DATASET_SPECS)
    assert EXPORTED_THEN_DROPPED <= EXPORTED_MODELS
    assert EXPORTED_THEN_DROPPED <= set(DATASET_SPECS)
    assert DROP - EXPORTED_THEN_DROPPED - {"organizations.Organization"} <= set(OMITTED_MODELS)
    assert "organizations.Organization" in GLOBAL_MODELS
    assert {
        label
        for label in PROJECT | DROP
        if FIRST_PARTY_MODEL_RULES[label].disposition == ModelDisposition.PROJECT
    } == PROJECT
    assert {
        label
        for label in PROJECT | DROP
        if FIRST_PARTY_MODEL_RULES[label].disposition == ModelDisposition.DROP
    } == DROP
    # Organizations are deployment-global authority, not a tenant-toggleable module.
    assert "organizations" not in MODULES
