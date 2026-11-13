# R reference environment for Climpact v3.4.3.
#
# Pins every dependency so the R outputs are reproducible:
#   - CRAN packages from the Posit Package Manager snapshot of 2026-09-18
#     (the date the v3.4.3 reference outputs were generated)
#   - PCICt 0.5-4.4 from the CRAN archive (removed from CRAN 2025-05-03)
#   - climdex.pcic from GitHub at a fixed commit (removed from CRAN 2023-05-15;
#     its R code has been unchanged since 2024-10-09)
FROM rocker/r-ver:4.6.1

ARG CRAN_SNAPSHOT=https://p3m.dev/cran/__linux__/noble/2026-09-18
ARG PCICT_URL=https://cran.r-project.org/src/contrib/Archive/PCICt/PCICt_0.5-4.4.tar.gz
ARG CLIMDEX_PCIC_SHA=011cb7828dfef1722d64e2fc207d2d9975280378

RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg-dev zlib1g-dev curl \
    && rm -rf /var/lib/apt/lists/*

RUN echo "options(repos = c(CRAN = '${CRAN_SNAPSHOT}'))" >> /usr/local/lib/R/etc/Rprofile.site

# CRAN packages needed to run the Climpact calculation code and its CSV comparison test
# (the Shiny UI packages are deliberately not installed).
RUN R -q -e "install.packages(c('Rcpp', 'SPEI', 'lmomco', 'zoo', 'zyp', 'Kendall', 'qpdf', 'dplyr', 'testthat'))" \
    && R -q -e "for (p in c('Rcpp','SPEI','lmomco','zoo','zyp','Kendall','qpdf','dplyr','testthat')) library(p, character.only = TRUE)"

RUN curl -fsSL -o /tmp/PCICt.tar.gz "${PCICT_URL}" \
    && R CMD INSTALL /tmp/PCICt.tar.gz \
    && curl -fsSL -o /tmp/climdex.pcic.tar.gz \
       "https://github.com/pacificclimate/climdex.pcic/archive/${CLIMDEX_PCIC_SHA}.tar.gz" \
    && R CMD INSTALL /tmp/climdex.pcic.tar.gz \
    && rm /tmp/*.tar.gz \
    && R -q -e "library(climdex.pcic); print(packageVersion('climdex.pcic'))"

# Gridded (netCDF) support, for climpact.ncdf.thresholds.wrapper.r. Added after the layers
# above so the packages the station references use are unchanged. Climpact installs its
# own modified climdex.pcic.ncdf and ncdf4.helpers 0.3-3 from server/pcic_packages
# (server/climpact.master.installer.r); they are fetched from the Climpact commit the
# references are made with. The CRAN packages come from the same snapshot as above.
ARG CLIMPACT_SHA=5ee0cfe760bbc1b9a9d534cb68c7c7763d6f1c8b
RUN apt-get update \
    && apt-get install -y --no-install-recommends libnetcdf-dev netcdf-bin libudunits2-dev libproj-dev \
    && rm -rf /var/lib/apt/lists/*
RUN R -q -e "install.packages(c('ncdf4', 'abind', 'snow', 'udunits2', 'functional', 'proj4'))" \
    && R -q -e "for (p in c('ncdf4','abind','snow','udunits2','functional','proj4')) library(p, character.only = TRUE)"
RUN base=https://github.com/ARCCSS-extremes/climpact/raw/${CLIMPACT_SHA}/server/pcic_packages \
    && curl -fsSL -o /tmp/ncdf4.helpers_0.3-3.tar.gz "$base/ncdf4.helpers_0.3-3.tar.gz" \
    && curl -fsSL -o /tmp/climdex.pcic.ncdf.tar.gz "$base/climdex.pcic.ncdf.climpact.tar.gz" \
    && echo "b2443932c208053ba6c4ff05079ea20a355d70499af10e5401a87f934f9b2a14  /tmp/ncdf4.helpers_0.3-3.tar.gz" | sha256sum -c - \
    && echo "e27fec3df874f88559b91d0045a7165776101dd4e88b7b854743935e303721fd  /tmp/climdex.pcic.ncdf.tar.gz" | sha256sum -c - \
    && R CMD INSTALL /tmp/ncdf4.helpers_0.3-3.tar.gz \
    && R CMD INSTALL /tmp/climdex.pcic.ncdf.tar.gz \
    && rm /tmp/*.tar.gz \
    && R -q -e "library(climdex.pcic.ncdf); print(packageVersion('climdex.pcic.ncdf'))"

# Record the exact package versions in the image.
RUN R -q -e "ip <- installed.packages()[, c('Package', 'Version')]; write.csv(ip, '/opt/r-package-versions.csv', row.names = FALSE)"

COPY run_reference.R run_gridded_thresholds.R compare_summary.R entrypoint.sh /opt/climpact-ref/
RUN chmod +x /opt/climpact-ref/entrypoint.sh

ENTRYPOINT ["/opt/climpact-ref/entrypoint.sh"]
