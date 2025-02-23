import jwt
import time
import httpx
import json
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, HTTPException

# Configuration
TEAM_ID = "7QM8T4XA98"
KEY_ID = "54QRS283BA"
BUNDLE_ID = "francescoparadis.Trainss"
APNS_HOST = "https://api.sandbox.push.apple.com"
PRIVATE_KEY_PATH = "AuthKey_54QRS283BA.p8"

tokens = {}
app = FastAPI()

def generate_apns_token():
    with open(PRIVATE_KEY_PATH, "r") as f:
        private_key = serialization.load_pem_private_key(
            f.read().encode(), password=None
        )
    
    now = int(time.time())
    headers = {"alg": "ES256", "kid": KEY_ID}
    payload = {"iss": TEAM_ID, "iat": now}
    
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

def send_live_activity_update(device_token: str, activity_id: str, update_payload: dict):
    token = generate_apns_token()
    url = f"{APNS_HOST}/3/device/{device_token}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "apns-topic": f"{BUNDLE_ID}.push-type.liveactivity",
        "apns-push-type": "liveactivity",
        "apns-priority": "10",
        "content-type": "application/json"
    }
    
    payload = {
        "aps": {
            "timestamp": int(time.time()),
            "event": "update",
            "content-state": {
                "ritardo": update_payload.get("ritardo"),
                "problemi": update_payload.get("problemi"),
                "programmato": update_payload.get("programmato"),
                "tracciato": update_payload.get("tracciato"),
                "prossimaStazione": update_payload.get("prossimaStazione"),
                "prossimoBinario": update_payload.get("prossimoBinario"),
                "tempoProssimaStazione": update_payload.get("tempoProssimaStazione"),
                "stazioneUltimoRilevamento": update_payload.get("stazioneUltimoRilevamento"),
                "orarioUltimoRilevamento": update_payload.get("orarioUltimoRilevamento"),
                "stazionePartenza": update_payload.get("stazionePartenza"),
                "orarioPartenza": update_payload.get("orarioPartenza"),
                "stazioneArrivo": update_payload.get("stazioneArrivo"),
                "orarioArrivo": update_payload.get("orarioArrivo")
            },
            "relevance-score": 1.0
        },
        "activity-id": activity_id
    }
    
    with httpx.Client() as client:
        response = client.post(url, headers=headers, json=payload)
    
    if response.status_code == 200:
        print("Update sent successfully")
    else:
        print(f"Failed to send update: {response.status_code}, {response.text}")

@app.post("/register-token")
def register_token(train_id: str, push_token: str):
    tokens[train_id] = push_token
    return {"status": "Token registered"}

@app.post("/update-train-activity")
def update_train_activity(data: dict):
    train_id = data.get("train_id")
    if train_id not in tokens:
        raise HTTPException(status_code=400, detail="Token not found")
    send_live_activity_update(tokens[train_id], train_id, data)
    return {"status": "Update sent"}

@app.post("/end-train-activity")
def end_train_activity(train_id: str):
    if train_id in tokens:
        del tokens[train_id]
    return {"status": "Activity ended"}
