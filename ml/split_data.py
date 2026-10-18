import json
import os

HOLDOUT_SCRIPTS = {"utility_shutoff", "romance"}

train_samples = []
val_samples = []

with open("ml/prefixes.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        sample = json.loads(line)
        clean_sample = {"messages": sample["messages"]}
        
        if sample.get("script") in HOLDOUT_SCRIPTS:
            val_samples.append(clean_sample)
        else:
            train_samples.append(clean_sample)

with open("ml/veri_train.jsonl", "w", encoding="utf-8") as f:
    for s in train_samples:
        f.write(json.dumps(s) + "\n")

with open("ml/veri_val.jsonl", "w", encoding="utf-8") as f:
    for s in val_samples:
        f.write(json.dumps(s) + "\n")

train_size_mb = os.path.getsize("ml/veri_train.jsonl") / (1024 * 1024)
print(f"Dataset split complete: {len(train_samples)} training rows ({train_size_mb:.2f} MB).")