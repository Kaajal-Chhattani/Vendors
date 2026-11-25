from django.urls import path

from . import views

app_name = 'company'

urlpatterns = [
    path('switch-company/<int:company_id>/', views.SwitchCompanyView.as_view(), name='switch-company'),
]