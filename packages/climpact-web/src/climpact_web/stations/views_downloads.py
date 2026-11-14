"""The downloads page of a station's results (#79): ``/station/<id>/downloads``.

Private to the session like the other steps. It lists the files of the analysis's
finished calculation (or of its batch station, ``origin``), each with its size.
"""

from __future__ import annotations

from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from climpact_web.core.navigation import station_steps
from climpact_web.stations import downloads as model
from climpact_web.stations.views import get_analysis
from climpact_web.stations.views_indices import current_source, load_results


@never_cache
@require_safe
def downloads(request, analysis_id):
    analysis = get_analysis(request, analysis_id)
    job, source = current_source(analysis)
    if job is None:
        return redirect("stations:indices", analysis_id=analysis.pk)
    if source is None:  # still running, or finished without tables: step 4 says which
        return redirect("stations:results", analysis_id=analysis.pk)
    run = load_results(analysis, source)
    main = model.main_downloads(source)
    summary = model.summary_downloads(source)
    qc = model.qc_downloads(source)
    first = next((c for s in run.sections() for c in s["cards"] if not c.daily), None)
    return render(
        request,
        "stations/downloads.html",
        {
            "analysis": analysis,
            "job": job,
            "source": source,
            "steps": station_steps("results", analysis.step_urls()),
            "main": main,
            "summary": summary,
            "qc": qc,
            "qc_total": model.totals(qc),
            "sections": model.index_downloads(source, run),
            "first_card": first,
            "from_batch": source.from_batch and analysis.indices_job is None,
            "plots_made": bool(job.params.get("plots", True)),
        },
    )
