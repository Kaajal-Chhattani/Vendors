VIEW_ALL_COMPANIES = "company.view_all_companies"


def is_admin(user):
    """True for anyone allowed to see all companies' data: superusers (Django always
    returns True for them) or users granted `view_all_companies` directly or via a Group."""
    return user.is_authenticated and user.has_perm(VIEW_ALL_COMPANIES)


def scope_queryset(qs, user, /, **extra_filters):
    """Users with view_all_companies see everything. Everyone else, including staff, is
    limited to their current company plus any extra filters passed in (e.g. user=request.user)."""
    if is_admin(user):
        return qs
    return qs.filter(company=user.current_company, **extra_filters)
