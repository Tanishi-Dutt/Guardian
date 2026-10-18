import os
import sys
from veri_sdk import Client

VERI_API_KEY = os.getenv("VERI_API_KEY")
DATASET_ID = os.getenv("VERI_DATASET_ID") or (sys.argv[1] if len(sys.argv) > 1 else "fa0bef3f000d")

if not VERI_API_KEY:
    raise ValueError("VERI_API_KEY environment variable is missing! Run: export VERI_API_KEY='vk_...'")

MODEL_NAME = "Qwen/Qwen2.5-1.5B-Instruct"
OUTPUT_NAME = "guardian-scam-qwen2.5-1.5b"

print("Launching fine-tuning job on Veri Studio...")
print(f"• Dataset ID: {DATASET_ID}")
print(f"• Model: {MODEL_NAME}")
print("• Target Window: ~1 min conversation analysis")

client = Client(api_key=VERI_API_KEY)

gpu_candidates = ["L4-24GB", "A10G-24GB"]

for gpu_type in gpu_candidates:
    try:
        print(f"\nAllocating GPU ({gpu_type})...")
        job = client.training_jobs.create(
            base_model=MODEL_NAME,
            dataset_id=DATASET_ID,
            output_name=OUTPUT_NAME,
            gpu_type=gpu_type,
            gpu_count=1,
            method="sft_text",
            hyperparameters={
                "n_epochs": 3,
                "batch_size": 4,
                "learning_rate": 2e-5
            }
        )
        
        job_id = getattr(job, "id", str(job))
        print(f"\nSUCCESS! Fine-tuning job launched.")
        print(f"Job ID: {job_id}")
        print(f"GPU Allocated: {gpu_type} (x1)")
        sys.exit(0)
    except Exception as e:
        print(f"Could not allocate {gpu_type}: {e}")