from django.conf import settings


def jobs(request):
    """``job_retention_days``: how long uploads and results are kept, for the pages that
    must say so (the upload page, #76); ``workspace_expiry``: whether workspaces are
    deleted after it at all (#231; off locally)."""
    return {
        "job_retention_days": settings.JOB_RETENTION_DAYS,
        "workspace_expiry": settings.WORKSPACE_EXPIRY,
    }
