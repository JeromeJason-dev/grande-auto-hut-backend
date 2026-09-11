from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    VehicleMakeListView, VehicleModelListView, VehicleYearListView,
    FitmentProductSearchView, FitmentViewSet,
)

router = DefaultRouter()
router.register("fitments", FitmentViewSet, basename="fitment")

urlpatterns = [
    path("vehicles/makes/", VehicleMakeListView.as_view(), name="vehicle-makes"),
    path("vehicles/<slug:make_slug>/models/", VehicleModelListView.as_view(), name="vehicle-models"),
    path("vehicles/<slug:make_slug>/<slug:model_slug>/years/", VehicleYearListView.as_view(), name="vehicle-years"),
    path("products/fitment/", FitmentProductSearchView.as_view(), name="products-fitment-search"),
] + router.urls
