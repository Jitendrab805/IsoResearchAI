"""Plot recipes.

IMPORTANT DESIGN RULE: every function in this module is self-contained (only
numpy / pandas / scipy / matplotlib) because the *same source code* is copied
into the exported, standalone plotting script.  The preview in the app and
the script you keep are therefore identical.

Recipes only plot the user's data.  They never generate, impute or
interpolate observations.  Each returns ``{"stats": [...], "notes": [...]}``.

Expected columns (canonical roles): time, precip [mm], intensity [mm/h],
temp [°C], rh [%], q [g/kg], pressure [hPa], d18o / d2h / dexcess [‰],
*_sim (model), *_sat (satellite), event_id, traj_metric.
"""
import numpy as np
import pandas as pd
from scipy import stats as _st

PALETTE = ["#0f766e", "#d97706", "#2563eb", "#9333ea", "#dc2626", "#4b5563"]
LABEL = {"d18o": "δ$^{18}$O (‰)", "d2h": "δ$^{2}$H (‰)", "dexcess": "d-excess (‰)", "precip": "Rainfall (mm)",
         "intensity": "Rainfall intensity (mm h$^{-1}$)", "temp": "Air temperature (°C)", "rh": "Relative humidity (%)",
         "q": "Specific humidity (g kg$^{-1}$)", "pressure": "Pressure (hPa)", "traj_metric": "Trajectory diagnostic"}


def _lab(v):
    base = v.replace("_sim", "").replace("_sat", "")
    suffix = " – model" if v.endswith("_sim") else (" – satellite" if v.endswith("_sat") else "")
    return LABEL.get(base, base) + suffix


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=0.25, lw=0.6)
    ax.tick_params(direction="out", length=3)


def _clean(df, cols):
    return df[list(cols)].dropna()


def _ols(x, y):
    r = _st.linregress(x, y)
    n = len(x)
    tval = _st.t.ppf(0.975, n - 2) if n > 2 else np.nan
    return {"slope": r.slope, "intercept": r.intercept, "r": r.rvalue, "p": r.pvalue,
            "slope_ci": tval * r.stderr if n > 2 else np.nan, "n": n}


def _rma(x, y):
    """Reduced major axis regression (both variables have error)."""
    r = np.corrcoef(x, y)[0, 1]
    slope = np.sign(r) * np.std(y, ddof=1) / np.std(x, ddof=1)
    return {"slope": slope, "intercept": np.mean(y) - slope * np.mean(x), "r": r, "n": len(x)}


def _pwlsr(x, y, w):
    """Precipitation-amount-weighted least squares (Hughes & Crawford, 2012 style)."""
    w = np.asarray(w, float)
    xm, ym = np.average(x, weights=w), np.average(y, weights=w)
    slope = np.sum(w * (x - xm) * (y - ym)) / np.sum(w * (x - xm) ** 2)
    return {"slope": slope, "intercept": ym - slope * xm, "n": len(x)}


def _metrics(o, s):
    o, s = np.asarray(o, float), np.asarray(s, float)
    m = np.isfinite(o) & np.isfinite(s)
    o, s = o[m], s[m]
    n = len(o)
    if n < 3:
        return {"n": n}
    r, p = _st.pearsonr(o, s)
    return {"n": n, "bias": float(np.mean(s - o)), "rmse": float(np.sqrt(np.mean((s - o) ** 2))),
            "mae": float(np.mean(np.abs(s - o))), "r": float(r), "p": float(p),
            "std_ratio": float(np.std(s) / np.std(o)) if np.std(o) > 0 else np.nan,
            "crmse": float(np.sqrt(np.mean(((s - s.mean()) - (o - o.mean())) ** 2)))}


def _fmt_metrics(m, unit="‰"):
    if m.get("n", 0) < 3:
        return [f"n = {m.get('n', 0)}: too few paired values for statistics"]
    return [f"n = {m['n']}", f"bias (model − obs) = {m['bias']:.2f} {unit}", f"RMSE = {m['rmse']:.2f} {unit}",
            f"MAE = {m['mae']:.2f} {unit}", f"Pearson r = {m['r']:.2f} (p = {m['p']:.2g})",
            f"σ_model/σ_obs = {m['std_ratio']:.2f}"]


