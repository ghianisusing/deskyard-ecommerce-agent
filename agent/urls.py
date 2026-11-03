from django.urls import path

from . import views

urlpatterns = [
    path("api/chat/", views.chat_api, name="chat_api"),
    path("api/chat/stream/", views.chat_stream_api, name="chat_stream_api"),
    path("api/tts/", views.tts_api, name="tts_api"),
]
