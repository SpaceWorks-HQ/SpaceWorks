from urllib.parse import urlsplit

from django.conf import settings


class AdminCspEvalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path_info == "/control" or request.path_info.startswith("/control/"):
            # Unfold's standard Alpine build requires unsafe-eval; the Django admin is
            # superuser-gated, so keep this exception scoped to admin responses only.
            merged = dict(getattr(response, "_csp_update", None) or {})
            script_src = merged.get("script-src", [])
            if isinstance(script_src, str):
                script_src = [script_src]
            else:
                script_src = list(script_src)
            if "'unsafe-eval'" not in script_src:
                script_src.append("'unsafe-eval'")
            merged["script-src"] = script_src

            endpoint = getattr(settings, "AWS_S3_PUBLIC_ENDPOINT_URL", "") or ""
            if endpoint:
                parts = urlsplit(endpoint)
                if parts.scheme and parts.netloc:
                    origin = f"{parts.scheme}://{parts.netloc}"
                    img_src = merged.get("img-src", [])
                    if isinstance(img_src, str):
                        img_src = [img_src]
                    else:
                        img_src = list(img_src)
                    if origin not in img_src:
                        img_src.append(origin)
                    merged["img-src"] = img_src

            response._csp_update = merged
        return response
