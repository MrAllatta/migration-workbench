import os

from django.db import connection
from django.http import JsonResponse


def healthz(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse(
        {
            "status": "ok",
            "release_id": os.environ.get("RELEASE_ID", "unknown"),
        }
    )
