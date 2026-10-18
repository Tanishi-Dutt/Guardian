import json
import os
import random
import time
import anthropic

OUTPUT_FILE = "ml/transcripts.jsonl"
TARGET_COUNT = 2500

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

SCENARIOS = [
    ("scam", "IRS tax fraud demand with gift card or wire transfer payment"),
    ("scam", "Tech support remote access scam reporting virus or compromised account"),
    ("scam", "Bank fraud department security alert asking for OTP or account login"),
    ("scam", "Grandchild in jail emergency bail money scam"),
    ("scam", "Utility company immediate power/water shutoff threat"),
    ("legit", "Routine doctor appointment reminder and verification"),
    ("legit", "Customer support resolving a legitimate delivery or return issue"),
    ("legit", "Bank representative confirming a suspicious transaction that was blocked"),
    ("legit", "Pharmacy notification regarding prescription refill readiness"),
    ("legit", "ISP tech support scheduling a home technician visit")
]

SYSTEM_PROMPT = """You are a dataset generator for fine-tuning a scam detection model. 
Generate realistic phone call transcripts between a Caller and an Agent/Receiver.
Each turn must include:
- speaker: "Caller" or "Agent"
- text: full dialogue utterance
- t_seconds: cumulative time offset in seconds
- stage: one of ["none", "hook", "authority", "urgency", "isolation", "payment_or_info"]

Return ONLY a valid JSON object with the following schema:
{
  "script": "<short_identifier>",
  "label": "<scam|legit>",
  "turns": [
    {"speaker": "Caller", "text": "...", "t_seconds": 5, "stage": "hook"}
  ]
}
"""

def count_existing_records():
    if not os.path.exists(OUTPUT_FILE):
        return 0
    with open(OUTPUT_FILE, "r") as f:
        return sum(1 for line in f if line.strip())

def generate_sample(label, scenario):
    user_prompt = f"Generate a detailed call transcript for label '{label}' based on this scenario: {scenario}."
    
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1500,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}
            }
        ],
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    raw_text = response.content[0].text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
    elif raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1].split("```")[0].strip()
        
    return json.loads(raw_text)

def main():
    os.makedirs("ml", exist_ok=True)
    current_count = count_existing_records()
    print(f"Current starting count in {OUTPUT_FILE}: {current_count}/{TARGET_COUNT}")

    with open(OUTPUT_FILE, "a") as out_f:
        while current_count < TARGET_COUNT:
            label, scenario = random.choice(SCENARIOS)
            try:
                data = generate_sample(label, scenario)
                out_f.write(json.dumps(data) + "\n")
                out_f.flush()
                current_count += 1
                print(f"Progress: {current_count}/{TARGET_COUNT} generated.")
            except Exception as e:
                print(f"Error generating sample: {e}")
                time.sleep(2)

    print(f"Finished! Total transcripts in {OUTPUT_FILE}: {current_count}")

if __name__ == "__main__":
    main()