"""Local dataset inspection (CSV, Excel, NetCDF) — read-only.

Original files are never modified.  Every derived step (variable mapping,
derived columns, filters) is recorded in a transformation log so the analysis
can be reproduced; derived quantities are computed only on explicit request.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# canonical variable roles: (label, unit, plausible range)
ROLES: dict[str, tuple[str, str, tuple[float, float] | None]] = {
    "time": ("Time", "", None),
    "lat": ("Latitude", "°N", (-90, 90)),
    "lon": ("Longitude", "°E", (-180, 360)),
    "event_id": ("Event ID", "", None),
    "precip": ("Rainfall amount", "mm", (0, 1000)),
    "intensity": ("Rainfall intensity", "mm h⁻¹", (0, 500)),
    "temp": ("Air temperature", "°C", (-90, 60)),
    "rh": ("Relative humidity", "%", (0, 105)),
    "q": ("Specific humidity", "g kg⁻¹", (0, 40)),
    "pressure": ("Pressure", "hPa", (1, 1100)),
    "d18o": ("δ18O (observed)", "‰ VSMOW", (-60, 20)),
    "d2h": ("δ2H (observed)", "‰ VSMOW", (-450, 100)),
    "dexcess": ("d-excess (observed)", "‰", (-60, 80)),
    "d18o_sim": ("δ18O (simulated)", "‰ VSMOW", (-60, 20)),
    "d2h_sim": ("δ2H (simulated)", "‰ VSMOW", (-450, 100)),
    "dexcess_sim": ("d-excess (simulated)", "‰", (-60, 80)),
    "d18o_sat": ("δ18O (satellite)", "‰", (-60, 20)),
    "d2h_sat": ("δD / δ2H (satellite retrieval)", "‰", (-600, 100)),
    "traj_metric": ("Trajectory / moisture-transport diagnostic", "", None),
    "apriori": ("A priori profile", "‰", None),
    "model_profile": ("Model profile", "‰", None),
    "avg_kernel": ("Averaging kernel (matrix)", "", None),
}

_MOD = r"(sim|mod|model|isorsm|isogsm|wiso|echam|cosmo|wrf|lmdz|gcm|rcm)"
_SAT = r"(sat|retr|iasi|tes|airs|musica|tropomi|gosat)"
PATTERNS: list[tuple[str, str]] = [
    ("time", r"^(time|date|datetime|timestamp|day|sampling[_ ]?date|date[_ ]?time)$|date"),
    ("lat", r"^(lat|latitude|nav_lat|y)$"),
    ("lon", r"^(lon|long|longitude|nav_lon|x)$"),
    ("event_id", r"event"),
    ("d18o_sim", r"(d|δ|delta)[_ ]?18[_ ]?o.*" + _MOD + "|" + _MOD + r".*18o"),
    ("d2h_sim", r"((d|δ|delta)[_ ]?2[_ ]?h|(d|δ|delta)d(?=[_ \-]|$)|hdo).*" + _MOD + "|" + _MOD + r".*(2h|dd\b|hdo)"),
    ("dexcess_sim", r"(d[_ ]?ex|dxs|excess).*" + _MOD + "|" + _MOD + r".*(d[_ ]?ex|dxs)"),
    ("d18o_sat", r"18o.*" + _SAT + "|" + _SAT + r".*18o"),
    ("d2h_sat", r"((d|δ|delta)[_ ]?2[_ ]?h|(d|δ|delta)d(?=[_ \-]|$)|hdo).*" + _SAT + "|" + _SAT + r".*(dd|2h|hdo)"),
    ("dexcess", r"d[_ -]?ex|dxs|deuterium[_ ]?excess|^d$"),
    ("d18o", r"(d|δ|delta)[_ ]?18[_ ]?o|o18|18o"),
    ("d2h", r"(d|δ|delta)[_ ]?2[_ ]?h|^(d|δ|delta)d(?=[_ \-]|$)|delta[_ ]?d\b|2h"),
    ("intensity", r"intens|rate|mm[_ ]?h"),
    ("precip", r"precip|rain|^pr$|^tp$|amount|^p$|mm$"),
    ("temp", r"^t$|^t[_ ]|_t$|temp|t2m|^tas$|air[_ ]?t|t[_ ]?air"),
    ("rh", r"^rh|relative[_ ]?hum|humidity[_ ]?rel|hurs"),
    ("q", r"^q$|^q[_ ]|spec(ific)?[_ ]?hum|huss|^sh$|mixing"),
    ("pressure", r"^p(res|ressure|lev)?$|^lev(el)?$|plev|hpa"),
    ("traj_metric", r"traj|uptake|source|transport|ivt|moisture"),
    ("apriori", r"a[_ ]?priori|prior"),
    ("avg_kernel", r"avg[_ ]?kernel|averaging[_ ]?kernel|^ak$"),
    ("model_profile", r"model[_ ]?profile"),
]


@dataclass
class LoadedDataset:
    path: Path
    kind: str  # csv | excel | netcdf
    df: pd.DataFrame
    attrs: dict = field(default_factory=dict)  # per-column units/long names
    dims: dict = field(default_factory=dict)  # netcdf dims
    coords: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)  # multi-dimensional arrays (e.g. averaging kernels)
    sha256: str = ""
    notes: list[str] = field(default_factory=list)
    synthetic: bool = False


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load(path: Path, sheet: str | int | None = 0) -> LoadedDataset:
    path = Path(path)
    ext = path.suffix.lower()
    notes: list[str] = []
    attrs: dict = {}
    dims: dict = {}
    coords: dict = {}
    extras: dict = {}
    synthetic = False
    if ext in (".csv", ".txt", ".tsv"):
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            head = [fh.readline() for _ in range(5)]
        comment_lines = [h for h in head if h.startswith("#")]
        synthetic = any("synthetic" in h.lower() for h in comment_lines)
        sep = "\t" if ext == ".tsv" or head[len(comment_lines)].count("\t") > head[len(comment_lines)].count(",") else ","
        df = pd.read_csv(path, sep=sep, comment="#", encoding="utf-8-sig")
        kind = "csv"
    elif ext in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl" if ext != ".xls" else None)
        kind = "excel"
    elif ext in (".nc", ".nc4", ".netcdf", ".cdf"):
        import xarray as xr

        with xr.open_dataset(path, decode_times=True) as ds:
            ds = ds.load()
        synthetic = "synthetic" in json.dumps({k: str(v) for k, v in ds.attrs.items()}).lower()
        dims = {k: int(v) for k, v in ds.sizes.items()}
        coords = {k: {"dims": list(ds[k].dims), "units": str(ds[k].attrs.get("units", "")),
                      "min": _safe_minmax(ds[k].values)[0], "max": _safe_minmax(ds[k].values)[1]}
                  for k in ds.coords}
        for v in ds.data_vars:
            attrs[v] = {"units": str(ds[v].attrs.get("units", "")),
                        "long_name": str(ds[v].attrs.get("long_name", "")), "dims": list(ds[v].dims)}
        # 1-D variables along the main dimension become table columns; higher-dim are kept as extras.
        main = max(dims, key=lambda d: dims[d]) if dims else None
        one_d = [v for v in ds.data_vars if ds[v].ndim <= 1]
        multi = [v for v in ds.data_vars if ds[v].ndim > 1]
        if one_d and main:
            same = [v for v in one_d if ds[v].dims == (main,)]
            df = ds[same].to_dataframe().reset_index() if same else pd.DataFrame()
        else:
            df = pd.DataFrame()
        for v in multi:
            extras[v] = ds[v].values
            notes.append(f"Variable '{v}' has dims {ds[v].dims}; kept as an array (not tabulated).")
        for v in one_d:
            if main and ds[v].dims != (main,):
                extras[v] = ds[v].values
        for c in ds.coords:
            if ds[c].ndim == 1:
                extras.setdefault(c, ds[c].values)
        kind = "netcdf"
    else:
        raise ValueError(f"Unsupported file type '{ext}'. Use CSV, Excel (.xlsx) or NetCDF (.nc).")
    df.columns = [str(c).strip() for c in df.columns]
    if synthetic:
        notes.insert(0, "This file is marked SYNTHETIC — values are not real observations.")
    return LoadedDataset(path, kind, df, attrs, dims, coords, extras, file_sha(path), notes, synthetic)


def _safe_minmax(a) -> tuple[str, str]:
    try:
        a = np.asarray(a)
        if a.size == 0:
            return "", ""
        return str(np.nanmin(a)), str(np.nanmax(a))
    except Exception:  # noqa: BLE001
        return "", ""


def detect_roles(ds: LoadedDataset) -> dict[str, str]:
    """Guess role → column.  Only a *suggestion*; the user confirms or edits it."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    cols = list(ds.df.columns) + [k for k in ds.extras if k not in ds.df.columns]
    for role, pat in PATTERNS:
        rx = re.compile(pat, re.I)
        for c in cols:
            if c in used:
                continue
            long_name = ds.attrs.get(c, {}).get("long_name", "")
            if rx.search(c) or (long_name and rx.search(long_name)):
                if role in ROLES and ROLES[role][2] and c in ds.df.columns:
                    s = pd.to_numeric(ds.df[c], errors="coerce").dropna()
                    lo, hi = ROLES[role][2]
                    # judge by the median so that a few bad values (which QC will flag) do not hide a column
                    if len(s) and not (lo <= float(s.median()) <= hi):
                        continue
                mapping[role] = c
                used.add(c)
                break
    if "time" not in mapping:
        for c in ds.df.columns:
            if c in used:
                continue
            if pd.api.types.is_datetime64_any_dtype(ds.df[c]):
                mapping["time"] = c
                break
    return mapping