# ------------------------------------------------------------ stable isotopes
def dual_isotope(df, fig, opts, extras=None):
    d = _clean(df, ["d18o", "d2h"] + (["precip"] if "precip" in df else []))
    ax = fig.add_subplot(111)
    _style(ax)
    ax.scatter(d["d18o"], d["d2h"], s=22, c=PALETTE[0], alpha=0.8, edgecolor="none", label=f"samples (n={len(d)})")
    xs = np.linspace(d["d18o"].min() - 1, d["d18o"].max() + 1, 50)
    ax.plot(xs, 8 * xs + 10, color="0.4", ls="--", lw=1, label="GMWL: δ²H = 8·δ¹⁸O + 10")
    out = {"stats": [], "notes": ["GMWL after Craig (1961). LMWL fitted only to the plotted samples."]}
    if len(d) >= 3:
        o = _ols(d["d18o"], d["d2h"])
        ax.plot(xs, o["slope"] * xs + o["intercept"], color=PALETTE[1], lw=1.6,
                label=f"LMWL (OLS): {o['slope']:.2f}x + {o['intercept']:.1f}")
        r = _rma(d["d18o"].values, d["d2h"].values)
        out["stats"] += [f"OLS LMWL slope = {o['slope']:.2f} ± {o['slope_ci']:.2f} (95% CI), "
                         f"intercept = {o['intercept']:.1f}, r² = {o['r'] ** 2:.3f}, n = {o['n']}",
                         f"RMA LMWL slope = {r['slope']:.2f}, intercept = {r['intercept']:.1f}"]
        if "precip" in d and (d["precip"] > 0).sum() >= 3:
            w = d[d["precip"] > 0]
            p = _pwlsr(w["d18o"].values, w["d2h"].values, w["precip"].values)
            ax.plot(xs, p["slope"] * xs + p["intercept"], color=PALETTE[2], lw=1.2, ls=":",
                    label=f"LMWL (PWLSR): {p['slope']:.2f}x + {p['intercept']:.1f}")
            out["stats"].append(f"Amount-weighted (PWLSR) slope = {p['slope']:.2f}, intercept = {p['intercept']:.1f}")
    else:
        out["notes"].append("Fewer than 3 paired samples: LMWL not fitted.")
    ax.set_xlabel(_lab("d18o"))
    ax.set_ylabel(_lab("d2h"))
    ax.legend(frameon=False, fontsize=8)
    return out


def dexcess_vs(df, fig, opts, extras=None):
    x = opts.get("x", "d18o")
    notes = []
    data = df.copy()
    if "dexcess" not in data or data["dexcess"].isna().all():
        data["dexcess"] = data["d2h"] - 8 * data["d18o"]
        notes.append("d-excess derived from the measured values as d = δ²H − 8·δ¹⁸O (Dansgaard, 1964).")
    d = _clean(data, [x, "dexcess"])
    ax = fig.add_subplot(111)
    _style(ax)
    ax.scatter(d[x], d["dexcess"], s=22, c=PALETTE[3], alpha=0.8, edgecolor="none")
    ax.axhline(10, color="0.5", ls="--", lw=0.8, label="global mean ≈ 10‰")
    st = []
    if len(d) >= 3:
        o = _ols(d[x], d["dexcess"])
        xs = np.linspace(d[x].min(), d[x].max(), 50)
        ax.plot(xs, o["slope"] * xs + o["intercept"], color=PALETTE[1], lw=1.5,
                label=f"OLS slope {o['slope']:.2f} (r = {o['r']:.2f})")
        rs = _st.spearmanr(d[x], d["dexcess"])
        st = [f"OLS slope = {o['slope']:.3f} ± {o['slope_ci']:.3f}, r = {o['r']:.2f}, p = {o['p']:.2g}, n = {o['n']}",
              f"Spearman ρ = {rs.correlation:.2f} (p = {rs.pvalue:.2g})"]
    ax.set_xlabel(_lab(x))
    ax.set_ylabel(_lab("dexcess"))
    ax.legend(frameon=False, fontsize=8)
    return {"stats": st, "notes": notes}


