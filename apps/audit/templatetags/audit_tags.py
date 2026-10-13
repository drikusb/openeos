from django import template

from apps.accounts.scoping import is_org_admin

register = template.Library()


@register.inclusion_tag('audit/org_admin_card.html', takes_context=True)
def organisation_admin_card(context, org):
    """Render the Administration card on the organisation overview.

    The card is only shown to superusers and admins of the given organisation;
    for anyone else the include renders nothing. The decision is made here
    rather than in the view so the template needs no extra context.
    """
    request = context.get('request')
    user = getattr(request, 'user', None)
    show = bool(
        org is not None
        and user is not None
        and user.is_authenticated
        and (user.is_superuser or is_org_admin(user, org))
    )
    return {'show': show, 'org': org}