def apply_mapping(ds: LoadedDataset, mapping: dict[str, str]) -> pd.DataFrame:
    """Return a *copy* with canonical column names (original data untouched)."""
    out = pd.DataFrame(index=ds.df.index)
    for role, col in mapping.items():
        if col in ds.df.columns:
            out[role] = ds.df[col]
    if "time" in out:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
    for role in out.columns:
        if role not in ("time", "event_id"):
            out[role] = pd.to_numeric(out[role], errors="coerce")
    return out


def summary(ds: LoadedDataset) -> dict:
    df = ds.df
    cols = []
    for c in df.columns:
        s = df[c]
        info = {"column": c, "dtype": str(s.dtype), "missing": int(s.isna().sum()),
                "missing_pct": round(100 * s.isna().mean(), 1) if len(s) else 0.0,
                "units": ds.attrs.get(c, {}).get("units", "")}
        is_dt = pd.api.types.is_datetime64_any_dtype(s)
        num = None if is_dt else pd.to_numeric(s, errors="coerce")
        if num is not None and num.notna().sum() > 0:
            info.update(min=float(num.min()), max=float(num.max()), mean=float(num.mean()),
                        std=float(num.std()) if num.notna().sum() > 1 else 0.0, n=int(num.notna().sum()))
        cols.append(info)
    cov = {}
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]) or re.search("date|time", c, re.I):
            t = pd.to_datetime(df[c], errors="coerce").dropna()
            if len(t):
                cov[c] = {"start": str(t.min()), "end": str(t.max()), "n": int(len(t))}
    return {"rows": int(len(df)), "columns": cols, "time_coverage": cov, "dims": ds.dims, "coords": ds.coords,
            "notes": ds.notes}