def iso_timeseries(df, fig, opts, extras=None):
    vars_ = [v for v in ("d18o", "d2h") if v in df and df[v].notna().any()]
    d = df.dropna(subset=["time"]).sort_values("time")
    axes = fig.subplots(len(vars_) + (1 if "precip" in d else 0), 1, sharex=True, squeeze=False)[:, 0]
    i = 0
    if "precip" in d:
        axes[0].bar(d["time"], d["precip"], width=0.8, color="#60a5fa")
        axes[0].set_ylabel("Rain (mm)")
        _style(axes[0])
        i = 1
    st = []
    for k, v in enumerate(vars_):
        ax = axes[i + k]
        _style(ax)
        s = d[["time", v]].dropna()
        ax.plot(s["time"], s[v], "o-", ms=3, lw=0.8, color=PALETTE[k])
        ax.set_ylabel(_lab(v))
        st.append(f"{v}: n = {len(s)}, mean = {s[v].mean():.2f}‰, range {s[v].min():.2f} to {s[v].max():.2f}‰")
        if "precip" in d:
            w = d[["precip", v]].dropna()
            w = w[w["precip"] > 0]
            if len(w):
                st.append(f"{v} amount-weighted mean = {np.average(w[v], weights=w['precip']):.2f}‰")
    fig.autofmt_xdate()
    return {"stats": st, "notes": ["Lines join consecutive samples only for readability; gaps are not filled."]}


# ------------------------------------------------------------ rainfall events
def _vs(df, fig, x, y="d18o", logx=False):
    d = _clean(df, [x, y])
    if logx:
        d = d[d[x] > 0]
    ax = fig.add_subplot(111)
    _style(ax)
    xv = np.log(d[x]) if logx else d[x]
    ax.scatter(d[x], d[y], s=24, c=PALETTE[0], alpha=0.8, edgecolor="none")
    st = []
    if len(d) >= 3:
        o = _ols(xv, d[y])
        xs = np.linspace(xv.min(), xv.max(), 60)
        ax.plot(np.exp(xs) if logx else xs, o["slope"] * xs + o["intercept"], color=PALETTE[1], lw=1.5,
                label=f"OLS: slope {o['slope']:.3f}{' per ln-unit' if logx else ''}, r = {o['r']:.2f}")
        rs = _st.spearmanr(d[x], d[y])
        st = [f"OLS slope = {o['slope']:.4f} ± {o['slope_ci']:.4f} (95% CI) ‰/{'ln(' + x + ')' if logx else x}",
              f"r = {o['r']:.2f}, r² = {o['r'] ** 2:.3f}, p = {o['p']:.2g}, n = {o['n']}",
              f"Spearman ρ = {rs.correlation:.2f} (p = {rs.pvalue:.2g})"]
        ax.legend(frameon=False, fontsize=8)
    if logx:
        ax.set_xscale("log")
    ax.set_xlabel(_lab(x))
    ax.set_ylabel(_lab(y))
    return st


def iso_vs_amount(df, fig, opts, extras=None):
    st = _vs(df, fig, "precip", opts.get("y", "d18o"))
    return {"stats": st, "notes": ["A negative slope is consistent with — but does not prove — an amount effect; "
                                   "upstream convection and moisture source can produce similar relationships."]}


def iso_vs_intensity(df, fig, opts, extras=None):
    return {"stats": _vs(df, fig, "intensity", opts.get("y", "d18o")), "notes": []}


def event_progression(df, fig, opts, extras=None):
    y = opts.get("y", "d18o")
    d = _clean(df, ["event_id", "time", y]).sort_values("time")
    ax = fig.add_subplot(111)
    _style(ax)
    st = []
    for k, (eid, g) in enumerate(d.groupby("event_id")):
        if len(g) < 2:
            continue
        hours = (g["time"] - g["time"].iloc[0]).dt.total_seconds() / 3600
        ax.plot(hours, g[y], "o-", ms=3, lw=1, color=PALETTE[k % len(PALETTE)], label=str(eid))
        st.append(f"event {eid}: n = {len(g)}, Δ{y} (last − first) = {g[y].iloc[-1] - g[y].iloc[0]:+.2f}‰")
    ax.set_xlabel("Hours since first sample in event")
    ax.set_ylabel(_lab(y))
    if st:
        ax.legend(frameon=False, fontsize=7, ncol=2, title="event")
    return {"stats": st or ["No event has ≥ 2 samples."], "notes": []}


