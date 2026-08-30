import hashlib
import json
import uuid

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render, redirect
from .models import UserProfile
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, login, authenticate
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from django.middleware.csrf import get_token
from django.utils.http import url_has_allowed_host_and_scheme
from .forms import LoginForm
from .token_auth import (
    REFRESH_COOKIE_NAME,
    TokenAuthError,
    issue_token_pair,
    revoke_access_token,
    revoke_refresh_family,
    revoke_user_tokens,
    rotate_refresh_token,
)
# Create your views here.


def _json_request(request):
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _request_id(request):
    return request.headers.get("X-Request-ID", "").strip()[:128] or uuid.uuid4().hex


def _token_error(error, request_id=None, status=None):
    resolved_request_id = request_id or uuid.uuid4().hex
    payload = {
        "success": False,
        "error_code": error.error_code,
        "message": error.message,
        "retryable": error.retryable,
        "next_action": error.next_action,
        "retry_after": error.retry_after,
        "details": error.details,
        "request_id": resolved_request_id,
    }
    response = JsonResponse(payload, status=status or error.http_status or 401)
    response["X-Request-ID"] = resolved_request_id
    if error.retry_after is not None:
        response["Retry-After"] = str(error.retry_after)
    return response


def _structured_error(request, error_code, message, *, status=400, retryable=False,
                      next_action="check_request", retry_after=None, details=None):
    resolved_request_id = _request_id(request)
    payload = {
        "success": False,
        "error_code": error_code,
        "message": message,
        "retryable": retryable,
        "next_action": next_action,
        "retry_after": retry_after,
        "details": details or {},
        "request_id": resolved_request_id,
    }
    response = JsonResponse(payload, status=status)
    response["X-Request-ID"] = resolved_request_id
    if retry_after is not None:
        response["Retry-After"] = str(retry_after)
    return response


def _set_refresh_cookie(response, pair):
    secure = bool(getattr(settings, "MAP_AUTH_COOKIE_SECURE", not settings.DEBUG))
    max_age = None
    if pair.remember_me:
        max_age = int(getattr(settings, "MAP_AUTH_REFRESH_ABSOLUTE_SECONDS", 30 * 86400))
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        pair.refresh_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite=getattr(settings, "MAP_AUTH_COOKIE_SAMESITE", "Lax"),
        path="/",
    )


def _origin_is_allowed(request):
    """Reject cross-site cookie writes while allowing non-browser API clients."""

    origin = request.META.get("HTTP_ORIGIN", "").strip()
    referer = request.META.get("HTTP_REFERER", "").strip()
    if not origin and not referer:
        return True
    target = origin or referer
    return url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    )


def csrf_failure(request, reason=""):
    """Keep API CSRF failures in the same structured envelope as other auth errors."""

    if request.path.startswith("/accounts/api/") or request.path.startswith("/mapping/api/"):
        return _structured_error(
            request,
            "csrf_failed",
            "请求校验失败，请刷新页面后重试",
            status=403,
            next_action="refresh_csrf_token",
        )
    from django.views.csrf import csrf_failure as default_csrf_failure

    return default_csrf_failure(request, reason)


def _security_error(error_code, message, request=None):
    if request is not None:
        return _structured_error(
            request, error_code, message, status=403, next_action="check_request"
        )
    return JsonResponse(
        {"success": False, "error_code": error_code, "message": message}, status=403
    )


def _rate_limit_key(request, username):
    import hashlib

    source = f"{request.META.get('REMOTE_ADDR', '')}:{username.lower()}"
    return "map:auth:login-rate:" + hashlib.sha256(source.encode()).hexdigest()


def _login_is_limited(request, username):
    key = _rate_limit_key(request, username)
    limit = int(getattr(settings, "MAP_AUTH_LOGIN_ATTEMPTS", 10))
    window = int(getattr(settings, "MAP_AUTH_LOGIN_WINDOW_SECONDS", 900))
    current = cache.get(key)
    if current is not None and int(current) >= limit:
        return True
    if not cache.add(key, 1, timeout=window):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=window)
    return False


def _clear_login_rate_limit(request, username):
    cache.delete(_rate_limit_key(request, username))


