from django.urls import path
from . import views
from . import google_drive_views

app_name = 'problems'

urlpatterns = [
    path('', views.index, name='index'),
    path('google-drive/', google_drive_views.google_drive_status, name='google_drive_status'),
    path('google-drive/connect/', google_drive_views.google_drive_connect, name='google_drive_connect'),
    path('google-drive/callback/', google_drive_views.google_drive_callback, name='google_drive_callback'),
    path('google-drive/disconnect/', google_drive_views.google_drive_disconnect, name='google_drive_disconnect'),
]
