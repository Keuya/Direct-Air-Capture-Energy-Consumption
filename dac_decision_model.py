"""Direct Air Capture as an energy-systems decision.

DAC is not a climate technology problem; it is an energy problem. Every tonne
of CO2 captured needs 1,200-2,500 kWh of energy, so WHERE you run DAC (grid
carbon intensity, power and heat price) decides both the real cost per NET
tonne removed and whether the plant removes carbon at all.

This model compares DAC pathways across host energy systems and asks the
commercial question: what does a net tonne actually cost, and where should
you build?

Anchor values from public literature (point estimates; ranges are wide):
- Liquid solvent (Carbon Engineering type): ~1,530 kWh-el + ~1,460 kWh-th
  high-grade heat (900C, today from gas) per tonne.
- Solid sorbent (Climeworks type): ~500 kWh-el + ~1,500 kWh-th LOW-grade heat
  (~100C - can come from geothermal brine or waste heat).
- Electrochemical / next-gen: ~1,300 kWh-el, no heat, early TRL.

Usage: python dac_decision_model.py   (writes charts + CSV to outputs/)
"""

import os
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = "outputs"


@dataclass(frozen=True)
class Pathway:
    name: str
    kwh_el: float          # electricity per gross tonne
    kwh_heat: float        # heat per gross tonne
    heat_grade: str        # "high" (900C) or "low" (~100C)
    maturity: str


@dataclass(frozen=True)
class HostSystem:
    name: str
    grid_gco2_kwh: float   # carbon intensity of marginal electricity
    el_usd_mwh: float      # delivered power price to industry
    low_heat_usd_mwh: float    # low-grade heat (geothermal/waste heat where cheap)
    high_heat_usd_mwh: float   # high-grade heat (gas-fired unless noted)
    high_heat_gco2_kwh: float  # emissions of high-grade heat source


PATHWAYS = [
    Pathway("Liquid solvent", 1530, 1460, "high", "commercial (1 Mt design)"),
    Pathway("Solid sorbent", 500, 1500, "low", "commercial (kt scale)"),
    Pathway("Electrochemical", 1300, 0, "none", "pilot"),
]

HOSTS = [
    #                       gCO2/kWh  el$   loheat$ hiheat$  hiheat gCO2
    HostSystem("Kenya (geothermal)",      90,  70,  15, 120, 90),   # hi-heat via electric
    HostSystem("Iceland (geo+hydro)",     28,  43,  10, 100, 28),
    HostSystem("US Gulf Coast (gas grid)",390,  60,  35,  45, 200), # cheap gas heat
    HostSystem("Coal-heavy grid",         700,  80,  45,  60, 340),
]


def evaluate(p: Pathway, h: HostSystem) -> dict:
    heat_cost = {"high": h.high_heat_usd_mwh, "low": h.low_heat_usd_mwh, "none": 0}[p.heat_grade]
    heat_co2 = {"high": h.high_heat_gco2_kwh, "low": 0.0, "none": 0.0}[p.heat_grade]

    energy_cost_gross = (p.kwh_el * h.el_usd_mwh + p.kwh_heat * heat_cost) / 1000
    emitted_t = (p.kwh_el * h.grid_gco2_kwh + p.kwh_heat * heat_co2) / 1e6
    net_fraction = 1 - emitted_t
    cost_net = energy_cost_gross / net_fraction if net_fraction > 0 else np.inf

    return {
        "pathway": p.name, "host": h.name,
        "energy cost $/t gross": round(energy_cost_gross, 0),
        "net removal fraction": round(net_fraction, 2),
        "energy cost $/t NET": round(cost_net, 0) if np.isfinite(cost_net) else np.inf,
    }


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    rows = [evaluate(p, h) for p in PATHWAYS for h in HOSTS]
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, "dac_host_matrix.csv"), index=False)
    print(df.to_string(index=False), "\n")

    # Chart 1: energy cost per NET tonne, pathway x host
    pivot = df.pivot(index="host", columns="pathway", values="energy cost $/t NET")
    pivot = pivot.replace(np.inf, np.nan)
    ax = pivot.plot(kind="bar", figsize=(10, 5.5), color=["#2b6cb0", "#38a169", "#c05621"])
    ax.set_ylabel("Energy cost per NET tonne removed (USD)")
    ax.set_title("DAC energy cost per net tonne — pathway vs host energy system")
    ax.tick_params(axis="x", rotation=15)
    ax.legend(title=None)
    for c in ax.containers:
        ax.bar_label(c, fmt="%.0f", fontsize=8)
    plt.figtext(0.99, 0.01, "Coal-heavy grid: liquid-solvent DAC removes almost nothing net",
                ha="right", fontsize=7, color="grey")
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, "cost_per_net_tonne.png"), dpi=150)

    # Chart 2: net removal fraction vs grid intensity (the "does it even work" curve)
    grid = np.linspace(0, 800, 100)
    fig, ax = plt.subplots(figsize=(9, 5))
    for p in PATHWAYS:
        heat_co2 = 200 if p.heat_grade == "high" else 0   # gas heat for high-grade
        net = 1 - (p.kwh_el * grid + p.kwh_heat * heat_co2) / 1e6
        ax.plot(grid, net * 100, label=p.name)
    for h in HOSTS:
        ax.axvline(h.grid_gco2_kwh, color="grey", lw=0.7, ls=":")
        ax.text(h.grid_gco2_kwh + 5, 5, h.name, rotation=90, fontsize=7, color="grey")
    ax.axhline(0, color="red", lw=1)
    ax.set_xlabel("Grid carbon intensity (gCO2/kWh)")
    ax.set_ylabel("Net CO2 removed per gross tonne captured (%)")
    ax.set_title("When does DAC stop removing carbon? Net removal vs grid intensity")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "net_removal_vs_grid.png"), dpi=150)

    # Chart 3: learning curve - energy cost per net tonne in Kenya, solid sorbent
    years = np.arange(2025, 2041)
    energy_decline = 0.985 ** (years - 2025)          # 1.5%/yr efficiency gain
    el_price = 70 * 0.99 ** (years - 2025)            # slow real decline
    cost = (500 * el_price + 1500 * 15) / 1000 * energy_decline / 0.955
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(years, cost, color="#38a169", lw=2)
    ax.set_ylabel("Energy cost, USD per net tonne")
    ax.set_title("Kenya solid-sorbent DAC — energy cost per net tonne, modest learning")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "kenya_learning_curve.png"), dpi=150)


if __name__ == "__main__":
    main()
