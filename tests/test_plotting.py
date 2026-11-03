import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from isoresearch.analysis import dataset as D
from isoresearch.plotting import catalog as C
from isoresearch.plotting.render import export_figure, render

EX = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="module")
def synth():
    ds = D.load(EX / "synthetic_rainfall_isotopes.csv")
    mapping = D.detect_roles(ds)
    return ds, mapping, D.apply_mapping(ds, mapping)


def test_example_dataset_is_marked_synthetic(synth):
    ds, mapping, df = synth
    assert ds.synthetic and "SYNTHETIC" in ds.notes[0]
    assert {"time", "precip", "d18o", "d2h", "d18o_sim", "q", "temp", "rh"} <= set(mapping)


def test_all_supported_recipes_render(synth):
    ds, mapping, df = synth
    avail = {c: int(df[c].notna().sum()) for c in df.columns}
    rendered = 0
    for spec in C.CATALOG:
        opts = C.default_options(spec)
        ok, _ = C.check_support(spec, opts, avail, set())
        if not ok:
            continue
        fig, res = render(spec, df, opts, {})
        assert isinstance(res["stats"], list)
        rendered += 1
    assert rendered >= 14


def test_missing_variables_are_reported_not_invented(synth):
    ds, mapping, df = synth
    df2 = df.drop(columns=["q"])
    avail = {c: int(df2[c].notna().sum()) for c in df2.columns}
    ok, msgs = C.check_support(C.BY_ID["q"], {"y": "d18o"}, avail, set())
    assert not ok and any("Missing variable: q" in m for m in msgs)
    ok, msgs = C.check_support(C.BY_ID["ak"], {}, avail, set())
    assert not ok


def test_plotted_values_are_exactly_the_data(synth):
    ds, mapping, df = synth
    fig, _ = render("dual", df, {}, {})
    ax = fig.axes[0]
    pts = ax.collections[0].get_offsets()
    d = df[["d18o", "d2h"]].dropna()
    assert len(pts) == len(d)
    np.testing.assert_allclose(np.sort(pts[:, 0]), np.sort(d["d18o"].values))
    np.testing.assert_allclose(np.sort(pts[:, 1]), np.sort(d["d2h"].values))


def test_gaps_are_not_interpolated():
    t = pd.date_range("2024-06-01", periods=10, freq="D")
    df = pd.DataFrame({"time": t, "precip": [5, np.nan, 7, 3, np.nan, 9, 2, 4, 6, 8],
                       "d18o": [-3, -4, np.nan, -2, -5, -6, -1, -2, -3, -4]})
    fig, res = render("lag", df, {"x": "precip", "y": "d18o", "max_lag": 2}, {})
    assert "missing days are not interpolated" in " ".join(res["notes"])


def test_export_figure_script_and_config(synth, tmp_path):
    ds, mapping, df = synth
    spec = C.BY_ID["ovs"]
    fig, res = render(spec, df, {"var": "d18o"}, {})
    out = export_figure(fig, res, spec, {"var": "d18o"}, mapping, str(ds.path), tmp_path, dpi=150,
                        synthetic=True)
    folder = Path(out["folder"])
    for f in ("figure.png", "figure.svg", "figure.pdf", "make_figure.py", "config.json", "README.txt"):
        assert (folder / f).exists() and (folder / f).stat().st_size > 0
    cfg = json.loads((folder / "config.json").read_text())
    assert cfg["data_marked_synthetic"] and cfg["mapping"] == mapping
    assert (folder / "figure.png").read_bytes()[:4] == b"\x89PNG"
    assert (folder / "figure.pdf").read_bytes()[:4] == b"%PDF"
    # the saved script reproduces the figure from the ORIGINAL data file
    r = subprocess.run([sys.executable, str(folder / "make_figure.py")], capture_output=True, text=True,
                       cwd=tmp_path, timeout=120)
    assert r.returncode == 0, r.stderr
    assert res["stats"][1] in r.stdout  # identical statistics
    assert (folder / "make_figure.png").exists()


def test_averaging_kernel_plot_from_netcdf(tmp_path):
    ds = D.load(EX / "synthetic_satellite_profiles.nc")
    ex = {"avg_kernel": ds.extras["avg_kernel"], "apriori": ds.extras["apriori"],
          "model_profile": ds.extras["model_profile"], "pressure": ds.extras["lev"]}
    fig, res = render("ak", ds.df, {}, ex)
    assert "trace A" in res["stats"][0]


def test_dataset_qc_flags_without_modifying(tmp_path):
    p = tmp_path / "obs.csv"
    pd.DataFrame({"date": ["2024-06-01", "2024-06-02", "bad"], "d18O": [-3.0, 45.0, -2.0],
                  "d2H": [-14.0, -20.0, -6.0], "rain_mm": [0.0, 5.0, 3.0]}).to_csv(p, index=False)
    before = p.read_bytes()
    ds = D.load(p)
    df = D.apply_mapping(ds, D.detect_roles(ds))
    issues = " | ".join(i["issue"] for i in D.qc_report(df))
    assert "outside the plausible range" in issues
    assert "unparseable time" in issues
    assert "zero rainfall" in issues
    assert p.read_bytes() == before