def lagged_correlation(df, fig, opts, extras=None):
    x, y, max_lag = opts.get("x", "precip"), opts.get("y", "d18o"), int(opts.get("max_lag", 7))
    d = df.dropna(subset=["time"]).set_index("time").sort_index()
    daily = d[[x, y]].resample("1D").mean()  # no filling: missing days stay missing
    lags, rs, ns = [], [], []
    for lag in range(0, max_lag + 1):
        pair = pd.concat([daily[x].shift(lag), daily[y]], axis=1).dropna()
        if len(pair) >= 5:
            lags.append(lag)
            rs.append(pair.corr().iloc[0, 1])
            ns.append(len(pair))
    ax = fig.add_subplot(111)
    _style(ax)
    ax.bar(lags, rs, color=PALETTE[2])
    if ns:
        crit = 1.96 / np.sqrt(np.array(ns))
        ax.plot(lags, crit, "k--", lw=0.8, label="≈95% significance (no autocorrelation correction)")
        ax.plot(lags, -crit, "k--", lw=0.8)
        ax.legend(frameon=False, fontsize=8)
    ax.axhline(0, color="0.3", lw=0.6)
    ax.set_xlabel(f"Lag (days): {x} leads {y}")
    ax.set_ylabel("Pearson r")
    return {"stats": [f"lag {l} d: r = {r:.2f} (n = {n})" for l, r, n in zip(lags, rs, ns)],
            "notes": ["Daily means of available samples; missing days are not interpolated. Serial correlation "
                      "reduces the effective sample size — treat significance lines as optimistic."]}


def weighted_summary(df, fig, opts, extras=None):
    y = opts.get("y", "d18o")
    d = _clean(df, ["time", "precip", y])
    d = d[d["precip"] > 0]
    d["month"] = d["time"].dt.to_period("M")
    g = d.groupby("month").apply(lambda t: pd.Series({"w": np.average(t[y], weights=t["precip"]),
                                                     "u": t[y].mean(), "rain": t["precip"].sum(), "n": len(t)}),
                                 include_groups=False)
    ax = fig.add_subplot(111)
    _style(ax)
    xs = np.arange(len(g))
    ax.bar(xs - 0.2, g["w"], 0.4, color=PALETTE[0], label="amount-weighted")
    ax.bar(xs + 0.2, g["u"], 0.4, color=PALETTE[1], alpha=0.7, label="arithmetic mean")
    ax.set_xticks(xs, [str(m) for m in g.index], rotation=45, ha="right")
    ax.set_ylabel(_lab(y))
    ax.legend(frameon=False, fontsize=8)
    return {"stats": [f"{m}: weighted {r.w:.2f}‰, mean {r.u:.2f}‰, rain {r.rain:.0f} mm, n = {int(r.n)}"
                      for m, r in g.iterrows()],
            "notes": ["Weighted mean = Σ(P·δ)/ΣP using only samples with both rainfall and isotope values."]}


# ------------------------------------------------------------ atmospheric
def iso_vs_q(df, fig, opts, extras=None):
    st = _vs(df, fig, "q", opts.get("y", "d18o"), logx=True)
    return {"stats": st, "notes": ["Linear fit of δ against ln(q): a Rayleigh-like dependence. Mixing and "
                                   "re-evaporation also produce δ–ln q relationships; compare with mixing lines."]}