def qc_report(df: pd.DataFrame) -> list[dict]:
    """Quality-control checks on a mapped (canonical) frame.  Flags only — nothing is altered."""
    issues = []
    for role in df.columns:
        if role not in ROLES or role in ("time", "event_id"):
            continue
        s = df[role]
        rng = ROLES[role][2]
        miss = int(s.isna().sum())
        if miss:
            issues.append({"severity": "info", "variable": role, "issue": f"{miss} missing value(s)"})
        if rng:
            bad = s[(s < rng[0]) | (s > rng[1])]
            if len(bad):
                issues.append({"severity": "warning", "variable": role,
                               "issue": f"{len(bad)} value(s) outside the plausible range {rng} {ROLES[role][1]}"})
        if s.notna().sum() > 8:
            z = (s - s.mean()) / (s.std() or 1)
            out = int((z.abs() > 4).sum())
            if out:
                issues.append({"severity": "info", "variable": role, "issue": f"{out} value(s) beyond 4σ (check, do not delete automatically)"})
    if "time" in df:
        t = df["time"]
        if t.isna().any():
            issues.append({"severity": "warning", "variable": "time", "issue": f"{int(t.isna().sum())} unparseable time stamp(s)"})
        dup = int(t.dropna().duplicated().sum())
        if dup:
            issues.append({"severity": "info", "variable": "time", "issue": f"{dup} duplicated time stamp(s) (several samples per time?)"})
        if t.dropna().is_monotonic_increasing is False:
            issues.append({"severity": "info", "variable": "time", "issue": "time stamps are not sorted"})
    if {"d18o", "d2h"} <= set(df.columns):
        d = df["d2h"] - 8 * df["d18o"]
        if "dexcess" in df:
            diff = (df["dexcess"] - d).abs()
            nbad = int((diff > 0.5).sum())
            if nbad:
                issues.append({"severity": "warning", "variable": "dexcess",
                               "issue": f"{nbad} row(s) where d-excess ≠ δ2H − 8·δ18O by > 0.5‰"})
        low = int((d < -10).sum())
        if low:
            issues.append({"severity": "info", "variable": "d-excess",
                           "issue": f"{low} sample(s) with d < −10‰ (strong evaporation or analysis issue?)"})
    if "precip" in df and (df["precip"] == 0).any() and {"d18o"} <= set(df.columns):
        z = int(((df["precip"] == 0) & df["d18o"].notna()).sum())
        if z:
            issues.append({"severity": "warning", "variable": "precip",
                           "issue": f"{z} isotope value(s) reported with zero rainfall"})
    if not issues:
        issues.append({"severity": "ok", "variable": "—", "issue": "No problems detected by the automatic checks."})
    return issues


class TransformLog:
    """In-memory reproducible record of what was done to a dataset."""

    def __init__(self, source: Path, sha: str):
        self.entries: list[dict] = [{"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": "load",
                                     "params": {"file": str(source), "sha256": sha}}]

    def add(self, action: str, **params) -> None:
        self.entries.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, "params": params})

    def as_text(self) -> str:
        return "\n".join(f"{e['time']}  {e['action']}  {json.dumps(e['params'], ensure_ascii=False, default=str)}"
                         for e in self.entries)


def derive_dexcess(df: pd.DataFrame, suffix: str = "") -> pd.Series:
    """d = δ2H − 8·δ18O (Dansgaard, 1964).  Computed only on explicit user request."""
    return df[f"d2h{suffix}"] - 8.0 * df[f"d18o{suffix}"]
