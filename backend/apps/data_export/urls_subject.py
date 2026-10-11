from django.urls import path

from .subject_views import SubjectExportDetailView, SubjectExportDownloadView, SubjectExportListView

urlpatterns = [
    path("member/makerspaces/<int:makerspace_id>/account/exports", SubjectExportListView.as_view(),
         name="member-subject-export-list"),
    path("member/makerspaces/<int:makerspace_id>/account/exports/<uuid:job_id>", SubjectExportDetailView.as_view(),
         name="member-subject-export-detail"),
    path("member/makerspaces/<int:makerspace_id>/account/exports/<uuid:job_id>/download", SubjectExportDownloadView.as_view(),
         name="member-subject-export-download"),
]
