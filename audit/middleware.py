from time import monotonic
from .operational import record

class OperationalLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = monotonic()
        response = self.get_response(request)
        if request.method not in {'GET','HEAD','OPTIONS'} or response.status_code >= 400:
            match = request.resolver_match
            record('request', actor=getattr(request,'user',None),
                   route=match.view_name if match else 'unmatched',
                   status=response.status_code, duration_ms=int((monotonic()-started)*1000),
                   level='ERROR' if response.status_code >= 500 else 'WARNING' if response.status_code >= 400 else 'INFO')
        return response
