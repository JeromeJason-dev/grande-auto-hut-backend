from django.urls import path
from .views import (
    TicketListCreateView, TicketDetailView, TicketMessageCreateView,
    TicketAttachmentDownloadView, TicketStatsView,
    StaffListView, StaffMemberDetailView, TaskListCreateView, TaskDetailView,
)

urlpatterns = [
    path("tickets/", TicketListCreateView.as_view(), name="ticket-list-create"),
    path("tickets/stats/", TicketStatsView.as_view(), name="ticket-stats"),
    path("tickets/<uuid:id>/", TicketDetailView.as_view(), name="ticket-detail"),
    path("tickets/<uuid:id>/messages/", TicketMessageCreateView.as_view(), name="ticket-message-create"),
    path(
        "tickets/<uuid:id>/attachments/<uuid:attachment_id>/",
        TicketAttachmentDownloadView.as_view(), name="ticket-attachment-download",
    ),
    path("staff/", StaffListView.as_view(), name="staff-list"),
    path("staff/<uuid:id>/", StaffMemberDetailView.as_view(), name="staff-detail"),
    path("tasks/", TaskListCreateView.as_view(), name="task-list-create"),
    path("tasks/<uuid:id>/", TaskDetailView.as_view(), name="task-detail"),
]