from django.conf import settings


def jobs(request):
    """``job_retention_days``: how long uploads and results are kept, for the pages that
    must say so (the upload page, #76)."""
    return {"job_retention_days": settings.JOB_RETENTION_DAYS}
