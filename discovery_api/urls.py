from django.urls import path
from . import views

urlpatterns = [
    path("search/", views.search),
    path("games/<int:appid>/", views.game_detail),
    path("games/<int:appid>/insights/", views.game_insights),
    path("health/", views.health),
]
