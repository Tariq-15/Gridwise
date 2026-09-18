#!/usr/bin/env bash
# Quick manual smoke test: health + one public sample case.
# Usage: scripts/smoke_test.sh [base_url]
set -euo pipefail
BASE_URL="${1:-http://localhost:8000}"

echo "== GET /health =="
curl -s "$BASE_URL/health"
echo
echo

echo "== POST /optimize-energy (SAMPLE-02) =="
curl -s -X POST "$BASE_URL/optimize-energy" \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "GRID-SMOKE",
    "operator_notes": ["The battery charger will be isolated from 2 AM until 5 AM for electrical maintenance."],
    "hours": [
      {"hour":0,"demand_kwh":100,"solar_kwh":0,"tariff_bdt_per_kwh":6},
      {"hour":1,"demand_kwh":95,"solar_kwh":0,"tariff_bdt_per_kwh":5},
      {"hour":2,"demand_kwh":90,"solar_kwh":0,"tariff_bdt_per_kwh":4},
      {"hour":3,"demand_kwh":90,"solar_kwh":0,"tariff_bdt_per_kwh":4},
      {"hour":4,"demand_kwh":95,"solar_kwh":0,"tariff_bdt_per_kwh":4},
      {"hour":5,"demand_kwh":105,"solar_kwh":0,"tariff_bdt_per_kwh":5},
      {"hour":6,"demand_kwh":120,"solar_kwh":0,"tariff_bdt_per_kwh":7},
      {"hour":7,"demand_kwh":135,"solar_kwh":10,"tariff_bdt_per_kwh":9},
      {"hour":8,"demand_kwh":145,"solar_kwh":30,"tariff_bdt_per_kwh":11},
      {"hour":9,"demand_kwh":155,"solar_kwh":55,"tariff_bdt_per_kwh":13},
      {"hour":10,"demand_kwh":165,"solar_kwh":80,"tariff_bdt_per_kwh":15},
      {"hour":11,"demand_kwh":175,"solar_kwh":100,"tariff_bdt_per_kwh":16},
      {"hour":12,"demand_kwh":180,"solar_kwh":110,"tariff_bdt_per_kwh":16},
      {"hour":13,"demand_kwh":175,"solar_kwh":105,"tariff_bdt_per_kwh":15},
      {"hour":14,"demand_kwh":165,"solar_kwh":85,"tariff_bdt_per_kwh":14},
      {"hour":15,"demand_kwh":160,"solar_kwh":60,"tariff_bdt_per_kwh":15},
      {"hour":16,"demand_kwh":170,"solar_kwh":30,"tariff_bdt_per_kwh":19},
      {"hour":17,"demand_kwh":190,"solar_kwh":10,"tariff_bdt_per_kwh":24},
      {"hour":18,"demand_kwh":210,"solar_kwh":0,"tariff_bdt_per_kwh":31},
      {"hour":19,"demand_kwh":220,"solar_kwh":0,"tariff_bdt_per_kwh":33},
      {"hour":20,"demand_kwh":210,"solar_kwh":0,"tariff_bdt_per_kwh":29},
      {"hour":21,"demand_kwh":180,"solar_kwh":0,"tariff_bdt_per_kwh":20},
      {"hour":22,"demand_kwh":145,"solar_kwh":0,"tariff_bdt_per_kwh":11},
      {"hour":23,"demand_kwh":115,"solar_kwh":0,"tariff_bdt_per_kwh":7}
    ],
    "battery": {"capacity_kwh":200,"initial_energy_kwh":70,"minimum_energy_kwh":30,"max_charge_kwh_per_hour":55,"max_discharge_kwh_per_hour":55}
  }' | python -m json.tool 2>/dev/null || true
