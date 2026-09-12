from django.urls import path
from .views import NotificationListView, NotificationMarkReadView, NotificationMarkAllReadView

urlpatterns = [
    path("notifications/", NotificationListView.as_view(), name="notification-list"),
    path("notifications/read-all/", NotificationMarkAllReadView.as_view(), name="notification-read-all"),
    path("notifications/<uuid:id>/read/", NotificationMarkReadView.as_view(), name="notification-read"),
]