def iso_vs_met(df, fig, opts, extras=None):
    y = opts.get("y", "d18o")
    xs = [v for v in ("temp", "rh") if v in df and df[v].notna().any()]
    axes = fig.subplots(1, len(xs), squeeze=False)[0]
    st = []
    for ax, x in zip(axes, xs):
        _style(ax)
        d = _clean(df, [x, y])
        ax.scatter(d[x], d[y], s=20, c=PALETTE[0], alpha=0.8, edgecolor="none")
        if len(d) >= 3:
            o = _ols(d[x], d[y])
            t = np.linspace(d[x].min(), d[x].max(), 30)
            ax.plot(t, o["slope"] * t + o["intercept"], color=PALETTE[1])
            st.append(f"{y} vs {x}: slope {o['slope']:.3f}, r = {o['r']:.2f}, p = {o['p']:.2g}, n = {o['n']}")
        ax.set_xlabel(_lab(x))
        ax.set_ylabel(_lab(y))
    return {"stats": st, "notes": ["Temperature and humidity co-vary with rainfall; consider partial correlation."]}


def vertical_profile(df, fig, opts, extras=None):
    cols = [c for c in ("d2h", "d2h_sim", "d2h_sat", "d18o", "d18o_sim", "model_profile", "apriori")
            if c in df and df[c].notna().any()]
    d = df.dropna(subset=["pressure"])
    g = d.groupby("pressure")[cols].agg(["mean", "std"])
    ax = fig.add_subplot(111)
    _style(ax)
    for k, c in enumerate(cols):
        m, s = g[(c, "mean")], g[(c, "std")]
        ax.plot(m, g.index, "o-", ms=3, color=PALETTE[k % 6], label=_lab(c))
        if s.notna().any():
            ax.fill_betweenx(g.index, m - s, m + s, color=PALETTE[k % 6], alpha=0.15)
    ax.invert_yaxis()
    ax.set_ylabel("Pressure (hPa)")
    ax.set_xlabel("δ (‰)")
    ax.legend(frameon=False, fontsize=8)
    return {"stats": [f"{len(g)} pressure levels; shading = ±1σ across samples at each level"], "notes": []}


def trajectory_relation(df, fig, opts, extras=None):
    st = _vs(df, fig, "traj_metric", opts.get("y", "d18o"))
    return {"stats": st, "notes": ["Trajectory diagnostics depend on the model, meteorological input and "
                                   "duration used; report these with the plot."]}


# ------------------------------------------------------------ model evaluation
def obs_vs_sim(df, fig, opts, extras=None):
    v = opts.get("var", "d18o")
    d = _clean(df, [v, v + "_sim"])
    ax = fig.add_subplot(111)
    _style(ax)
    ax.scatter(d[v], d[v + "_sim"], s=22, c=PALETTE[0], alpha=0.8, edgecolor="none")
    lo, hi = np.nanmin(d.values), np.nanmax(d.values)
    ax.plot([lo, hi], [lo, hi], "k--", lw=0.8, label="1:1")
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Observed " + _lab(v))
    ax.set_ylabel("Simulated " + _lab(v))
    ax.legend(frameon=False, fontsize=8)
    m = _metrics(d[v], d[v + "_sim"])
    return {"stats": _fmt_metrics(m), "notes": ["Pairs are matched row-by-row as stored in the file; make sure "
                                                "model output was sampled at the observation times/location."]}


def obs_sim_timeseries(df, fig, opts, extras=None):
    v = opts.get("var", "d18o")
    d = df.dropna(subset=["time"]).sort_values("time")
    ax = fig.add_subplot(111)
    _style(ax)
    o = d[["time", v]].dropna()
    s = d[["time", v + "_sim"]].dropna()
    ax.plot(o["time"], o[v], "o", ms=4, color="k", label="observed")
    ax.plot(s["time"], s[v + "_sim"], "-", lw=1.2, color=PALETTE[1], label="simulated")
    ax.set_ylabel(_lab(v))
    ax.legend(frameon=False, fontsize=8)
    fig.autofmt_xdate()
    return {"stats": _fmt_metrics(_metrics(d[v], d[v + "_sim"])), "notes": []}


