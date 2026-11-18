from django.urls import path
from . import views
from .agent import views as agent_views

urlpatterns = [
    path('agent/providers/', agent_views.providers),
    path('agent/models/', agent_views.models),
    path('agent/discover/', agent_views.discover),
    path('agent/chat/', agent_views.chat),
    path('filters/', views.filters),
    path("search/", views.search),
    path("games/<int:appid>/", views.game_detail),
    path("games/<int:appid>/insights/", views.game_insights),
    path("health/", views.health),
]
