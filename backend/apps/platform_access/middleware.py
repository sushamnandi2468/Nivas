from apps.platform_access.models import PlatformAccessEvent


class PlatformAccessDenialAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        denial = getattr(request, "platform_access_denial", None)
        if denial is not None and response.status_code >= 400:
            PlatformAccessEvent.objects.create(**denial)
        return response


class EngineWatermarkMiddleware:
    """Injects overt NivasOps engine watermark and AGPL-3.0 license header."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Engine"] = "NivasOps/0.1.0"
        response["X-License"] = "AGPL-3.0"
        return response