@csrf_protect
@require_http_methods(["POST", "DELETE"])
def issue_token(request):
    get_token(request)
    if not _origin_is_allowed(request):
        return _security_error("csrf_origin_invalid", "请求来源不受信任", request)
    if request.method == "DELETE":
        return revoke_all_tokens(request)
    payload = _json_request(request)
    if not payload:
        return _structured_error(
            request, "invalid_json", "请求格式无效", status=400,
            next_action="send_valid_json"
        )
    username = str(payload.get("username", "")).strip()
    password = payload.get("password")
    try:
        login_limited = _login_is_limited(request, username)
    except Exception:
        return _structured_error(
            request,
            "auth_rate_limiter_unavailable",
            "登录服务暂时不可用，请稍后重试",
            status=503,
            retryable=True,
            next_action="retry_login",
            retry_after=1,
        )
    if login_limited:
        return _structured_error(
            request,
            "auth_rate_limited",
            "登录尝试次数过多，请稍后再试",
            status=429,
            retryable=True,
            next_action="wait",
            retry_after=int(getattr(settings, "MAP_AUTH_LOGIN_WINDOW_SECONDS", 900)),
        )
    if not username or not isinstance(password, str):
        return _structured_error(
            request, "invalid_credentials", "账号或密码不正确", status=401,
            next_action="check_credentials"
        )
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return _structured_error(
            request, "invalid_credentials", "账号或密码不正确", status=401,
            next_action="check_credentials"
        )
    _clear_login_rate_limit(request, username)
    try:
        pair = issue_token_pair(
            user,
            remember_me=bool(payload.get("remember_me", False)),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            ip_address=request.META.get("REMOTE_ADDR"),
        )
    except TokenAuthError as error:
        return _token_error(error, _request_id(request))
    response = JsonResponse(
        {
            **pair.public_payload(),
            "user": {"id": user.pk, "username": user.get_username()},
        },
        status=201,
    )
    _set_refresh_cookie(response, pair)
    return response


@csrf_protect
@require_http_methods(["DELETE"])
def revoke_all_tokens(request):
    """Revoke every refresh family for the Bearer-authenticated user."""

    get_token(request)
    if not _origin_is_allowed(request):
        return _security_error("csrf_origin_invalid", "请求来源不受信任", request)
    revoked_count = revoke_user_tokens(request.user, "user_logout_all")
    revoke_access_token(getattr(request, "map_access_token", ""))
    response = JsonResponse(
        {"success": True, "revoked_refresh_tokens": revoked_count}
    )
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    return response


@csrf_protect
@require_http_methods(["POST"])
def refresh_token(request):
    get_token(request)
    if not _origin_is_allowed(request):
        return _security_error("csrf_origin_invalid", "请求来源不受信任", request)
    request_id = request.headers.get("X-Refresh-Request-Id", "").strip()
    request_context_id = _request_id(request)
    if not request_id or len(request_id) > 128:
        return _token_error(
            TokenAuthError("refresh_request_invalid", "刷新请求标识无效"),
            request_context_id,
        )
    try:
        pair = rotate_refresh_token(
            request.COOKIES.get(REFRESH_COOKIE_NAME, ""),
            request_id=request_id,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            ip_address=request.META.get("REMOTE_ADDR"),
        )
    except TokenAuthError as error:
        return _token_error(error, request_context_id)
    response = JsonResponse(pair.public_payload())
    _set_refresh_cookie(response, pair)
    return response


@csrf_protect
@require_http_methods(["POST", "DELETE"])
def revoke_current_token(request):
    get_token(request)
    if not _origin_is_allowed(request):
        return _security_error("csrf_origin_invalid", "请求来源不受信任", request)
    raw_refresh_token = request.COOKIES.get(REFRESH_COOKIE_NAME, "")
    authorization = request.headers.get("Authorization", "")
    scheme, separator, access_token = authorization.partition(" ")
    raw_access_token = getattr(request, "map_access_token", "")
    if not raw_access_token and scheme.lower() == "bearer" and separator:
        raw_access_token = access_token.strip()
    revoke_access_token(raw_access_token)
    if raw_refresh_token:
        from .models import RefreshToken

        token_hash = hashlib.sha256(raw_refresh_token.encode("utf-8")).hexdigest()
        token = RefreshToken.objects.filter(token_hash=token_hash).first()
        if token:
            revoke_refresh_family(token.family_id, "user_logout")
    response = JsonResponse({"success": True})
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    return response


