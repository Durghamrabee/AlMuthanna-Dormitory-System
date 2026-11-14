from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.common.models import Gender
from apps.dormitories.models import Building
from .models import User
from .roles import ROLE_NAMES


class LoginForm(AuthenticationForm):
    error_messages = {"invalid_login": "تعذر تسجيل الدخول. تحقق من بياناتك وحاول مجدداً.",
                      "inactive": "تعذر تسجيل الدخول. تحقق من بياناتك وحاول مجدداً."}


class AccessFields(forms.ModelForm):
    roles = forms.ModelMultipleChoiceField(label="الأدوار", queryset=None, required=False)
    genders = forms.MultipleChoiceField(label="نطاقات الجنس المخولة صراحةً", choices=Gender.choices, required=False)
    buildings = forms.ModelMultipleChoiceField(label="البنايات المخولة", queryset=Building.objects.none(), required=False)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "is_active", "scope_mode"]
        labels = {"first_name": "الاسم الأول", "last_name": "اللقب", "email": "البريد الإلكتروني", "is_active": "حساب فعال"}

    def __init__(self, *args, **kwargs):
        from django.contrib.auth.models import Group
        super().__init__(*args, **kwargs)
        self.fields["roles"].queryset = Group.objects.filter(name__in=ROLE_NAMES)
        self.fields["buildings"].queryset = Building.objects.select_related("complex")
        self.fields["buildings"].label_from_instance = lambda building: f"{building.complex.name} / {building.name}"
        self.fields["email"].required = True
        if self.instance.pk:
            self.initial["roles"] = self.instance.groups.values_list("pk", flat=True)
            self.initial["genders"] = self.instance.scopes.values_list("gender", flat=True)
            self.initial["buildings"] = self.instance.building_scopes.values_list("building_id", flat=True)


class AccountCreateForm(AccessFields, UserCreationForm):
    def clean_username(self):
        value = super().clean_username()
        if value == "__local_operator__":
            raise forms.ValidationError("اسم المستخدم محجوز للنظام.")
        return value

    class Meta(AccessFields.Meta):
        fields = ["username", *AccessFields.Meta.fields, "password1", "password2"]


class AccountUpdateForm(AccessFields):
    pass
