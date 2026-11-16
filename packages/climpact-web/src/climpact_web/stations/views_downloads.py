"""The Files section of a station (#79, #176): ``/station/<id>/downloads``.

Private to the session like the other steps. It lists every file of the analysis: the
quality-control files of the Quality page's check, and the files of the finished
calculation (or of its batch station, ``origin``), each with its size. Before the indices
are calculated it holds the quality-control files alone.
"""

from __future__ import annotations

from pathlib import Path

from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from climpact_web.core.navigation import station_steps
from climpact_web.jobs.models import Status
from climpact_web.stations import downloads as model
from climpact_web.stations.views import get_analysis
from climpact_web.stations.views_indices import current_source, load_results


@never_cache
@require_safe
def downloads(request, analysis_id):
    analysis = get_analysis(request, analysis_id)
    job, source = current_source(analysis)
    qc_done = analysis.qc_job is not None and analysis.qc_job.status == Status.SUCCEEDED
    if job is None and not qc_done:
        return redirect("stations:indices", analysis_id=analysis.pk)
    if job is not None and source is None:  # still running, or no tables: step 4 says which
        return redirect("stations:results", analysis_id=analysis.pk)
    quality = model.quality_downloads(analysis, source)
    context = {
        "analysis": analysis,
        "job": job,
        "source": source,
        "quality": quality,
        "steps": station_steps("results" if source else "qc", analysis.step_urls()),
    }
    if source is not None:
        from climpact_web.stations.views_sector import sector_job

        run = load_results(analysis, source)
        main = model.main_downloads(source)
        summary = model.summary_downloads(source)
        sections = model.index_downloads(source, run)
        listed = {d.path for d in [*main.values(), *summary] if d}
        listed |= {
            d.path
            for s in sections
            for c in s["cards"]
            for row in c["rows"]
            for d in (row["csv"], row["png"])
            if d
        }
        covered = set()
        if quality and quality["job"] == job:
            listed |= {d.path for d in quality["files"]}
        elif quality:
            covered = {Path(d.path).name for d in quality["files"]}
        context |= {
            "main": main,
            "summary": summary,
            "sections": sections,
            "others": model.other_downloads(source, listed, covered),
            "from_batch": source.from_batch and analysis.indices_job is None,
            "plots_made": bool(job.params.get("plots", True)),
            "sector": model.sector_downloads(sector_job(analysis, source)),
        }
    return render(request, "stations/downloads.html", context)
