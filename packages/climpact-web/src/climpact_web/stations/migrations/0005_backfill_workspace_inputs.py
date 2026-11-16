"""Record the inputs of the jobs that existing analyses link to (#179).

Before #179 a change to the file or the station details cleared an analysis's job links,
so a linked job was always produced from the analysis's current file, details and
thresholds. This sets the analysis's ``file_hash`` from its file on disk and gives each
linked ``qc`` and ``station`` job (and the finished run a recalculation replaces, #178) the
inputs it was made from: the file's hash, and the metadata, thresholds and settings in its
own parameters. A station opened from a batch gets the inputs of the batch's results in
``origin["inputs"]``. The workspace then shows them as current, as before.

The values are copied here rather than imported, so the migration does not change when the
code does. Reversing it leaves the columns to the schema migrations.
"""

import hashlib
from pathlib import Path

from django.conf import settings
from django.db import migrations

STATION_FILE = "station.txt"
QC_DEFAULTS = {
    "iqr_temp": 3.0,
    "iqr_prec": 5.0,
    "prec_max": 200.0,
    "temp_max": 50.0,
    "flatline_days": 5,
    "jump": 20.0,
}


def file_hash(analysis_id) -> str:
    path = Path(settings.MEDIA_ROOT) / "stations" / str(analysis_id) / STATION_FILE
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def job_inputs(job, digest: str) -> dict:
    p = job.params or {}
    inputs = {"file": digest, "metadata": p.get("metadata") or {}, "qc": p.get("qc") or {}}
    if job.kind == "station":
        inputs["settings"] = {
            "params": p.get("params") or {},
            "plot_title": p.get("plot_title") or "",
            "plots": bool(p.get("plots", True)),
            "zip": bool(p.get("zip", True)),
            "report": bool(p.get("report", True)),
        }
    return inputs


def forwards(apps, schema_editor):
    StationAnalysis = apps.get_model("stations", "StationAnalysis")
    Job = apps.get_model("jobs", "Job")
    for analysis in StationAnalysis.objects.all().iterator():
        digest = analysis.file_hash or file_hash(analysis.pk)
        jobs = [
            j
            for j in (analysis.qc_job, analysis.indices_job)
            if j is not None and j.kind in ("qc", "station")
        ]
        replaces = (analysis.indices_job.params or {}).get("replaces") if jobs else None
        if replaces:
            jobs += list(Job.objects.filter(pk=replaces, kind="station"))
        for job in jobs:
            if not job.inputs:
                Job.objects.filter(pk=job.pk).update(inputs=job_inputs(job, digest))
        origin = analysis.origin or {}
        if origin and "inputs" not in origin:
            origin = {
                **origin,
                "inputs": {
                    "file": digest,
                    "metadata": {
                        "name": analysis.station_name,
                        "latitude": analysis.latitude,
                        "longitude": analysis.longitude,
                        "base_start": analysis.base_start,
                        "base_end": analysis.base_end,
                    },
                    "qc": {
                        **QC_DEFAULTS,
                        **{k: v for k, v in (analysis.qc_params or {}).items() if k in QC_DEFAULTS},
                    },
                },
            }
        StationAnalysis.objects.filter(pk=analysis.pk).update(file_hash=digest, origin=origin)


class Migration(migrations.Migration):
    dependencies = [
        ("stations", "0004_workspace_inputs"),
        ("jobs", "0003_workspace_inputs"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
