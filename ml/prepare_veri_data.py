import json

def generate_prefixes(input_file, output_file):
    samples = []
    
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            script_type = data.get("script", "unknown")
            turns = data.get("turns", [])
            label = data.get("label", "legit")
            
            total_turns = len(turns)
            if total_turns == 0:
                continue
            
            # Sample Turn 1, Turn 2, every 2 turns thereafter, and the final turn
            checkpoints = set([1, 2])
            for t in range(4, total_turns, 2):
                checkpoints.add(t)
            checkpoints.add(total_turns)
            
            for i in sorted(list(checkpoints)):
                prefix_turns = turns[:i]
                transcript_text = "\n".join([f"{t['speaker']}: {t['text']}" for t in prefix_turns])
                
                if label == "scam":
                    risk = 0.85 if i >= 2 else 0.4
                    red_flags = ["urgency", "payment_or_info"] if i >= 2 else ["hook"]
                else:
                    risk = 0.1
                    red_flags = []
                
                last_stage = prefix_turns[-1].get("stage", "none")
                
                sample = {
                    "script": script_type,
                    "label": label,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Analyze this live call snippet for scam risk:\n{transcript_text}"
                        },
                        {
                            "role": "assistant",
                            "content": json.dumps({
                                "risk": risk,
                                "stage": last_stage,
                                "red_flags": red_flags
                            })
                        }
                    ]
                }
                samples.append(sample)
                
    with open(output_file, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")

if __name__ == "__main__":
    generate_prefixes("ml/transcripts.jsonl", "ml/prefixes.jsonl")
    print("Generated granular prefix dataset successfully!")