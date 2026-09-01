from dataclasses import dataclass, field
from typing import Callable

from django.utils.module_loading import import_string
from rest_framework.exceptions import APIException

from apps.accounts import rbac


@dataclass(frozen=True)
class ReportResult:
    field_order: tuple[str, ...]
    records: list[dict[str, object]]
    meta: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportDefinition:
    key: str
    builder_path: str
    fields: tuple[str, ...]
    required_modules: tuple[str, ...] = ()
    exportable: bool = True
    summary: bool = False
    required_action: str = rbac.Action.VIEW_AUDIT
    title: str = ""
    chart_hint: str = "table"
    grains: tuple[str, ...] = ()
    section_modules: tuple[str, ...] = ()

    def builder(self) -> Callable:
        return import_string(self.builder_path)


class ReportNotFound(APIException):
    status_code = 404

    def __init__(self):
        self.detail = {"detail": "Unknown report key.", "code": "report_not_found"}


class ReportNotExportable(APIException):
    status_code = 400

    def __init__(self):
        self.detail = {"detail": "Report is not exportable.", "code": "report_not_exportable"}
