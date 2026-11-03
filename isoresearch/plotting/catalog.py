"""Scientific plot advisor catalogue.

Each entry documents the scientific question, required variables, expected
interpretation, alternative explanations, confounders and statistics — and
names the recipe that draws it from the user's own data.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlotSpec:
    id: str
    family: str
    title: str
    question: str
    why: str
    required: list[str]
    interpretation: str
    alternatives: str
    confounders: str
    statistics: str
    recipe: str
    keywords: str
    optional: list[str] = field(default_factory=list)
    options: dict = field(default_factory=dict)  # option name -> list of choices
    extras_required: list[str] = field(default_factory=list)  # multi-dim arrays (NetCDF)
    data_quality: str = ""

    def required_for(self, opts: dict) -> list[str]:
        req = list(self.required)
        for k, v in (opts or {}).items():
            req = [r.replace("{" + k + "}", str(v)) for r in req]
        return req


ISO_OPT = {"y": ["d18o", "d2h", "dexcess"]}
EVAL_OPT = {"var": ["d18o", "d2h", "dexcess"]}

CATALOG: list[PlotSpec] = [
    # ---------------------------------------------------------------- stable isotopes
    PlotSpec("dual", "Stable isotope plots", "δ²H versus δ¹⁸O with GMWL and LMWL",
             "Do local rainfall samples follow the global meteoric water line, and what is the local line?",
             "The LMWL slope/intercept summarise equilibrium vs kinetic (evaporative) fractionation and moisture "
             "source humidity; deviations from the GMWL flag sub-cloud evaporation or distinct sources.",
             ["d18o", "d2h"],
             "Slope ≈ 8 indicates equilibrium condensation; slopes < 8 suggest below-cloud evaporation of falling "
             "drops; a high intercept suggests a source with low relative humidity / high kinetic fractionation.",
             "Seasonal mixing of two moisture sources can produce an apparent low slope without evaporation.",
             "Sample storage evaporation, analytical precision, few low-amount samples dominating the fit.",
             "OLS, RMA and precipitation-weighted (PWLSR) regressions with 95% CI; report n and r².",
             "dual_isotope", "meteoric water line LMWL GMWL slope intercept", optional=["precip"],
             data_quality="Exclude samples flagged for evaporation during storage; state analytical precision."),
    PlotSpec("dexcess", "Stable isotope plots", "d-excess versus δ¹⁸O, relative humidity or temperature",
             "What controls d-excess at the site — evaporation conditions at the source or local processes?",
             "d-excess is sensitive to kinetic fractionation (source RH, SST) and to sub-cloud evaporation.",
             ["{x}", "d18o", "d2h"],
             "Negative d–RH relation at the source is expected (Pfahl & Sodemann type behaviour); locally, low d with "
             "low rainfall suggests below-cloud evaporation.",
             "Moisture recycling over land raises d; changes of source region alter d independently of local RH.",
             "Local RH is not source RH; trajectory-based source conditions may be needed.",
             "OLS slope with CI and Spearman ρ (robust to outliers).",
             "dexcess_vs", "deuterium excess relative humidity source", options={"x": ["d18o", "rh", "temp"]}),
    PlotSpec("ts", "Stable isotope plots", "δ¹⁸O and δ²H time series",
             "How do rainfall isotopes evolve through the monsoon season(s)?",
             "Reveals seasonality, monsoon onset/withdrawal signals and episodic depletion events.",
             ["time", "d18o"], "Progressive depletion during active monsoon spells; enrichment in weak phases.",
             "Changes in moisture source or large-scale organised convection rather than local rainfall.",
             "Irregular sampling; events with very small rainfall.", "Amount-weighted means; event counts.",
             "iso_timeseries", "seasonal variability monsoon onset time series", optional=["d2h", "precip"]),
    # ---------------------------------------------------------------- rainfall / events
    PlotSpec("amount", "Rainfall and event analysis", "Isotope composition versus rainfall amount",
             "Is there an amount effect at the station?",
             "The amount effect is the classical tropical control on δ¹⁸O; its strength varies with timescale.",
             ["precip", "{y}"],
             "A negative slope indicates more depleted rainfall during heavy rain (convective depletion).",
             "Upstream (regional) convection, not local amount, often controls δ (e.g. integrated convective activity "
             "along trajectories).",
             "Timescale (event vs daily vs monthly), rainfall type (stratiform/convective), seasonality.",
             "OLS with 95% CI, Spearman ρ; test separately per season.", "iso_vs_amount",
             "amount effect rainfall amount convection", options=ISO_OPT),
    PlotSpec("intensity", "Rainfall and event analysis", "Isotope composition versus rainfall intensity",
             "Does rainfall intensity explain isotope variability better than total amount?",
             "Intensity relates to convective vigour and to below-cloud evaporation (weak in heavy rain).",
             ["intensity", "{y}"], "Depletion with increasing intensity indicates convective processes.",
             "Intensity is correlated with amount; the two effects are hard to separate.",
             "Gauge resolution; intensity averaging period.", "OLS, Spearman ρ, partial correlation with amount.",
             "iso_vs_intensity", "rainfall intensity convective stratiform", options=ISO_OPT),
    PlotSpec("event", "Rainfall and event analysis", "Event progression (intra-event evolution)",
             "How does isotope composition evolve within individual rain events?",
             "Intra-event 'V' or monotonic patterns reveal changing cloud processes and moisture sources.",
             ["event_id", "time", "{y}"],
             "Progressive depletion suggests Rayleigh-type rainout or increasing convective contribution.",
             "Change of air mass or rain type (convective → stratiform) during the event.",
             "Sampling interval; sample volume; event definition.", "Δδ (last − first), slopes vs cumulative rain.",
             "event_progression", "intra-event variability sequential sampling", options=ISO_OPT),
    PlotSpec("lag", "Rainfall and event analysis", "Lagged relationships with meteorological variables",
             "Do isotopes respond to rainfall/humidity of previous days (memory of upstream convection)?",
             "Lagged correlations reveal integrated upstream influence beyond the local event.",
             ["time", "{x}", "{y}"],
             "A stronger correlation at lag > 0 suggests isotopes integrate convection over preceding days.",
             "Autocorrelation of the meteorological series can create spurious lagged correlations.",
             "Uneven sampling; serial correlation reduces effective sample size.",
             "Pearson r per lag with approximate significance; consider effective-n correction.",
             "lagged_correlation", "lag memory upstream convection preceding days",
             options={"x": ["precip", "rh", "temp", "q", "traj_metric"], "y": ["d18o", "d2h", "dexcess"],
                      "max_lag": ["3", "5", "7", "10", "14"]}),
    PlotSpec("weighted", "Rainfall and event analysis", "Rainfall amount-weighted isotope summaries",
             "What is the representative (amount-weighted) monthly isotope composition?",
             "Weighted means are comparable with GNIP and model monthly output.",
             ["time", "precip", "{y}"], "Differences between weighted and arithmetic means highlight small events.",
             "", "Missing rainfall amounts bias the weighting.", "Σ(P·δ)/ΣP per month; n per month.",
             "weighted_summary", "amount-weighted mean monthly GNIP", options=ISO_OPT),
    # ---------------------------------------------------------------- atmospheric
    PlotSpec("q", "Atmospheric processes", "Isotope composition versus specific humidity",
             "Does vapour/rain follow a Rayleigh-type dependence on humidity, or mixing?",
             "δ–ln q diagrams separate Rayleigh distillation from mixing and re-evaporation processes.",
             ["q", "{y}"], "Linear δ vs ln q is Rayleigh-like; curvature toward mixing lines suggests mixing.",
             "Mixing of air masses with different q and δ; re-evaporation of rain.",
             "Measurement height; q at the surface vs cloud level.", "Fit δ = a + b·ln(q), CI.",
             "iso_vs_q", "specific humidity Rayleigh mixing line", options=ISO_OPT),
    PlotSpec("met", "Atmospheric processes", "Isotope composition versus temperature and relative humidity",
             "What is the role of temperature and humidity in local isotope variability?",
             "Temperature effects are weak in the tropics; RH influences below-cloud evaporation.",
             ["temp", "rh", "{y}"], "Weak T dependence expected at tropical maritime sites.",
             "Temperature and humidity co-vary with rainfall amount.",
             "Diurnal timing of sampling vs meteorological averages.", "OLS per panel; partial correlations.",
             "iso_vs_met", "temperature effect relative humidity", options=ISO_OPT),
    PlotSpec("profile", "Atmospheric processes", "Pressure-level isotope profiles",
             "How do isotopes vary vertically (model levels, soundings or retrievals)?",
             "Vertical structure shows mixing, convective detrainment and the levels a satellite senses.",
             ["pressure", "d2h"], "Depletion with height reflects progressive condensation.",
             "Different averaging (time/space) between datasets can mimic structural differences.",
             "Vertical resolution; interpolation between grids.", "Mean ± σ per level.",
             "vertical_profile", "vertical profile pressure level troposphere",
             optional=["d2h_sim", "d2h_sat", "d18o", "d18o_sim"]),
    PlotSpec("traj", "Atmospheric processes", "Relationship with moisture transport / trajectory diagnostics",
             "Do back-trajectory diagnostics (e.g. rainfall along trajectory, source region uptake) explain isotopes?",
             "Links observed isotopes to upstream processes rather than local conditions.",
             ["traj_metric", "{y}"], "Strong correlations support upstream control (e.g. upstream rainout).",
             "Trajectory errors and model-dependent moisture-uptake attribution.",
             "Trajectory length, starting height, meteorological input (e.g. ERA5) resolution.",
             "OLS and Spearman ρ; sensitivity to trajectory settings.",
             "trajectory_relation", "back trajectory moisture source HYSPLIT uptake transport", options=ISO_OPT),
    # ---------------------------------------------------------------- model evaluation
    PlotSpec("ovs", "Model evaluation", "Observed versus simulated isotope scatterplot",
             "How well does the isotope-enabled model reproduce observed values?",
             "The basic model-evaluation diagnostic, with bias, RMSE and correlation.",
             ["{var}", "{var}_sim"], "Points along 1:1 indicate skill; systematic offset indicates bias.",
             "Representativeness: a grid-cell mean versus a point observation.",
             "Temporal matching of model output to sampling times; spin-up; nudging.",
             "Bias, RMSE, MAE, Pearson r, σ ratio.", "obs_vs_sim", "model evaluation bias RMSE simulated observed",
             options=EVAL_OPT),
    PlotSpec("ots", "Model evaluation", "Observed and simulated time series",
             "Does the model capture the timing and magnitude of isotope variations?",
             "Shows phase errors and event-scale skill hidden in summary metrics.",
             ["time", "{var}", "{var}_sim"], "", "", "Different temporal resolution of output and samples.",
             "Bias, RMSE, r.", "obs_sim_timeseries", "time series comparison model observations", options=EVAL_OPT),
    PlotSpec("season", "Model evaluation", "Seasonal model performance",
             "Is model skill different in the monsoon (JJAS) and other seasons?",
             "Seasonal biases point to specific process deficiencies (e.g. convection parameterisation).",
             ["time", "{var}", "{var}_sim"], "", "", "Small seasonal sample sizes.",
             "Bias and RMSE per season with n.", "seasonal_performance", "seasonal bias monsoon JJAS",
             options=EVAL_OPT),
    PlotSpec("taylor", "Model evaluation", "Taylor diagram",
             "How do correlation and variability compare across variables/simulations?",
             "Summarises r, σ ratio and centred RMSE in one diagram.",
             ["d18o", "d18o_sim"], "", "", "Only meaningful with enough paired samples.",
             "r, normalised σ, centred RMSE.", "taylor_diagram", "Taylor diagram",
             optional=["d2h", "d2h_sim", "dexcess", "dexcess_sim"]),
    PlotSpec("resid", "Model evaluation", "Residual analysis",
             "Are model errors random, or structured in time?",
             "Structured residuals reveal systematic, process-related model errors.",
             ["time", "{var}", "{var}_sim"], "", "", "", "Residual mean, σ, Shapiro–Wilk, lag-1 autocorrelation.",
             "residuals", "residual error uncertainty", options=EVAL_OPT),
    # ---------------------------------------------------------------- satellites
    PlotSpec("sat", "Satellite comparisons", "In situ vs satellite retrieval vs model",
             "Are satellite isotope retrievals consistent with in-situ observations and the model?",
             "Satellites extend spatial coverage; validation establishes their usefulness for the region.",
             ["time", "{var}", "{var}_sat"],
             "Agreement only after accounting for vertical sensitivity (averaging kernels).",
             "Different air masses sampled (column/free troposphere vs surface).",
             "Cloud screening, retrieval quality flags, collocation radius and time window.",
             "Bias, RMSE, r on collocated pairs.", "satellite_comparison", "satellite retrieval validation IASI TES",
             optional=["{var}_sim"], options={"var": ["d2h", "d18o"]}),
    PlotSpec("ak", "Satellite comparisons", "Averaging-kernel-aware profile comparison",
             "How does the model compare with a retrieval once the retrieval's vertical sensitivity is applied?",
             "Applying x_s = x_a + A(x_m − x_a) makes model and retrieval comparable (Rodgers, 2000).",
             [], "Differences that remain after smoothing are genuine model–retrieval differences.",
             "Errors in the a priori or kernel reporting; mismatched pressure grids.",
             "Requires kernel, a priori and model profile on the same pressure grid.",
             "Degrees of freedom for signal (trace A); smoothed − raw difference.",
             "averaging_kernel_comparison", "averaging kernel a priori retrieval profile",
             extras_required=["avg_kernel", "apriori", "model_profile", "pressure"]),
]

BY_ID = {p.id: p for p in CATALOG}


def families() -> list[str]:
    return list(dict.fromkeys(p.family for p in CATALOG))


def default_options(spec: PlotSpec) -> dict:
    return {k: v[0] for k, v in spec.options.items()}


def check_support(spec: PlotSpec, opts: dict, available: dict[str, int], extras: set[str]) -> tuple[bool, list[str]]:
    """``available`` maps role → number of non-missing values.  Returns (ok, messages)."""
    msgs = []
    req = spec.required_for(opts)
    if spec.id == "dexcess":
        x = opts.get("x", "d18o")
        req = [x] + (["dexcess"] if available.get("dexcess") else ["d18o", "d2h"])
    if spec.id == "met":
        y = opts.get("y", "d18o")
        have = [v for v in ("temp", "rh") if available.get(v)]
        req = [y] + (have or ["temp", "rh"])
    ok = True
    for r in dict.fromkeys(req):
        n = available.get(r, 0)
        if n == 0:
            ok = False
            msgs.append(f"✗ Missing variable: {r}. Map a column to it in Data Analysis.")
        elif n < 3:
            ok = False
            msgs.append(f"✗ Only {n} value(s) for {r}; at least 3 are needed.")
        elif n < 10:
            msgs.append(f"⚠ Only {n} values for {r}: statistics will be weak.")
        else:
            msgs.append(f"✓ {r}: {n} values")
    for e in spec.extras_required:
        if e in extras:
            msgs.append(f"✓ array '{e}' available")
        else:
            ok = False
            msgs.append(f"✗ Missing array '{e}' (needs a NetCDF file with this variable mapped).")
    for o in spec.optional:
        o = o.format(**opts) if "{" in o else o
        if available.get(o):
            msgs.append(f"✓ optional {o}: {available[o]} values")
    return ok, msgs
