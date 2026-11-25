from django.shortcuts import render

# Create your views here.
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from .models import Company
from django.shortcuts import redirect


class SwitchCompanyView(LoginRequiredMixin, View):
    def get(self, request, company_id):
        print("compoany",request,request.user,company_id)
        if request.user.is_superuser:
            allowed = Company.objects.filter(id=company_id).exists()
        else:
            allowed = request.user.company.filter(id=company_id).exists()

        if allowed:
            request.user.current_company_id = company_id
            request.user.save(update_fields=['current_company'])

        return redirect(request.META.get('HTTP_REFERER', '/admin/'))