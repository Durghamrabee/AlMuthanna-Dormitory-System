from datetime import timedelta

from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.audit.services import record_event
from .forms import AccountCreateForm, AccountUpdateForm, LoginForm
from .models import LoginThrottle, User
from .policy import require_account_admin
from .services import save_account


@transaction.atomic
def throttled(request, kind, increment=False, clear=False):
    # Use the actual peer, never an untrusted X-Forwarded-For header.
    key = salted_hmac("auth-throttle", f"{kind}:{request.META.get('REMOTE_ADDR', '')}").hexdigest()
    now = timezone.now()
    item, _ = LoginThrottle.objects.get_or_create(key=key, defaults={"window_started": now})
    if clear or now - item.window_started >= timedelta(minutes=5):
        item.window_started, item.failures = now, 0
    if increment:
        item.failures += 1
    item.save(update_fields=["window_started", "failures", "updated_at"])
    return item.failures >= 5


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if throttled(request, "login"):
            return self.render_to_response(self.get_context_data(form=LoginForm(request), throttled=True))
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        throttled(self.request, "login", increment=True)
        return super().form_invalid(form)

    def form_valid(self, form):
        throttled(self.request, "login", clear=True)
        return super().form_valid(form)


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("accounts:password_change_done")

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)
        record_event("auth.password_changed", actor=self.request.user, target=self.request.user)
        return response


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def post(self, request, *args, **kwargs):
        if throttled(request, "reset", increment=True):
            return redirect(self.success_url)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        record_event("auth.reset_requested")
        return response


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)
        record_event("auth.password_reset", target=form.user)
        return response


@login_required
@never_cache
def account_list(request):
    require_account_admin(request.user)
    page = Paginator(User.objects.exclude(username="__local_operator__").order_by("username"), 25).get_page(request.GET.get("page"))
    return render(request, "accounts/list.html", {"accounts": page, "page": page})


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password1", "password2")
def account_edit(request, pk=None):
    require_account_admin(request.user)
    target = get_object_or_404(User.objects.exclude(username="__local_operator__"), pk=pk) if pk else None
    form_class = AccountUpdateForm if target else AccountCreateForm
    form = form_class(request.POST or None, instance=target)
    if request.method == "POST" and form.is_valid():
        try:
            save_account(request.user, form, target)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("accounts:list")
    return render(request, "common/form.html", {"form": form, "title": "تعديل حساب الموظف" if target else "إضافة حساب موظف"})
