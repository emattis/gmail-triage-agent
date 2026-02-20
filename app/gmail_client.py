from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os
import json

TOKEN_STORE_PATH = os.getenv("TOKEN_STORE_PATH", "data/token.json")

def get_gmail_service():
    if not os.path.exists(TOKEN_STORE_PATH):
        raise RuntimeError("No token found. Please authenticate first.")

    with open(TOKEN_STORE_PATH, "r") as f:
        token_data = json.load(f)

    creds = Credentials.from_authorized_user_info(token_data)
    service = build("gmail", "v1", credentials=creds)
    return service
