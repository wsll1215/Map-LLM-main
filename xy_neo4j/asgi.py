"""
ASGI config for xy_neo4j project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'xy_neo4j.settings')

django_asgi_app = get_asgi_application()

from mapping.sse import MapBuildSSEApplication
from accounts.middleware import WorkbenchBearerASGIMiddleware


class HttpApplication:
    """Route only the SSE endpoint specially and keep Django for all other HTTP."""

    def __init__(self, django_app):
        self.django_app = django_app
        self.sse_app = MapBuildSSEApplication()

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if path.startswith("/mapping/api/stream/"):
            await self.sse_app(scope, receive, send)
            return
        await self.django_app(scope, receive, send)

application = ProtocolTypeRouter({
    "http": WorkbenchBearerASGIMiddleware(HttpApplication(django_asgi_app)),
})
