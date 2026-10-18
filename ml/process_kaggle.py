import json
import os
import random
import re

SCAM_FILE = "ml/scam.txt"
NON_SCAM_FILE = "ml/non_scam.txt"
OUTPUT_FILE = "ml/transcripts.jsonl"

def infer_stage_and_risk(text: str, is_scam: bool) -> tuple[str, float]:
    if not is_scam:
        return "none", 0.05
    
    low_text = text.lower()
    if any(k in low_text for k in ["gift card", "card number", "ssn", "wire", "pay", "account number", "money"]):
        return "payment_or_info", 0.88
    elif any(k in low_text for k in ["arrest", "police", "urgent", "immediately", "24 hours", "lawsuit"]):
        return "urgency", 0.75
    elif any(k in low_text for k in ["don't tell", "keep this secret", "hang up", "confidential"]):
        return "isolation", 0.80
    elif any(k in low_text for k in ["irs", "officer", "medicare", "bank fraud", "department", "sheriff"]):
        return "authority", 0.55
    elif any(k in low_text for k in ["calling regarding", "found an issue", "problem with"]):
        return "hook", 0.30
    
    return "none", 0.15

def parse_transcript_to_turns(raw_text: str):
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    if len(lines) <= 1:
        sentences = re.split(r'(?<=[.!?]) +', raw_text)
        lines = [s.strip() for s in sentences if s.strip()]

    turns = []
    current_time = 0

    for i, line in enumerate(lines):
        current_time += random.randint(4, 7)
        speaker = "Caller" if i % 2 == 0 else "Agent"
        
        if "caller:" in line.lower():
            speaker = "Caller"
            line = re.sub(r'(?i)caller:\s*', '', line)
        elif "receiver:" in line.lower() or "agent:" in line.lower():
            speaker = "Agent"
            line = re.sub(r'(?i)(receiver|agent):\s*', '', line)

        turns.append({
            "speaker": speaker,
            "text": line,
            "t_seconds": current_time,
            "stage": infer_stage_and_risk(line, True)[0]
        })

    return turns

def convert_kaggle_dataset():
    os.makedirs("ml", exist_ok=True)
    converted_count = 0

    with open(OUTPUT_FILE, "a") as out_f:
        if os.path.exists(SCAM_FILE):
            with open(SCAM_FILE, "r") as f:
                content = f.read().split("\n\n")
                for entry in content:
                    if not entry.strip():
                        continue
                    turns = parse_transcript_to_turns(entry)
                    if turns:
                        item = {
                            "script": "kaggle_scam_real",
                            "label": "scam",
                            "turns": turns
                        }
                        out_f.write(json.dumps(item) + "\n")
                        converted_count += 1

        if os.path.exists(NON_SCAM_FILE):
            with open(NON_SCAM_FILE, "r") as f:
                content = f.read().split("\n\n")
                for entry in content:
                    if not entry.strip():
                        continue
                    turns = parse_transcript_to_turns(entry)
                    if turns:
                        item = {
                            "script": "kaggle_legit_real",
                            "label": "legit",
                            "turns": turns
                        }
                        out_f.write(json.dumps(item) + "\n")
                        converted_count += 1

    print(f"Done! Converted {converted_count} Kaggle call transcripts into {OUTPUT_FILE}")

if __name__ == "__main__":
    convert_kaggle_dataset()