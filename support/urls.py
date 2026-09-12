from django.urls import path
from .views import TicketListCreateView, TicketDetailView, TicketMessageCreateView

urlpatterns = [
    path("tickets/", TicketListCreateView.as_view(), name="ticket-list-create"),
    path("tickets/<uuid:id>/", TicketDetailView.as_view(), name="ticket-detail"),
    path("tickets/<uuid:id>/messages/", TicketMessageCreateView.as_view(), name="ticket-message-create"),
]
