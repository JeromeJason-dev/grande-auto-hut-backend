from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),  

    # Auth
    path("api/auth/", include("accounts.urls")),
    path("api/", include("fitment.urls")),
    path("api/", include("catalog.urls")),
    path("api/", include("orders.urls")),
    path("api/", include("payments.urls")),
    path("api/", include("reviews.urls")),
    path("api/", include("support.urls")),
    path("api/", include("inventory.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("core.urls")),

    # API schema / docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)