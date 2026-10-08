#!/usr/bin/env python3
"""Reproduce an explicitly truncated, four-gas kettle screening scenario.

This is not a complete cradle-to-gate LCA. All omitted providers are exported.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "kettle-lca-matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(Path(tempfile.gettempdir()) / "kettle-lca-cache"))
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

ROOT = Path(__file__).resolve().parents[1]
USLCI_COMMIT = "83f722d2c97ca784e3d258ab51ec4f6804625c1f"
USLCI_FILE = "uslci_fy25_q2_01_olca2_4_1_elci_lib_json_ld.zip"
USLCI_URL = f"https://raw.githubusercontent.com/FLCAC-admin/uslci-content/{USLCI_COMMIT}/downloads/{USLCI_FILE}"
USLCI_SHA256 = "55437502fc33d193236d50fd87a361880beea82a27139d1803be38ae0f0934b0"
TIANGONG_COMMIT = "c50cab7961e0b0ca11c26a600bd4c90fea6c6c32"
TIANGONG_BASE = f"https://raw.githubusercontent.com/tiangong-lca/data/{TIANGONG_COMMIT}/tiangong_lca_data"
CLIMATE_UUID = "6209b35f-9447-40b5-b68c-a1099e3674a0"
COPPER_UUID = "84f07e17-6318-47ba-a4d0-866068257bbd"
GRID_UUID = "0aa8c769-a04a-4e76-897a-2b1051cb9344"
THERMAL_UUID = "aef876a0-dd1f-4e00-97c5-3e59a0cfb6ac"
BOX_UUID = "b0a8d882-9859-4069-b59b-90dd19dc98a0"

PROFILE_IDS = {
    "steel": "49f5324b-fc33-36e9-b5af-3c80d73492bd",
    "zinc": "230e8d51-1f4d-3459-be47-429b0b828add",
    "PP": "2e8facf6-46aa-4ddb-95de-a4e2a00eb2bb",
    "PVC": "3dbccdda-2014-4239-ad1f-4e15c034942b",
    "ABS": "0e42a306-ee2d-362e-8bc3-580000096459",
    "LDPE": "6a12cba1-889d-4515-90f8-89feb8d662f2",
    "rubber_proxy": "fa60e60f-73f0-3e20-bb3a-073e4a9469cc",
    "cardboard": "226ed3c2-e020-4c95-b1fc-4559fc2d18ac",
}
TRUCK_UUID = "34156f3c-28ef-33db-9ad0-6293a2aa0d52"
MOLD_UUID = "89a2b59a-1ca2-34f5-acc8-a8eaaa6fa870"
MATERIAL_PROFILES = {
    "Stainless steel": ("steel", "direct", "USLCI stainless 304 flat rolled coil; actual grade unknown"),
    "Brass": ("brass", "composite proxy", "70% Tiangong primary copper direct emissions + 30% USLCI zinc; alloy process excluded"),
    "Copper": ("copper", "direct-only", "Tiangong primary copper direct climate emissions; upstream providers excluded"),
    "Polypropylene (PP)": ("PP", "direct", "USLCI virgin PP resin"),
    "Polyvinyl chloride (PVC)": ("PVC", "direct", "USLCI suspension PVC resin; grade/additives unknown"),
    "Nylon, grade unspecified": ("ABS", "proxy", "ABS resin substitutes for unspecified nylon; chemistry differs"),
    "Polyoxymethylene (POM)": ("ABS", "proxy", "ABS resin substitutes for POM; chemistry differs"),
    "Polycarbonate (PC)": ("ABS", "proxy", "ABS resin substitutes for PC; chemistry differs"),
    "Acrylonitrile-butadiene-styrene (ABS)": ("ABS", "direct", "USLCI ABS copolymer resin"),
    "Silicone": ("rubber_proxy", "proxy", "Polybutadiene rubber substitutes for silicone rubber; chemistry differs"),
    "LDPE packaging foil": ("LDPE", "proxy", "LDPE resin matches polymer; film conversion proxied separately"),
    "Cardboard packaging": ("cardboard", "proxy", "Average corrugated board and separate box conversion; board type unknown"),
}
PLASTICS = {
    "Polypropylene (PP)", "Polyvinyl chloride (PVC)", "Nylon, grade unspecified",
    "Polyoxymethylene (POM)", "Polycarbonate (PC)",
    "Acrylonitrile-butadiene-styrene (ABS)", "Silicone", "LDPE packaging foil",
}
METALS = {"Stainless steel", "Brass", "Copper"}
NS = {"p": "http://lca.jrc.it/ILCD/Process", "m": "http://lca.jrc.it/ILCD/LCIAMethod", "c": "http://lca.jrc.it/ILCD/Common"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "Kettle-LCA-reproduction"}), timeout=60) as response:
        return response.read()


def tg_file(folder: str, uuid: str, manifest: list[dict], local_root: Path | None) -> ET.Element:
    name = f"{folder}/{uuid}.xml"
    url = f"{TIANGONG_BASE}/{name}"
    path = local_root / name if local_root else None
    data = path.read_bytes() if path else download(url)
    manifest.append({"asset": name, "source_url": url, "sha256": digest(data), "bytes": len(data)})
    return ET.fromstring(data)


def tg_exchanges(root: ET.Element) -> tuple[float, list[dict]]:
    ref_id = root.findtext(".//p:quantitativeReference/p:referenceToReferenceFlow", namespaces=NS)
    rows = []
    for element in root.findall(".//p:exchanges/p:exchange", NS):
        flow = element.find("p:referenceToFlowDataSet", NS)
        if flow is None:
            continue
        rows.append({
            "id": element.get("dataSetInternalID"),
            "flow_id": flow.get("refObjectId"),
            "flow_name": flow.findtext("c:shortDescription", namespaces=NS),
            "direction": element.findtext("p:exchangeDirection", namespaces=NS),
            "amount": float(element.findtext("p:meanAmount", default="0", namespaces=NS)),
        })
    reference = next(row for row in rows if row["id"] == ref_id)
    return reference["amount"], rows


def load_tiangong(manifest: list[dict], local_root: Path | None) -> dict:
    climate = tg_file("lciamethods", CLIMATE_UUID, manifest, local_root)
    factors = {}
    names = {}
    for factor in climate.findall(".//m:characterisationFactors/m:factor", NS):
        flow = factor.find("m:referenceToFlowDataSet", NS)
        if flow is None:
            continue
        flow_id = flow.get("refObjectId")
        factors[flow_id] = float(factor.findtext("m:meanValue", namespaces=NS))
        names[flow_id] = flow.findtext("c:shortDescription", namespaces=NS) or ""
    for label, expected in [("carbon dioxide (fossil)", 1.0), ("methane (fossil)", 29.8), ("nitrous oxide", 273.0), ("sulphur hexafluoride", 25200.0)]:
        assert any(text.lower().startswith(label) and factors[key] == expected for key, text in names.items()), label
    copper = tg_file("processes", COPPER_UUID, manifest, local_root)
    copper_ref, copper_rows = tg_exchanges(copper)
    copper_direct = sum(row["amount"] * factors.get(row["flow_id"], 0.0) for row in copper_rows if row["direction"] == "Output") / copper_ref
    thermal = tg_file("processes", THERMAL_UUID, manifest, local_root)
    thermal_ref, thermal_rows = tg_exchanges(thermal)
    thermal_direct = sum(row["amount"] * factors.get(row["flow_id"], 0.0) for row in thermal_rows if row["direction"] == "Output")
    grid = tg_file("processes", GRID_UUID, manifest, local_root)
    grid_ref, grid_rows = tg_exchanges(grid)
    thermal_input = next(row["amount"] for row in grid_rows if row["direction"] == "Input" and row["flow_name"] == "electricity for thermal power")
    assert abs(thermal_ref - grid_ref) < 1e-9 and grid_ref == 3.6
    grid_direct_per_kwh = thermal_direct * thermal_input / thermal_ref
    box = tg_file("processes", BOX_UUID, manifest, local_root)
    box_ref, box_rows = tg_exchanges(box)
    box_electricity_mj_per_kg = next(row["amount"] for row in box_rows if row["direction"] == "Input" and row["flow_name"] == "Electricity") / box_ref
    return {
        "copper_direct_kgco2e_per_kg": copper_direct,
        "grid_direct_kgco2e_per_kwh": grid_direct_per_kwh,
        "box_electricity_mj_per_kg": box_electricity_mj_per_kg,
        "method_uuid": CLIMATE_UUID,
        "thermal_share": thermal_input / grid_ref,
    }


def load_uslci(path: Path, manifest: list[dict]) -> dict:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(download(USLCI_URL))
    archive_bytes = path.read_bytes()
    if digest(archive_bytes) != USLCI_SHA256:
        raise ValueError("USLCI archive SHA-256 differs from the verified source")
    manifest.append({"asset": USLCI_FILE, "source_url": USLCI_URL, "sha256": digest(archive_bytes), "bytes": len(archive_bytes)})
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        return {
            process["@id"]: process
            for name in archive.namelist()
            if name.startswith("processes/") and name.endswith(".json")
            for process in [json.loads(archive.read(name))]
        }


def gas_impact(exchange: dict) -> float:
    if exchange.get("isInput") or exchange.get("flow", {}).get("flowType") != "ELEMENTARY_FLOW":
        return 0.0
    flow = exchange["flow"]
    if "emission/air" not in flow.get("category", ""):
        return 0.0
    # USLCI's generic CO2 and CH4 names have no fossil/biogenic qualifier.
    # This explicit screening choice classifies both as fossil.
    factor = {"Carbon dioxide": 1.0, "Methane": 29.8, "Nitrous oxide": 273.0, "Sulfur hexafluoride": 25200.0}.get(flow.get("name"), 0.0)
    return float(exchange.get("amount", 0.0)) * factor


def electricity_kwh(amount: float, unit: str) -> float | None:
    scale = {"MJ": 1 / 3.6, "kWh": 1.0, "Wh": 0.001}.get(unit)
    return amount * scale if scale is not None else None


def derive_uslci_factors(processes: dict, grid_factor: float) -> tuple[dict, dict, list[dict]]:
    ids = list(processes)
    index = {uuid: i for i, uuid in enumerate(ids)}
    references = {uuid: next((e for e in process["exchanges"] if e.get("isQuantitativeReference")), None) for uuid, process in processes.items()}
    by_flow = defaultdict(list)
    for uuid, ref in references.items():
        if ref is not None:
            by_flow[ref["flow"]["@id"]].append(uuid)
    matrix = lil_matrix((len(ids), len(ids)))
    direct = np.zeros(len(ids))
    missing = defaultdict(list)
    for uuid, process in processes.items():
        col = index[uuid]
        reference = references[uuid]
        if reference is None:
            continue
        matrix[col, col] += float(reference["amount"])
        for exchange in process["exchanges"]:
            if exchange is reference:
                continue
            direct[col] += gas_impact(exchange)
            flow = exchange.get("flow", {})
            if not exchange.get("isInput") or flow.get("flowType") != "PRODUCT_FLOW":
                continue
            name = flow.get("name", "")
            unit = exchange.get("unit", {}).get("name", "")
            amount = float(exchange.get("amount", 0.0))
            if name.lower().startswith("electricity"):
                kwh = electricity_kwh(amount, unit)
                if kwh is not None:
                    direct[col] += kwh * grid_factor
                    continue
            provider = exchange.get("defaultProvider", {}).get("@id")
            if not provider:
                candidates = by_flow.get(flow.get("@id"), [])
                if len(candidates) == 1:
                    provider = candidates[0]
            provider_ref = references.get(provider)
            if provider in processes and provider_ref is not None and provider_ref["flow"]["@id"] == flow.get("@id") and provider_ref.get("unit", {}).get("name") == unit:
                sign = -1.0 if exchange.get("isAvoidedProduct") else 1.0
                matrix[index[provider], col] -= sign * amount
            else:
                missing[uuid].append({"upstream_process": process["name"], "input_flow": name, "amount_per_process": amount, "unit": unit, "reason": "no matching provider with matching unit", "avoided_product": bool(exchange.get("isAvoidedProduct"))})
    matrix = matrix.tocsr()
    factors = {}
    diagnostics = {}
    missing_rows = []
    for profile, uuid in PROFILE_IDS.items():
        demand = np.zeros(len(ids))
        demand[index[uuid]] = 1.0  # All selected reference products have mass units; demand is 1 kg.
        activity = spsolve(matrix, demand)
        if not np.all(np.isfinite(activity)):
            raise ValueError(f"Nonfinite solve for {profile}")
        factor = float(activity @ direct)
        factors[profile] = factor
        row_count = 0
        for process_uuid, rows in missing.items():
            scale = float(activity[index[process_uuid]])
            if abs(scale) < 1e-12:
                continue
            for row in rows:
                quantity = scale * row["amount_per_process"]
                if abs(quantity) < 1e-12:
                    continue
                missing_rows.append({"profile": profile, "source_process_uuid": process_uuid, "upstream_process": row["upstream_process"], "input_flow": row["input_flow"], "unlinked_amount_per_kg_product": quantity, "unit": row["unit"], "reason": row["reason"], "avoided_product": row["avoided_product"]})
                row_count += 1
        process = processes[uuid]
        reference = references[uuid]
        if reference["unit"]["name"] != "kg":
            raise ValueError(f"Reference unit for {profile} is not kg")
        diagnostics[profile] = {"process_uuid": uuid, "process_name": process["name"], "process_version": process.get("version", "unknown"), "geography": process.get("location", {}).get("name", "unknown"), "reference_amount": reference["amount"], "reference_unit": "kg", "active_processes": int(np.count_nonzero(abs(activity) > 1e-12)), "unlinked_input_rows": row_count, "direct_impact_per_process": float(direct[index[uuid]])}
    return factors, diagnostics, missing_rows


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_figure(path: Path, material_rows: list[dict], stage_rows: list[dict]) -> None:
    entries = [(row["material"], row["modeled_kgco2e"]) for row in material_rows]
    entries += [(row["stage"], row["modeled_kgco2e"]) for row in stage_rows[1:]]
    entries.sort(key=lambda item: item[1])
    names, values = zip(*entries)
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(names, values, color=["#2879b8" if name in {row["material"] for row in material_rows} else "#dd8f33" for name in names])
    ax.set_xlabel("Modeled kg CO₂e per packaged kettle")
    ax.set_title("Incomplete four-gas screening scenario; omitted providers are unquantified")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def monte_carlo(masses: dict, factors: dict, assumptions: dict, grid: float, truck: float, box_mj: float) -> dict:
    draws = assumptions["uncertainty_draws"]
    rng = np.random.default_rng(assumptions["uncertainty_seed"])
    f = {name: value * rng.triangular(0.75, 1.0, 1.25, draws) for name, value in factors.items()}
    f["copper"] = factors["copper"] * rng.triangular(1.0, 1.2, 2.0, draws)
    grid_draw = grid * rng.triangular(0.8, 1.0, 1.2, draws)
    plastic_purchase = rng.triangular(1.0, assumptions["plastic_purchase_per_finished_kg"], 1.10, draws)
    board_purchase = rng.triangular(1.0, assumptions["cardboard_purchase_per_finished_kg"], 1.10, draws)
    brass_copper = rng.uniform(0.6, 0.8, draws)
    total = np.zeros(draws)
    for material, mass in masses.items():
        profile, status, _ = MATERIAL_PROFILES[material]
        multiplier = plastic_purchase if material in PLASTICS else board_purchase if material == "Cardboard packaging" else 1.0
        factor = brass_copper * f["copper"] + (1 - brass_copper) * f["zinc"] if material == "Brass" else f[profile]
        if status == "proxy" and material != "LDPE packaging foil" and material != "Cardboard packaging":
            factor = factor * rng.triangular(0.75, 1.0, 1.75, draws)
        total += mass * multiplier * factor
    plastic_mass = sum(masses[m] for m in PLASTICS)
    metal_mass = sum(masses[m] for m in METALS)
    board_mass = masses["Cardboard packaging"]
    plastic_energy = assumptions["plastic_conversion_MJ_per_finished_kg"] / 3.6 * plastic_mass * rng.triangular(0.5, 1.0, 1.5, draws)
    metal_energy = assumptions["metal_forming_kWh_per_finished_kg"] * metal_mass * rng.triangular(0.5, 1.0, 1.5, draws)
    assembly_energy = assumptions["assembly_kWh_per_kettle"] * rng.triangular(0.5, 1.0, 2.0, draws)
    board_energy = box_mj / 3.6 * board_mass
    total += grid_draw * (plastic_energy + metal_energy + assembly_energy + board_energy)
    purchase_mass = sum(masses[m] for m in METALS) + plastic_mass * plastic_purchase + board_mass * board_purchase
    total += purchase_mass / 1000 * rng.uniform(100, 1000, draws) * truck
    first, second = float(np.mean(total[: draws // 2])), float(np.mean(total[draws // 2 :]))
    return {"draws": draws, "seed": assumptions["uncertainty_seed"], "mean": float(np.mean(total)), "median": float(np.median(total)), "p05": float(np.quantile(total, 0.05)), "p95": float(np.quantile(total, 0.95)), "half_sample_mean_relative_difference": abs(first - second) / float(np.mean(total)), "scope": "Conditional parameter and proxy scenario only; missing upstream processes and uncharacterized gases are outside this interval."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uslci-archive", type=Path, default=Path("/tmp/kettle-lca-uslci") / USLCI_FILE)
    parser.add_argument("--tiangong-root", type=Path, help="Path containing Tiangong's tiangong_lca_data directory; otherwise download pinned XML files")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    assumptions = json.loads((ROOT / "data/scenario_assumptions.json").read_text())
    with (ROOT / "data/bom.csv").open(newline="") as file:
        bom = list(csv.DictReader(file))
    masses = {row["material"]: float(row["finished_mass_g"]) / 1000 for row in bom}
    assert len(masses) == 12 and sum(masses.values()) == 0.8608
    manifest = []
    tg_root = args.tiangong_root / "tiangong_lca_data" if args.tiangong_root else None
    tiangong = load_tiangong(manifest, tg_root)
    processes = load_uslci(args.uslci_archive, manifest)
    factors, diagnostics, missing_rows = derive_uslci_factors(processes, tiangong["grid_direct_kgco2e_per_kwh"])
    factors["copper"] = tiangong["copper_direct_kgco2e_per_kg"]
    copper_fraction = assumptions["brass_copper_mass_fraction"]
    factors["brass"] = copper_fraction * factors["copper"] + (1 - copper_fraction) * factors["zinc"]
    plastic_purchase = assumptions["plastic_purchase_per_finished_kg"]
    board_purchase = assumptions["cardboard_purchase_per_finished_kg"]
    metal_purchase = assumptions["metal_purchase_per_finished_kg"]
    contribution_rows = []
    for material, mass in masses.items():
        profile, status, note = MATERIAL_PROFILES[material]
        multiplier = plastic_purchase if material in PLASTICS else board_purchase if material == "Cardboard packaging" else metal_purchase
        contribution_rows.append({"material": material, "scope": next(row["scope"] for row in bom if row["material"] == material), "finished_mass_kg": mass, "purchase_mass_kg": mass * multiplier, "profile": profile, "mapping_status": status, "factor_kgco2e_per_kg": factors[profile], "modeled_kgco2e": mass * multiplier * factors[profile], "limitations": note})
    material_total = sum(row["modeled_kgco2e"] for row in contribution_rows)
    mold = processes[MOLD_UUID]
    mold_ref = next(row for row in mold["exchanges"] if row.get("isQuantitativeReference"))
    mold_energy = sum(electricity_kwh(e["amount"], e["unit"]["name"]) for e in mold["exchanges"] if e.get("isInput") and e["flow"]["name"].lower().startswith("electricity")) / mold_ref["amount"]
    assert abs(mold_energy - assumptions["plastic_conversion_MJ_per_finished_kg"] / 3.6) < 1e-9
    truck = processes[TRUCK_UUID]
    truck_ref = next(row for row in truck["exchanges"] if row.get("isQuantitativeReference"))
    assert truck_ref["unit"]["name"] == "t*km"
    truck_direct = sum(gas_impact(row) for row in truck["exchanges"]) / truck_ref["amount"]
    grid = tiangong["grid_direct_kgco2e_per_kwh"]
    plastic_mass = sum(masses[m] for m in PLASTICS)
    metal_mass = sum(masses[m] for m in METALS)
    board_mass = masses["Cardboard packaging"]
    purchase_mass = sum(row["purchase_mass_kg"] for row in contribution_rows)
    stage_rows = [
        {"stage": "material production and proxies", "activity": purchase_mass, "activity_unit": "kg purchased material", "factor": "mixed material factors", "modeled_kgco2e": material_total},
        {"stage": "polymer and film conversion electricity", "activity": plastic_mass * mold_energy, "activity_unit": "kWh", "factor": grid, "modeled_kgco2e": plastic_mass * mold_energy * grid},
        {"stage": "metal forming electricity", "activity": metal_mass * assumptions["metal_forming_kWh_per_finished_kg"], "activity_unit": "kWh", "factor": grid, "modeled_kgco2e": metal_mass * assumptions["metal_forming_kWh_per_finished_kg"] * grid},
        {"stage": "cardboard box conversion electricity", "activity": board_mass * tiangong["box_electricity_mj_per_kg"] / 3.6, "activity_unit": "kWh", "factor": grid, "modeled_kgco2e": board_mass * tiangong["box_electricity_mj_per_kg"] / 3.6 * grid},
        {"stage": "assembly electricity", "activity": assumptions["assembly_kWh_per_kettle"], "activity_unit": "kWh", "factor": grid, "modeled_kgco2e": assumptions["assembly_kWh_per_kettle"] * grid},
        {"stage": "inbound road transport direct emissions", "activity": purchase_mass / 1000 * assumptions["inbound_road_km"], "activity_unit": "t*km", "factor": truck_direct, "modeled_kgco2e": purchase_mass / 1000 * assumptions["inbound_road_km"] * truck_direct},
    ]
    scope_rows = []
    for scope in ("Kettle", "Packaging"):
        scoped = [row for row in contribution_rows if row["scope"] == scope]
        scoped_plastic_mass = sum(masses[row["material"]] for row in scoped if row["material"] in PLASTICS)
        scoped_purchase_mass = sum(row["purchase_mass_kg"] for row in scoped)
        conversion = scoped_plastic_mass * mold_energy * grid
        if scope == "Kettle":
            conversion += metal_mass * assumptions["metal_forming_kWh_per_finished_kg"] * grid
            conversion += assumptions["assembly_kWh_per_kettle"] * grid
        else:
            conversion += board_mass * tiangong["box_electricity_mj_per_kg"] / 3.6 * grid
        materials = sum(row["modeled_kgco2e"] for row in scoped)
        transport = scoped_purchase_mass / 1000 * assumptions["inbound_road_km"] * truck_direct
        scope_rows.append({"scope": scope, "material_kgco2e": materials, "manufacturing_kgco2e": conversion, "transport_kgco2e": transport, "modeled_total_kgco2e": materials + conversion + transport})
    total = sum(row["modeled_kgco2e"] for row in stage_rows)
    assert abs(sum(row["modeled_total_kgco2e"] for row in scope_rows) - total) < 1e-10
    uncertainty = monte_carlo(masses, factors, assumptions, grid, truck_direct, tiangong["box_electricity_mj_per_kg"])
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "material_contributions.csv", contribution_rows, list(contribution_rows[0]))
    write_csv(out / "stage_contributions.csv", stage_rows, list(stage_rows[0]))
    write_csv(out / "scope_contributions.csv", scope_rows, list(scope_rows[0]))
    write_figure(out / "contributions.png", contribution_rows, stage_rows)
    write_csv(out / "unlinked_providers.csv", missing_rows, list(missing_rows[0]))
    manifest_rows = [{"asset": "data/bom.csv", "source_url": "student-supplied in conversation", "sha256": digest((ROOT / "data/bom.csv").read_bytes()), "bytes": (ROOT / "data/bom.csv").stat().st_size}, *manifest]
    write_csv(out / "source_manifest.csv", manifest_rows, list(manifest_rows[0]))
    factor_rows = [{"profile": profile, "factor_kgco2e_per_kg": value, **diagnostics.get(profile, {"process_uuid": COPPER_UUID if profile == "copper" else "composite", "process_name": "Tiangong copper direct climate emissions" if profile == "copper" else "70% copper + 30% zinc proxy", "process_version": "see source", "geography": "CN/US proxy", "reference_amount": 1, "reference_unit": "kg", "active_processes": "unknown", "unlinked_input_rows": "unknown", "direct_impact_per_process": "not applicable"})} for profile, value in factors.items()]
    write_csv(out / "process_factors.csv", factor_rows, list(factor_rows[0]))
    summary = {"run_id": assumptions["run_id"], "status": "screening scenario with incomplete upstream closure; NOT a complete factory-gate LCA", "modeled_total_kgco2e_per_packaged_kettle": total, "material_kgco2e": material_total, "manufacturing_kgco2e": sum(row["modeled_kgco2e"] for row in stage_rows[1:5]), "transport_kgco2e": stage_rows[5]["modeled_kgco2e"], "top_contributors": sorted([{"name": row["material"], "kgco2e": row["modeled_kgco2e"]} for row in contribution_rows] + [{"name": row["stage"], "kgco2e": row["modeled_kgco2e"]} for row in stage_rows[1:]], key=lambda row: row["kgco2e"], reverse=True)[:3], "bom_kettle_kg": sum(masses[row["material"]] for row in bom if row["scope"] == "Kettle"), "bom_packaging_kg": sum(masses[row["material"]] for row in bom if row["scope"] == "Packaging"), "purchased_mass_kg": purchase_mass, "implied_process_scrap_kg": purchase_mass - sum(masses.values()), "grid_direct_kgco2e_per_kwh": grid, "truck_direct_kgco2e_per_tkm": truck_direct, "uslci_unlinked_rows_across_profiles": len(missing_rows), "uncertainty": uncertainty, "checks": {"material_plus_manufacturing_plus_transport_equals_total": abs(material_total + sum(row["modeled_kgco2e"] for row in stage_rows[1:]) - total) < 1e-10, "kettle_plus_packaging_equals_total": abs(sum(row["modeled_total_kgco2e"] for row in scope_rows) - total) < 1e-10, "bom_mass_kg": sum(masses.values()), "reference_unit": "1 packaged kettle", "climate_gases_modeled": ["generic CO2 treated as fossil", "generic CH4 treated as fossil", "N2O", "SF6"], "missing_provider_impacts": "unquantified, not zero", "other_climate_flow_impacts": "unquantified, not zero"}}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"run_id": summary["run_id"], "modeled_total_kgco2e": total, "unlinked_rows": len(missing_rows), "uncertainty_p05_p95": [uncertainty["p05"], uncertainty["p95"]]}, indent=2))


if __name__ == "__main__":
    main()
