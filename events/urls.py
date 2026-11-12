
from django.urls import path

from .views import (
    QRStudentLookupView,
    StudentLookupView,
    QRAttendanceView,
    ManualAttendanceView,
    AttendanceListView,
    AttendanceSummaryView,
    AttendanceDashboardView,
)

urlpatterns = [

    # Lookup APIs
    path(
        "qr/lookup/",
        QRStudentLookupView.as_view(),
        name="qr-student-lookup"
    ),

    path(
        "student/lookup/",
        StudentLookupView.as_view(),
        name="student-lookup"
    ),

    # Attendance APIs
    path(
        "qr/present/",
        QRAttendanceView.as_view(),
        name="qr-attendance"
    ),

    path(
        "manual/present/",
        ManualAttendanceView.as_view(),
        name="manual-attendance"
    ),

    # Attendance records
    path(
        "",
        AttendanceListView.as_view(),
        name="attendance-list"
    ),

    path(
        "summary/",
        AttendanceSummaryView.as_view(),
        name="attendance-summary"
    ),

    # Complete attendance dashboard
    path(
        "dashboard/",
        AttendanceDashboardView.as_view(),
        name="attendance-dashboard"
    ),
]
