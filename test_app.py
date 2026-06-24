# LaunchPad AI - AI Co-Founder Boardroom
# Engineered by: Mohibul Hoque (hokworks@gmail.com)
# LinkedIn: https://www.linkedin.com/in/speedymohibul
# License: MIT License

import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from fastapi.testclient import TestClient

# Ensure the current directory is in the import path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app

client = TestClient(app)

def test_generate_blueprint():
    # Verify Google API Key is present
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("\nError: GEMINI_API_KEY or GOOGLE_API_KEY is not set.")
        print("Please configure your Google API key in a .env file or export it in your terminal:")
        print("e.g. export GEMINI_API_KEY=\"AIzaSy...\"")
        sys.exit(1)

    print("Sending POST request to /api/generate-blueprint...")
    idea = "AI-Powered Check-in Tablet for Dental Clinics"
    
    response = client.post(
        "/api/generate-blueprint",
        json={
            "startup_idea": idea,
            "q1_answer": "Yes, it will be fully HIPAA compliant with AWS KMS encryption at rest, HTTPS transit, auto-logouts, and we sign Business Associate Agreements (BAAs) with all clinics.",
            "q2_answer": "Primary target is private dental practices with 1-5 dentists. Average annual customer value (ACV) to us is $3,600 ($300/mo subscription).",
            "q3_answer": "Syncs with Open Dental and Dentrix databases using a secure local windows service agent. Local backups are encrypted, and cloud backup runs nightly."
        }
    )
    
    print("Response Status Code:", response.status_code)
    
    if response.status_code == 200:
        data = response.json()
        blueprint = data.get("blueprint", "")
        with open("blueprint_output.md", "w", encoding="utf-8") as f:
            f.write(blueprint)
        print("\n--- TEST SUCCESSFUL! ---")
        print(f"Generated Blueprint Length: {len(blueprint)} characters")
        print("Blueprint written to blueprint_output.md")
        print("\nBlueprint Preview (First 500 characters):")
        print(blueprint[:500])
        print("\n------------------------")
    else:
        print("\n--- TEST FAILED! ---")
        print("Response JSON:", response.json())
        sys.exit(1)

if __name__ == "__main__":
    test_generate_blueprint()
