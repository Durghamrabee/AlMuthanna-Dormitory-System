from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.services import record_event
from .models import User, UserScope, UserBuildingScope
from .policy import require_account_admin
from .roles import MALE_MANAGER, FEMALE_MANAGER


@transaction.atomic
def save_account(actor, form, target=None):
    require_account_admin(actor)
    user = form.save(commit=False)
    if target is not None:
        locked = User.objects.select_for_update().get(pk=target.pk)
        if locked.pk == actor.pk and not user.is_active:
            raise ValidationError("لا يمكنك تعطيل حسابك الحالي.")
        if locked.is_superuser and not user.is_active and User.objects.filter(is_active=True, is_superuser=True).count() <= 1:
            raise ValidationError("لا يمكن تعطيل آخر مدير نظام فعال.")
    selected_genders = set(form.cleaned_data["genders"])
    groups = list(form.cleaned_data["roles"])
    buildings = list(form.cleaned_data["buildings"])
    names = {group.name for group in groups}
    if MALE_MANAGER in names and "male" not in selected_genders:
        raise ValidationError("مسؤول سكن الطلاب يحتاج نطاق الطلاب.")
    if FEMALE_MANAGER in names and "female" not in selected_genders:
        raise ValidationError("مسؤولة سكن الطالبات تحتاج نطاق الطالبات.")
    if any(building.complex.gender not in selected_genders for building in buildings):
        raise ValidationError("البنايات المختارة يجب أن تقع ضمن نطاق الجنس المخول.")
    user.save()
    user.groups.set(groups)
    # Explicit replacements ensure removed grants are actually revoked.
    UserScope.objects.filter(user=user).delete()
    UserScope.objects.bulk_create([UserScope(user=user, gender=gender) for gender in selected_genders])
    UserBuildingScope.objects.filter(user=user).delete()
    UserBuildingScope.objects.bulk_create([UserBuildingScope(user=user, building=building) for building in buildings])
    record_event("account.updated" if target else "account.created", actor=actor, target=user,
                 fields=("roles", "gender_scopes", "building_scopes", "scope_mode", "is_active"))
    return user