def seasonal_performance(df, fig, opts, extras=None):
    v = opts.get("var", "d18o")
    d = _clean(df, ["time", v, v + "_sim"])
    seasons = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM", 6: "JJAS", 7: "JJAS", 8: "JJAS",
               9: "JJAS", 10: "ON", 11: "ON"}
    d["season"] = d["time"].dt.month.map(seasons)
    rows = []
    for sname in ["DJF", "MAM", "JJAS", "ON"]:
        g = d[d["season"] == sname]
        m = _metrics(g[v], g[v + "_sim"])
        rows.append((sname, m))
    ax = fig.subplots(1, 2)
    for a in ax:
        _style(a)
    names = [r[0] for r in rows]
    ax[0].bar(names, [r[1].get("bias", np.nan) for r in rows], color=PALETTE[1])
    ax[0].axhline(0, color="0.3", lw=0.6)
    ax[0].set_ylabel("Bias (model − obs, ‰)")
    ax[1].bar(names, [r[1].get("rmse", np.nan) for r in rows], color=PALETTE[2])
    ax[1].set_ylabel("RMSE (‰)")
    st = [f"{n}: " + (", ".join(f"{k}={m[k]:.2f}" for k in ("bias", "rmse", "r") if k in m) or "too few") +
          f" (n={m.get('n', 0)})" for n, m in rows]
    return {"stats": st, "notes": ["Seasons: DJF, MAM, JJAS (Indian summer monsoon), ON (post-monsoon). "
                                   "Small seasonal samples give unstable metrics."]}


def taylor_diagram(df, fig, opts, extras=None):
    vars_ = [v for v in ("d18o", "d2h", "dexcess") if v in df and v + "_sim" in df]
    ax = fig.add_subplot(111, projection="polar")
    ax.set_thetamin(0)
    ax.set_thetamax(90)
    st = []
    smax = 1.6
    for k, v in enumerate(vars_):
        m = _metrics(df[v], df[v + "_sim"])
        if m.get("n", 0) < 3:
            continue
        theta = np.arccos(np.clip(m["r"], -1, 1))
        ax.plot(theta, m["std_ratio"], "o", ms=8, color=PALETTE[k], label=v)
        smax = max(smax, m["std_ratio"] * 1.2)
        st.append(f"{v}: r = {m['r']:.2f}, normalised σ = {m['std_ratio']:.2f}, n = {m['n']}")
    ax.plot(0, 1, "k*", ms=10, label="reference (obs)")
    t = np.linspace(0, np.pi / 2, 100)
    for rr in (0.5, 1.0, 1.5):
        ax.plot(t, np.full_like(t, rr), color="0.85", lw=0.5)
    corr_ticks = np.array([0, 0.2, 0.4, 0.6, 0.8, 0.9, 0.95, 0.99, 1.0])
    ax.set_thetagrids(np.degrees(np.arccos(corr_ticks)), [f"{c:g}" for c in corr_ticks])
    ax.set_rmax(smax)
    ax.set_xlabel("Normalised standard deviation")
    ax.legend(frameon=False, fontsize=8, loc="upper right", bbox_to_anchor=(1.25, 1.1))
    return {"stats": st, "notes": ["Angle = correlation, radius = σ_model/σ_obs; distance to ★ = centred RMSE."]}


def residuals(df, fig, opts, extras=None):
    v = opts.get("var", "d18o")
    d = _clean(df, ["time", v, v + "_sim"]).sort_values("time")
    res = d[v + "_sim"] - d[v]
    ax1, ax2 = fig.subplots(1, 2, gridspec_kw={"width_ratios": [2.2, 1]})
    for a in (ax1, ax2):
        _style(a)
    ax1.axhline(0, color="0.3", lw=0.6)
    ax1.plot(d["time"], res, "o", ms=3, color=PALETTE[3])
    ax1.set_ylabel("Residual (model − obs, ‰)")
    ax2.hist(res, bins="auto", color=PALETTE[3], alpha=0.8)
    ax2.set_xlabel("Residual (‰)")
    fig.autofmt_xdate()
    st = [f"mean residual = {res.mean():.2f}‰, σ = {res.std():.2f}‰, n = {len(res)}"]
    if len(res) >= 8:
        sh = _st.shapiro(res)
        st.append(f"Shapiro–Wilk p = {sh.pvalue:.2g} (normality of residuals)")
        ac = pd.Series(res.values).autocorr(1)
        st.append(f"lag-1 autocorrelation of residuals = {ac:.2f}")
    return {"stats": st, "notes": []}


