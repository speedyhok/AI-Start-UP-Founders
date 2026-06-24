# LaunchPad AI - AI Co-Founder Boardroom 

LaunchPad AI is an advanced, automated co-founder boardroom simulator that transforms a simple startup idea into an investor-grade business blueprint. Powered by **FastAPI** and the **Google Gemini API**, it runs a multi-agent system of specialized virtual co-founders who debate, research in real-time, stress-test, and synthesize your venture.

---

## 👥 Meet Your Virtual Co-Founders
The system orchestrates five AI co-founders and an auditor to build your blueprint:

*   **Incubator Director (Consultant)**: Asks clarifying questions at the start to shape the core product vision.
*   **VC Investment Analyst (Idea Validator)**: Researches market trends, calculates TAM/SAM/SOM, runs a SWOT analysis, and analyzes direct competitors.
*   **Chief Technology Officer (CTO)**: Designs the system architecture, chooses the software stack, defines API protocols, and maps out a 12-week MVP development timeline.
*   **Chief Financial Officer (CFO)**: Builds pricing tiers, calculates operating expenses, forecasts monthly burn rates, and conducts break-even calculations.
*   **Chief Marketing Officer (CMO)**: Creates target customer personas, maps out acquisition channels, and outlines pre-launch/launch GTM strategy schedules.
*   **Venture Critic (Auditor)**: Audits all other co-founders' reports to identify fatal vulnerabilities and errors in assumptions or financials.
*   **CEO (Pitcher)**: Resolves the critic's objections with active mitigations and compiles the final unified business blueprint.

---

## 🛠️ Tech Stack
*   **Backend framework**: FastAPI (Python)
*   **LLM Integration**: Google Gemini API (`gemini-2.5-flash` by default)
*   **Real-time Web Search**: Integrated DuckDuckGo search for live competitor & market data
*   **Frontend Dashboard**: Pure modern HTML/CSS/JavaScript (Glassmorphism design, Outfit & Inter typography) embedded natively in the backend

---

## 📂 Project Structure
```text
├── agents.py                 # System prompts and agent personality profiles
├── app.py                    # FastAPI server, dashboard HTML, and orchestration logic
├── test_app.py               # In-process FastAPI TestClient simulation tool
├── requirements.txt          # Python packages and dependencies
├── .gitignore                # Specifies untracked files to ignore
├── .env.example              # Environment variables template file
└── boardroom_reports/        # Directory storing individual co-founder markdown reports
```

---

## 🚀 Getting Started

### Prerequisites
*   Python 3.10 or higher installed.
*   A Gemini API Key (get one free at [Google AI Studio](https://aistudio.google.com)).

### Installation
1. Clone the repository and navigate into it:
   ```bash
   git clone https://github.com/speedyhok/AI-Start-UP-Founders.git
   cd AI-Start-UP-Founders
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   # On Windows:
   .venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Configuration
1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```
2. Open the `.env` file and replace `your_gemini_api_key_here` with your actual Google Gemini API key:
   ```env
   GEMINI_API_KEY=AIzaSy...
   GEMINI_MODEL=gemini-2.5-flash
   ```

### Running the Application
1. Start the FastAPI server:
   ```bash
   uvicorn app:app --host 127.0.0.1 --port 8000 --reload
   ```
2. Open your web browser and navigate to:
   ```text
   http://127.0.0.1:8000
   ```
3. Type in your startup idea, answer the 3 generated follow-up questions from the Incubator Director, and watch your AI co-founders build your blueprint in real time!

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
