"""The Files section of a station (#79, #176): ``/w/<workspace>/<station>/downloads``.

Private to the session like the other steps. It lists every file of the analysis: the
quality-control files of the checks Quality shows, and the files of the finished
calculation (or of its batch station, ``origin``), each with its size. Before the indices
are calculated it holds the quality-control files alone.
"""

from __future__ import annotations

from pathlib import Path

from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from climpact_web.stations import downloads as model
from climpact_web.stations import workspace
from climpact_web.stations.views import get_analysis
from climpact_web.stations.views_indices import current_source, load_results


@never_cache
@require_safe
def downloads(request, workspace_id, slug):
    analysis = get_analysis(request, workspace_id, slug)
    job, source = current_source(analysis)
    qc_done = workspace.shown_qc(analysis) is not None
    if job is None and not qc_done:
        return redirect(analysis.url("results"))
    if job is not None and source is None and not qc_done:  # Results say why
        return redirect(analysis.url("results"))
    quality = model.quality_downloads(analysis, source)
    context = {
        "analysis": analysis,
        "job": job,
        "source": source,
        "quality": quality,
        **workspace.context(analysis, "files", request.path),
        # Files of out-of-date checks or results (#179) are still listed, with a note.
        "stale_results": source is not None and bool(workspace.run_changes(analysis, job)),
        "stale_quality": bool(workspace.qc_changes(analysis, workspace.shown_qc(analysis))),
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
            "from_batch": source.from_batch,
            "plots_made": bool(job.params.get("plots", True)),
            "sector": model.sector_downloads(sector_job(analysis, source)),
        }
    return render(request, "stations/downloads.html", context)