def current_user(request):
    """Return the user resolved by WorkbenchBearerMiddleware."""

    return JsonResponse(
        {
            "success": True,
            "user": {
                "id": request.user.pk,
                "username": request.user.get_username(),
                "is_staff": bool(request.user.is_staff),
            },
        }
    )


def do_register(request):
    try:
        msg = ""
        if request.method == "GET":
            return render(request, "register.html", locals())
        if request.method == "POST":
            user = request.user
            datas = request.POST
            username = request.POST.get("username")
            password = request.POST.get("password")
            password2 = request.POST.get("password2")


            if len(username) < 3 or len(password) < 6 or len(password2) < 6:
                msg="账号必须大于3位，密码必须大于6位"
                return render(request, "register.html", locals())
            # 验证密码长度
            if len(password) < 6:
                msg = "密码长度必须至少6位"
                return render(request, "register.html", locals())

            # 验证确认密码长度
            if len(password2) < 6:
                msg = "确认密码长度必须至少6位"
                return render(request, "register.html", locals())

            # 验证一致性
            if password != password2:
                msg = "两次输入的密码不一致"
                return render(request, "register.html", locals())
            only = UserProfile.objects.filter(username=username)
            if len(only) > 0:
                msg = "用户名已经存在"
                return render(request, "register.html", locals())
            new_user = UserProfile()
            new_user.username = username
            new_user.set_password(password)
            new_user.save()
            return redirect("accounts:login")
        else:
            return render(request, "register.html", locals())
    except Exception as e:
        print(e)
        msg = "添加失败系统错误"
        return render(request, "register.html", locals())


def user_login(request):
    try:
        if request.user.is_authenticated:
            pair = issue_token_pair(
                request.user,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            response = redirect("/mapping/")
            _set_refresh_cookie(response, pair)
            return response
        if request.method == 'POST':
            login_form = LoginForm(request.POST)
            if login_form.is_valid():
                username = login_form.cleaned_data["username"]
                password = login_form.cleaned_data["password"]
                user = authenticate(username=username,password=password)
                if user is not None:
                    # user.backend = 'django.contrib.auth.backends.ModelBackend' # 指定默认的登录验证方式

                    login(request, user)
                    pair = issue_token_pair(
                        user,
                        remember_me=bool(request.POST.get("remember_me")),
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                        ip_address=request.META.get("REMOTE_ADDR"),
                    )
                else:
                    errorinfo = "账号或密码不正确"
                    return render(request, 'login.html', {'login_form': login_form, "errorinfo":errorinfo})
                response = redirect("/mapping/")
                _set_refresh_cookie(response, pair)
                return response
            else:
                errorinfo = "账号或密码不正确或格式错误"
                return render(request, 'login.html', {'login_form': login_form, "errorinfo":errorinfo})
        else:
            login_form = LoginForm()
            return render(request, 'login.html', {'login_form': login_form})
    except Exception as e:
        login_form = LoginForm()
        print(e)
        errorinfo = "系统错误"
        return render(request, 'login.html', {'login_form': login_form, "errorinfo":errorinfo})

@login_required
def user_logout(request):
    try:
        logout(request)
        return redirect('accounts:login')
    except Exception as e:
        print(e)
    return render(request, "error.html", {"msg":"退出错误"})

@login_required
def modify(request):
    try:
        user = request.user
        if request.method == 'POST':
            oldpassword = request.POST.get("oldpassword")
            newpassword = request.POST.get("newpassword")
            conpassword = request.POST.get("conpassword")
            if not user.check_password(oldpassword):
                errorinfo = "旧密码错误"
                return render(request, 'modify.html',  locals())
            if newpassword != conpassword:
                errorinfo = "新旧密码不一致"
                return render(request, 'modify.html',  locals())
            if len(newpassword) < 6:
                errorinfo = "密码大于6位"
                return render(request, 'modify.html', locals())
            user.set_password(newpassword)
            user.save()
            logout(request)
            return redirect("/accounts/login")
        else:
            return render(request, 'modify.html', locals())
    except Exception as e:
        print(e)
        errorinfo = "系统错误"
        return render(request, 'modify.html',  locals())
