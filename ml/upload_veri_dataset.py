import os
import json
import time
import urllib.request
import urllib.error

VERI_API_KEY = os.getenv("VERI_API_KEY")

if not VERI_API_KEY:
    raise ValueError("VERI_API_KEY environment variable is missing! Run: export VERI_API_KEY='vk_...'")

BASE_URL = "https://api.veri.studio/v1"

def make_request(url, data=None, method="POST"):
    headers = {
        "Authorization": f"Bearer {VERI_API_KEY}",
        "Content-Type": "application/json"
    }
    json_data = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=json_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(error_body)
        except Exception:
            return e.code, {"raw_error": error_body}

def upload_dataset():
    unique_name = f"guardian-scam-train-{int(time.time())}"
    print(f"1. Creating dataset container '{unique_name}' with format 'chat'...")
    
    # Updated to 'format': 'chat'
    status, create_res = make_request(
        f"{BASE_URL}/datasets", 
        {"name": unique_name, "format": "chat"}, 
        method="POST"
    )
    print(f"   Server response (Status {status}): {create_res}")
    
    if status not in (200, 201):
        raise RuntimeError(f"Failed to create dataset container: Status {status} - {create_res}")
        
    dataset_id = None
    if isinstance(create_res, dict):
        dataset_id = create_res.get("id") or create_res.get("dataset_id")
        if not dataset_id and "dataset" in create_res and isinstance(create_res["dataset"], dict):
            dataset_id = create_res["dataset"].get("id")
            
    if not dataset_id:
        raise ValueError(f"Could not extract a valid dataset ID from server response: {create_res}")

    print(f"\nDataset container created successfully! ID: {dataset_id}")

    # 2. Read training rows
    print("2. Reading training rows from ml/veri_train.jsonl...")
    rows = []
    with open("ml/veri_train.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    # 3. Append rows in chunks of 250
    chunk_size = 250
    total_rows = len(rows)
    print(f"3. Uploading {total_rows} rows in batches of {chunk_size}...")

    for i in range(0, total_rows, chunk_size):
        chunk = rows[i:i + chunk_size]
        status, append_res = make_request(
            f"{BASE_URL}/datasets/{dataset_id}/rows",
            chunk,
            method="POST"
        )
        if status in (200, 201):
            print(f"   Uploaded rows {i + 1} to {min(i + chunk_size, total_rows)} / {total_rows} successfully.")
        else:
            raise RuntimeError(f"Error uploading batch at row {i}: Status {status} - {append_res}")

    print(f"\nDataset upload complete! Dataset ID: {dataset_id}")
    return dataset_id

if __name__ == "__main__":
    upload_dataset()