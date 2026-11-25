

from company.models import Company


def company_switcher(request):
    # print("request.user",request.user,"current_company",request.user.company,request.user.company.all())
    if not request.user.is_authenticated:
        return {}
    if request.user.is_superuser:
        companies = Company.objects.all()
    else:
        companies = request.user.company.all()
    return {'switcher_companies': companies}