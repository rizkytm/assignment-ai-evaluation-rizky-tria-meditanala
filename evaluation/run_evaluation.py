"""
Jalankan 12 evaluation scenario terhadap sistem IT Helpdesk Assistant
yang sedang berjalan (POST /ask), lalu tulis hasilnya ke evaluation_results.csv.

Pemakaian:
    1. Jalankan server dulu:  uvicorn app.main:app --app-dir system --port 8000
    2. Jalankan skrip ini:     python evaluation/run_evaluation.py
"""

import csv
import time
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000/ask"
SCENARIOS_PATH = Path(__file__).parent / "evaluation_test_scenarios.csv"
RESULTS_PATH = Path(__file__).parent / "evaluation_results.csv"

MAX_ATTEMPTS = 4          # retry saat 503/429/koneksi gagal
BASE_BACKOFF_S = 3.0      # jeda antar retry (backoff eksponensial)
INTER_SCENARIO_S = 2.0    # jeda antar skenario (hindari rate limit)

# Kolom teknis yang diisi otomatis; kolom observation diisi manual setelah run.
FIELDNAMES = [
    "scenario_id", "category", "query", "intent", "status",
    "response", "http_latency_ms", "retrieval_ms", "llm_ms", "lookup_ms",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "attempts", "observation",
]


def load_scenarios() -> list:
    """Baca scenario_id, category, query (kolom lain di CSV sumber diabaikan)."""
    with open(SCENARIOS_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            {
                "scenario_id": row["scenario_id"].strip(),
                "category": row["category"].strip(),
                "query": row["query"].strip(),
            }
            for row in reader
            if row.get("scenario_id", "").strip()
        ]


def call_assistant(query: str):
    """
    Kirim satu query ke /ask dengan retry.
    Mengembalikan (payload, http_latency_ms, attempts) atau (None, None, attempts)
    jika semua percobaan gagal.
    """
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            t0 = time.perf_counter()
            resp = requests.post(BASE_URL, json={"query": query}, timeout=60)
            http_latency_ms = (time.perf_counter() - t0) * 1000

            # 5xx dari server atau badan non-JSON → anggap gagal, retry
            payload = resp.json()
            if resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
            elif payload.get("status") == "error":
                # server menangkap exception (mis. 503 Gemini) → retry
                last_err = "status=error dari server"
            else:
                return payload, http_latency_ms, attempt
        except (requests.RequestException, ValueError) as exc:
            last_err = repr(exc)

        wait = BASE_BACKOFF_S * (2 ** (attempt - 1))
        print(f"    ... percobaan {attempt} gagal ({last_err}), retry dalam {wait:.0f}s")
        time.sleep(wait)

    return None, None, MAX_ATTEMPTS


def main() -> None:
    scenarios = load_scenarios()
    print(f"Menjalankan {len(scenarios)} skenario...\n")

    rows = []
    for i, sc in enumerate(scenarios, start=1):
        print(f"[{i:02d}/{len(scenarios)}] {sc['scenario_id']} ({sc['category']})")

        payload, latency_ms, attempts = call_assistant(sc["query"])

        if payload is None:
            print("    GAGAL setelah semua retry.")
            rows.append({
                "scenario_id": sc["scenario_id"],
                "category": sc["category"],
                "query": sc["query"],
                "intent": "", "status": "FAILED_ALL_RETRIES", "response": "",
                "http_latency_ms": "", "retrieval_ms": "", "llm_ms": "",
                "lookup_ms": "", "prompt_tokens": "", "completion_tokens": "",
                "total_tokens": "", "attempts": attempts, "observation": "",
            })
        else:
            meta = payload.get("meta", {}) or {}
            print(f"    intent={payload['intent']} latency={latency_ms:.0f}ms "
                    f"tokens={meta.get('total_tokens')}")
            rows.append({
                "scenario_id": sc["scenario_id"],
                "category": sc["category"],
                "query": sc["query"],
                "intent": payload.get("intent", ""),
                "status": payload.get("status", ""),
                "response": payload.get("data", ""),
                "http_latency_ms": round(latency_ms, 1),
                "retrieval_ms": meta.get("retrieval_ms", ""),
                "llm_ms": meta.get("llm_ms", ""),
                "lookup_ms": meta.get("lookup_ms", ""),
                "prompt_tokens": meta.get("prompt_tokens", ""),
                "completion_tokens": meta.get("completion_tokens", ""),
                "total_tokens": meta.get("total_tokens", ""),
                "attempts": attempts,
                "observation": "",
            })

        if i < len(scenarios):
            time.sleep(INTER_SCENARIO_S)

    with open(RESULTS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSelesai. Hasil ditulis ke {RESULTS_PATH}")
    print("Kolom 'observation' masih kosong — isi manual setelah membaca response.")


if __name__ == "__main__":
    main()