# ------------------------------------------------------------ satellites
def satellite_comparison(df, fig, opts, extras=None):
    v = opts.get("var", "d2h")
    cols = [c for c in (v, v + "_sat", v + "_sim") if c in df]
    d = df.dropna(subset=["time"]).sort_values("time")
    ax1, ax2 = fig.subplots(1, 2, gridspec_kw={"width_ratios": [2, 1]})
    for a in (ax1, ax2):
        _style(a)
    names = {v: "in situ", v + "_sat": "satellite", v + "_sim": "model"}
    for k, c in enumerate(cols):
        s = d[["time", c]].dropna()
        ax1.plot(s["time"], s[c], "o-" if c != v + "_sim" else "-", ms=3, lw=1, color=PALETTE[k], label=names[c])
    ax1.legend(frameon=False, fontsize=8)
    ax1.set_ylabel(_lab(v))
    st = []
    if v + "_sat" in d:
        p = _clean(d, [v, v + "_sat"])
        ax2.scatter(p[v], p[v + "_sat"], s=18, color=PALETTE[1])
        if len(p):
            lo, hi = p.values.min(), p.values.max()
            ax2.plot([lo, hi], [lo, hi], "k--", lw=0.8)
        ax2.set_xlabel("in situ")
        ax2.set_ylabel("satellite")
        st += ["satellite vs in situ: " + "; ".join(_fmt_metrics(_metrics(p[v], p[v + "_sat"])))]
    fig.autofmt_xdate()
    return {"stats": st, "notes": ["Satellite retrievals have limited vertical sensitivity; a direct comparison "
                                   "with surface/near-surface in-situ values is only indicative unless averaging "
                                   "kernels are applied (see the averaging-kernel plot)."]}


def averaging_kernel_comparison(df, fig, opts, extras=None):
    """x_smoothed = x_a + A (x_model − x_a)   (Rodgers, 2000)."""
    A = np.asarray(extras["avg_kernel"], float)
    xa = np.asarray(extras["apriori"], float)
    xm = np.asarray(extras["model_profile"], float)
    p = np.asarray(extras["pressure"], float)
    # use the first profile if time-dependent
    while A.ndim > 2:
        A = A[0]
    xa = xa.reshape(-1, len(p))[0] if xa.ndim > 1 else xa
    xm = xm.reshape(-1, len(p))[0] if xm.ndim > 1 else xm
    xs = xa + A @ (xm - xa)
    ax1, ax2 = fig.subplots(1, 2, sharey=True)
    for a in (ax1, ax2):
        _style(a)
    ax1.plot(xa, p, "--", color="0.5", label="a priori")
    ax1.plot(xm, p, "-", color=PALETTE[1], label="model (raw)")
    ax1.plot(xs, p, "-", color=PALETTE[0], lw=2, label="model × AK")
    if "retrieval" in extras:
        xr_ = np.asarray(extras["retrieval"], float)
        xr_ = xr_.reshape(-1, len(p))[0] if xr_.ndim > 1 else xr_
        ax1.plot(xr_, p, "o", color="k", ms=4, label="retrieval")
    ax1.invert_yaxis()
    ax1.set_ylabel("Pressure (hPa)")
    ax1.set_xlabel("δD (‰)")
    ax1.legend(frameon=False, fontsize=8)
    for i in range(A.shape[0]):
        ax2.plot(A[i, :], p, lw=0.8, color=PALETTE[i % 6], alpha=0.8)
    ax2.set_xlabel("Averaging-kernel rows")
    dofs = float(np.trace(A))
    return {"stats": [f"Degrees of freedom for signal (trace A) = {dofs:.2f}",
                      f"Mean |smoothed − raw model| = {np.mean(np.abs(xs - xm)):.2f}‰"],
            "notes": ["Uses the first profile if the file holds several. Kernel, a priori and model profile must be "
                      "on the same pressure grid (no regridding is done here)."]}
