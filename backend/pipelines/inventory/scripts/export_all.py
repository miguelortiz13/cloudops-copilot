#!/usr/bin/env python3
# export_all.py — Python-based Azure Resource Graph exporter (no az CLI needed)
import os
import csv
import json
import time
from pathlib import Path
from dotenv import load_dotenv

# Load env variables from backend root .env if it exists
from _paths import BACKEND, EXPORTS, QUERIES, RAW

load_dotenv(BACKEND / ".env")

try:
    from azure.identity import ClientSecretCredential, DefaultAzureCredential
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions
except ImportError:
    print("CRITICAL: Python Azure SDK dependencies are missing. Install with: pip install azure-mgmt-resourcegraph azure-identity")
    exit(1)

# Folders relative to this script

RAW.mkdir(parents=True, exist_ok=True)
EXPORTS.mkdir(parents=True, exist_ok=True)

# Queries lists
SUMMARY_QUERIES = [
    "summary_by_type",
    "summary_by_rg",
    "summary_by_subscription",
    "summary_by_location",
    "resource_type_summary"
]

PAGED_QUERIES = [
    "resources_full",
    "resources_with_tags",
    "missing_owner",
    "missing_environment",
    "domain_networking",
    "domain_platform",
    "domain_data",
    "domain_security",
    "resources_missing_owner"
]

def get_azure_client() -> ResourceGraphClient:
    tenant_id = os.getenv("AZURE_TENANT_ID")
    client_id = os.getenv("AZURE_READER_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_READER_CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET")
    
    if tenant_id and client_id and client_secret and "PEGA_AQUI" not in client_secret:
        try:
            print("Authenticating with Service Principal...")
            cred = ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret
            )
            return ResourceGraphClient(cred)
        except Exception as e:
            print(f"Error authenticating with Service Principal: {e}. Falling back to DefaultAzureCredential.")
            
    print("Authenticating with DefaultAzureCredential...")
    cred = DefaultAzureCredential()
    return ResourceGraphClient(cred)

def run_query(client: ResourceGraphClient, query_text: str, sub_ids: list, paged: bool = False) -> list:
    results = []
    skip = 0
    page_size = 1000
    
    while True:
        try:
            request = QueryRequest(
                subscriptions=sub_ids,
                query=query_text,
                options=QueryRequestOptions(
                    result_format="ObjectArray",
                    top=page_size,
                    skip=skip
                )
            )
            response = client.resources(request)
            data = response.data if response.data else []
            results.extend(data)
            
            if not paged or len(data) < page_size:
                break
            skip += page_size
        except Exception as e:
            print(f"Error executing query: {e}")
            break
            
    return results

def save_output(name: str, data: list):
    # Save to raw/ as JSON
    json_path = RAW / f"{name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    # Save to exports/ as CSV
    csv_path = EXPORTS / f"{name}.csv"
    if data:
        keys = list(data[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
    else:
        # Create empty CSV with header if we know it, or just touch it
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            f.write("")

def main():
    print("========================================")
    print(f" Azure Resource Graph Python Extractor - {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("========================================")
    
    client = get_azure_client()
    
    # 1. Export Subscriptions List
    print("\n=== Exportando lista de suscripciones ===")
    sub_kql = "resourcecontainers | where type == 'microsoft.resources/subscriptions' | project subscriptionId, name"
    # Query with empty sub list first
    subs_raw = run_query(client, sub_kql, [], paged=False)
    
    # Write to exports/subscriptions.csv matching expected format (id, name)
    subs_formatted = []
    sub_ids = []
    for s in subs_raw:
        sub_id = s.get("subscriptionId", "")
        name = s.get("name", "")
        if sub_id:
            sub_ids.append(sub_id)
            subs_formatted.append({"id": sub_id, "name": name})
            
    sub_csv_path = EXPORTS / "subscriptions.csv"
    with open(sub_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name"])
        w.writeheader()
        w.writerows(subs_formatted)
    print(f"   ✓ {len(subs_formatted)} suscripciones -> {sub_csv_path.name}")
    
    if not sub_ids:
        # Fallback to subscription ID from environment if resourcecontainers KQL returned empty
        env_sub = os.getenv("AZURE_SUBSCRIPTION_ID")
        if env_sub:
            sub_ids = [env_sub]
            print(f"   ⚠️ Usando suscripción por defecto de variables de entorno: {env_sub}")
            with open(sub_csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["id", "name"])
                w.writeheader()
                w.writerow({"id": env_sub, "name": "Default Subscription"})
        else:
            print("❌ ERROR: No se detectaron suscripciones asociadas a las credenciales.")
            exit(1)
            
    # 2. Run Paged Queries
    print("\n=== Exportando queries con paginación ===")
    for q in PAGED_QUERIES:
        kql_file = QUERIES / f"{q}.kql"
        if not kql_file.exists():
            print(f"  ⚠️ Query file not found: {kql_file.name}")
            continue
        print(f"→ [paged] {q}")
        with open(kql_file, "r", encoding="utf-8") as f:
            kql_text = f.read()
            
        data = run_query(client, kql_text, sub_ids, paged=True)
        save_output(q, data)
        print(f"   ✓ {len(data)} recursos -> exports/{q}.csv")
        
    # 3. Run Summary Queries
    print("\n=== Exportando queries de resumen ===")
    for q in SUMMARY_QUERIES:
        kql_file = QUERIES / f"{q}.kql"
        if not kql_file.exists():
            print(f"  ⚠️ Query file not found: {kql_file.name}")
            continue
        print(f"→ [summary] {q}")
        with open(kql_file, "r", encoding="utf-8") as f:
            kql_text = f.read()
            
        data = run_query(client, kql_text, sub_ids, paged=False)
        save_output(q, data)
        print(f"   ✓ {len(data)} filas -> exports/{q}.csv")
        
    print("\n✅ Extracción completa en Python.")

if __name__ == "__main__":
    main()
