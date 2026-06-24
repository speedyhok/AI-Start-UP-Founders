# LaunchPad AI - AI Co-Founder Boardroom
# Engineered by: Mohibul Hoque (hokworks@gmail.com)
# LinkedIn: https://www.linkedin.com/in/speedymohibul
# License: MIT License

import os
import logging
import asyncio
import httpx
import re
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from agents import (
    CONSULTANT_SYSTEM_PROMPT,
    IDEA_VALIDATOR_SYSTEM_PROMPT,
    CFO_SYSTEM_PROMPT,
    CTO_SYSTEM_PROMPT,
    CMO_SYSTEM_PROMPT,
    CRITIC_SYSTEM_PROMPT,
    PITCHER_SYSTEM_PROMPT
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Startup Cofounder Agent System",
    description="FastAPI backend powered by local Ollama model",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateBlueprintRequest(BaseModel):
    startup_idea: str
    q1_answer: str = ""
    q2_answer: str = ""
    q3_answer: str = ""

class GenerateBlueprintResponse(BaseModel):
    blueprint: str

# Retrieve Google API config from environment variables
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

async def call_gemini(system_prompt: str, user_prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("Google API key is missing. Please set GEMINI_API_KEY or GOOGLE_API_KEY environment variable.")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7
        }
    }
    
    max_retries = 4
    retry_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Invoking Gemini model '{GEMINI_MODEL}' (Attempt {attempt+1}/{max_retries})...")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        logger.warning("Gemini API Rate Limit (429) hit. Waiting 15s to clear limit window...")
                        await asyncio.sleep(15.0)
                        continue
                elif response.status_code == 503:
                    if attempt < max_retries - 1:
                        logger.warning(f"Gemini API high load (503). Retrying in {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                if response.status_code != 200:
                    logger.error(f"Gemini API returned error {response.status_code}: {response.text}")
                response.raise_for_status()
                data = response.json()
                
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError) as e:
                    logger.error(f"Failed to parse Gemini response: {data}")
                    raise RuntimeError("Invalid response structure from Gemini API") from e
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            if attempt == max_retries - 1:
                raise e
            logger.warning(f"Connection error: {e}. Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
            retry_delay *= 2
            
    raise RuntimeError("Gemini API call failed after multiple retries")

async def search_duckduckgo(query: str, max_results: int = 5) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = "https://lite.duckduckgo.com/lite/"
    try:
        logger.info(f"Searching DuckDuckGo Lite for: '{query}'")
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, data={"q": query}, headers=headers)
            if response.status_code != 200:
                logger.warning(f"DuckDuckGo Lite returned status code {response.status_code}")
                return "No search results found (search service unavailable)."
            
            html = response.text
            snippets = re.findall(r"<td class='result-snippet'[^>]*>(.*?)</td>", html, re.DOTALL)
            results = []
            for i, snippet in enumerate(snippets[:max_results]):
                clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                clean_snippet = clean_snippet.replace("&#x27;", "'").replace("&quot;", '"').replace("&amp;", "&")
                clean_snippet = " ".join(clean_snippet.split())
                results.append(f"{i+1}. {clean_snippet}")
            
            if results:
                logger.info(f"Successfully retrieved {len(results)} search snippets from DuckDuckGo Lite.")
                return "\n".join(results)
            return "No search results found."
    except Exception as e:
        logger.warning(f"Failed to fetch DuckDuckGo Lite search results: {e}")
        return "Search failed or search service unavailable."

@app.post("/api/generate-blueprint", response_model=GenerateBlueprintResponse)
async def generate_blueprint(request: GenerateBlueprintRequest):
    logger.info(f"Received blueprint request for startup idea: {request.startup_idea}")
    startup_idea = request.startup_idea
    
    # Construct user answer context
    consultation_context = ""
    if request.q1_answer or request.q2_answer or request.q3_answer:
        consultation_context = "=== User Clarifying Answers ===\n"
        if request.q1_answer:
            consultation_context += f"Q1 Answer: {request.q1_answer}\n"
        if request.q2_answer:
            consultation_context += f"Q2 Answer: {request.q2_answer}\n"
        if request.q3_answer:
            consultation_context += f"Q3 Answer: {request.q3_answer}\n"
        consultation_context += "\n"

    try:
        os.makedirs("boardroom_reports", exist_ok=True)

        # Step 1: Validator Search & Run
        val_comp_query = f"{startup_idea} direct competitors companies startups"
        val_market_query = f"{startup_idea} market size revenue statistics growth funding"
        val_comp_results = await search_duckduckgo(val_comp_query)
        val_market_results = await search_duckduckgo(val_market_query)
        validator_search_context = f"=== Competitor Search Context ===\n{val_comp_results}\n\n=== Market Sizing Search Context ===\n{val_market_results}"
        
        logger.info("Step 1: Running IdeaValidator Agent...")
        validator_user_prompt = (
            f"Startup Idea: {startup_idea}\n\n"
            f"{consultation_context}"
            f"Search Context (real-time web search results):\n{validator_search_context}\n\n"
            f"Please write your analysis report on viability, market size, and competitors."
        )
        validator_report = await call_gemini(IDEA_VALIDATOR_SYSTEM_PROMPT, validator_user_prompt)
        with open("boardroom_reports/1_idea_validator.md", "w", encoding="utf-8") as f:
            f.write(validator_report)

        # Step 2: CTO Search & Run
        cto_stack_query = f"{startup_idea} tech stack architecture databases APIs"
        cto_compliance_query = f"{startup_idea} regulatory compliance HIPAA GDPR SOC2 PCI"
        cto_stack_results = await search_duckduckgo(cto_stack_query)
        cto_compliance_results = await search_duckduckgo(cto_compliance_query)
        cto_search_context = f"=== Technical Stack Search Context ===\n{cto_stack_results}\n\n=== Compliance & Security Search Context ===\n{cto_compliance_results}"

        logger.info("Step 2: Running CTO Agent...")
        cto_user_prompt = (
            f"Startup Idea: {startup_idea}\n\n"
            f"{consultation_context}"
            f"Search Context (real-time web search results):\n{cto_search_context}\n\n"
            f"Here is the market viability & competitor report from our Idea Validator co-founder:\n"
            f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
            f"Please write your technical architecture and 3-month MVP timeline report, ensuring it addresses any market constraints or competitive features outlined by the Idea Validator."
        )
        cto_report = await call_gemini(CTO_SYSTEM_PROMPT, cto_user_prompt)
        with open("boardroom_reports/2_cto.md", "w", encoding="utf-8") as f:
            f.write(cto_report)

        # Step 3: CFO Search & Run
        cfo_pricing_query = f"{startup_idea} pricing model subscription tier costs"
        cfo_hosting_query = "AWS RDS Postgres EC2 Stripe transaction pricing startup costs"
        cfo_pricing_results = await search_duckduckgo(cfo_pricing_query)
        cfo_hosting_results = await search_duckduckgo(cfo_hosting_query)
        cfo_search_context = f"=== Industry Pricing Search Context ===\n{cfo_pricing_results}\n\n=== Operational/Hosting Cost Search Context ===\n{cfo_hosting_results}"

        logger.info("Step 3: Running CFO Agent...")
        cfo_user_prompt = (
            f"Startup Idea: {startup_idea}\n\n"
            f"{consultation_context}"
            f"Search Context (real-time web search results):\n{cfo_search_context}\n\n"
            f"Here are the reports from our co-founders:\n"
            f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
            f"--- CTO REPORT ---\n{cto_report}\n\n"
            f"Please write your financial model, pricing tiers, and runway estimation report. Ensure the monthly burn rate incorporates the stack costs, tools, compliance costs, and timelines suggested by the CTO, and the pricing fits the validator's market expectations."
        )
        cfo_report = await call_gemini(CFO_SYSTEM_PROMPT, cfo_user_prompt)
        with open("boardroom_reports/3_cfo.md", "w", encoding="utf-8") as f:
            f.write(cfo_report)

        # Step 4: CMO Search & Run
        cmo_gtm_query = f"{startup_idea} marketing channels customer acquisition GTM strategy"
        cmo_audience_query = f"{startup_idea} target customer buyer persona demographics"
        cmo_gtm_results = await search_duckduckgo(cmo_gtm_query)
        cmo_audience_results = await search_duckduckgo(cmo_audience_query)
        cmo_search_context = f"=== GTM & Growth Search Context ===\n{cmo_gtm_results}\n\n=== Target Persona Search Context ===\n{cmo_audience_results}"

        logger.info("Step 4: Running CMO Agent...")
        cmo_user_prompt = (
            f"Startup Idea: {startup_idea}\n\n"
            f"{consultation_context}"
            f"Search Context (real-time web search results):\n{cmo_search_context}\n\n"
            f"Here are the reports from our co-founders:\n"
            f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
            f"--- CTO REPORT ---\n{cto_report}\n\n"
            f"--- CFO REPORT ---\n{cfo_report}\n\n"
            f"Please write your target audience analysis and go-to-market strategy report, making sure it aligns with the product design, pricing tiers, and runway constraints established by the team."
        )
        cmo_report = await call_gemini(CMO_SYSTEM_PROMPT, cmo_user_prompt)
        with open("boardroom_reports/4_cmo.md", "w", encoding="utf-8") as f:
            f.write(cmo_report)

        # Step 5: Run Venture Critic
        logger.info("Step 5: Running Venture Critic Agent...")
        critic_user_prompt = (
            f"Startup Idea: {startup_idea}\n\n"
            f"{consultation_context}"
            f"Here are the reports generated by the startup co-founders:\n"
            f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
            f"--- CTO REPORT ---\n{cto_report}\n\n"
            f"--- CFO REPORT ---\n{cfo_report}\n\n"
            f"--- CMO REPORT ---\n{cmo_report}\n\n"
            f"Analyze these reports, audit their assumptions, verify if the numbers align, and list all fatal vulnerabilities and required corrections as instructed."
        )
        critic_report = await call_gemini(CRITIC_SYSTEM_PROMPT, critic_user_prompt)
        with open("boardroom_reports/5_venture_critic.md", "w", encoding="utf-8") as f:
            f.write(critic_report)

        # Step 6: Run Pitcher Agent to Synthesize the Blueprint
        logger.info("Step 6: Running Pitcher/Orchestrator to synthesize final blueprint...")
        pitcher_user_prompt = (
            f"You are the CEO. Synthesize the reports below into a single, cohesive, highly detailed Startup Blueprint.\n\n"
            f"You MUST use this exact structure of Markdown headers:\n"
            f"# [Startup Name] - Investor Pitch & Business Blueprint\n"
            f"## Executive Summary\n"
            f"## 1. Market Opportunity & Competitor Analysis\n"
            f"### SWOT Analysis\n"
            f"### Competitive Landscape\n"
            f"### Market Sizing (TAM, SAM, SOM) & KPIs\n"
            f"### Risk Rating & Initial Assessment\n"
            f"## 2. Product Stack & Technical MVP Timeline\n"
            f"### Technology Stack & API Protocols\n"
            f"### Compliance & Security Strategy\n"
            f"### 12-Week MVP Timeline\n"
            f"## 3. Financial Model, Pricing & Runway\n"
            f"### Pricing Tiers\n"
            f"### Detailed Operating Expenses & Monthly Burn Breakdown\n"
            f"### Runway & Break-Even Math\n"
            f"## 4. Go-To-Market & Growth Strategy\n"
            f"### Target Customer Persona Profile\n"
            f"### Customer Acquisition Channels\n"
            f"### Pre-Launch & Launch Schedule\n"
            f"## 5. Risk Assessment & Critic Response\n"
            f"### Venture Critic\'s Audit (Fatal Vulnerabilities & Required Corrections)\n"
            f"### Critic\'s Objections & Completed Mitigations\n"
            f"## Conclusion & Funding Requirements\n"
            f"### Confidence Scores & Action Items Summary\n\n"
            f"CRITICAL: Under \'### Critic\'s Objections & Completed Mitigations\', you must list each of the Critic\'s objections and write active, present-tense, completed mitigations (e.g. \'We have adjusted MoM growth rate to 12% to ensure sustainable scaling\', \'We have optimized AWS hosting costs to $1,500/mo by utilizing local SQLite sync caching\'). Do NOT say \'we will do it\' or leave them unmitigated.\n\n"
            f"CRITICAL: Replace \'[Startup Name]\' in the header and throughout the document with the actual startup/company name analyzed or invented in the validator\'s report. Do NOT leave \'[Startup Name]\' in the output.\n\n"
            f"CRITICAL: Under \'### Confidence Scores & Action Items Summary\', compile and list all the Confidence Scores and Action Items from each of the co-founder reports separately, grouped by co-founder, keeping their original scores.\n\n"
            f"Here are the reports:\n"
            f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
            f"--- CTO REPORT ---\n{cto_report}\n\n"
            f"--- CFO REPORT ---\n{cfo_report}\n\n"
            f"--- CMO REPORT ---\n{cmo_report}\n\n"
            f"--- VENTURE CRITIC REPORT ---\n{critic_report}\n\n"
            f"Output the complete, unified, highly detailed Markdown document according to the required headers, ensuring you replace any remaining bracket placeholders with real details."
        )
        blueprint_text = await call_gemini(PITCHER_SYSTEM_PROMPT, pitcher_user_prompt)

        # Write to blueprint_output.md
        with open("blueprint_output.md", "w", encoding="utf-8") as f:
            f.write(blueprint_text)
        with open("boardroom_reports/6_pitcher_blueprint.md", "w", encoding="utf-8") as f:
            f.write(blueprint_text)
        logger.info("Blueprint successfully written to blueprint_output.md and boardroom_reports/6_pitcher_blueprint.md")

        return GenerateBlueprintResponse(blueprint=blueprint_text)

    except Exception as e:
        logger.exception("Error during blueprint generation")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while generating the blueprint: {str(e)}"
        )

@app.get("/api/consult")
async def consult(startup_idea: str = Query(..., description="The startup idea")):
    try:
        logger.info(f"Generating consultation questions for idea: {startup_idea}")
        response = await call_gemini(CONSULTANT_SYSTEM_PROMPT, f"Startup Idea: {startup_idea}")
        
        # Clean response of markdown code block wrapper if present
        clean_response = response.strip()
        if clean_response.startswith("```"):
            lines = clean_response.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_response = "\n".join(lines).strip()
            
        questions = json.loads(clean_response)
        if not isinstance(questions, list) or len(questions) != 3:
            raise ValueError("Response is not a list of 3 elements")
        
        # Make sure they are strings
        questions = [str(q) for q in questions]
        return {"questions": questions}
    except Exception as e:
        logger.exception("Error generating consultation questions")
        return {
            "questions": [
                "What is your target customer segment and their primary pain point?",
                "What is your initial budget/funding runway to build the MVP?",
                "Do you have any unfair distribution advantages or proprietary IP?"
            ]
        }

@app.get("/api/generate-blueprint-stream")
async def generate_blueprint_stream(
    startup_idea: str = Query(..., description="The startup idea to generate a blueprint for"),
    q1_answer: str = Query("", description="Answer to question 1"),
    q2_answer: str = Query("", description="Answer to question 2"),
    q3_answer: str = Query("", description="Answer to question 3")
):
    logger.info(f"Received streaming blueprint request for: {startup_idea}")
    
    # Construct user answer context
    consultation_context = ""
    if q1_answer or q2_answer or q3_answer:
        consultation_context = "=== User Clarifying Answers ===\n"
        if q1_answer:
            consultation_context += f"Q1 Answer: {q1_answer}\n"
        if q2_answer:
            consultation_context += f"Q2 Answer: {q2_answer}\n"
        if q3_answer:
            consultation_context += f"Q3 Answer: {q3_answer}\n"
        consultation_context += "\n"

    async def event_generator():
        try:
            os.makedirs("boardroom_reports", exist_ok=True)

            # Step 1: Validator Search
            yield f"data: {json.dumps({'status': 'search', 'message': 'Idea Validator searching for competitors & market sizing...'})}\n\n"
            val_comp_query = f"{startup_idea} direct competitors companies startups"
            val_market_query = f"{startup_idea} market size revenue statistics growth funding"
            val_comp_results = await search_duckduckgo(val_comp_query)
            val_market_results = await search_duckduckgo(val_market_query)
            validator_search_context = f"=== Competitor Search Context ===\n{val_comp_results}\n\n=== Market Sizing Search Context ===\n{val_market_results}"
            await asyncio.sleep(0.3)

            # Step 2: Run IdeaValidator Agent
            yield f"data: {json.dumps({'status': 'validator', 'message': 'Idea Validator analyzing viability, competitors, and market...' })}\n\n"
            validator_user_prompt = (
                f"Startup Idea: {startup_idea}\n\n"
                f"{consultation_context}"
                f"Search Context (real-time web search results):\n{validator_search_context}\n\n"
                f"Please write your analysis report on viability, market size, and competitors."
            )
            validator_report = await call_gemini(IDEA_VALIDATOR_SYSTEM_PROMPT, validator_user_prompt)
            with open("boardroom_reports/1_idea_validator.md", "w", encoding="utf-8") as f:
                f.write(validator_report)

            # Step 3: CTO Search
            yield f"data: {json.dumps({'status': 'search', 'message': 'CTO searching for modern stacks & compliance guidelines...'})}\n\n"
            cto_stack_query = f"{startup_idea} tech stack architecture databases APIs"
            cto_compliance_query = f"{startup_idea} regulatory compliance HIPAA GDPR SOC2 PCI"
            cto_stack_results = await search_duckduckgo(cto_stack_query)
            cto_compliance_results = await search_duckduckgo(cto_compliance_query)
            cto_search_context = f"=== Technical Stack Search Context ===\n{cto_stack_results}\n\n=== Compliance & Security Search Context ===\n{cto_compliance_results}"
            await asyncio.sleep(0.3)

            # Step 4: Run CTO Agent (receives Validator report)
            yield f"data: {json.dumps({'status': 'cto', 'message': 'CTO designing software stack and MVP timeline...' })}\n\n"
            cto_user_prompt = (
                f"Startup Idea: {startup_idea}\n\n"
                f"{consultation_context}"
                f"Search Context (real-time web search results):\n{cto_search_context}\n\n"
                f"Here is the market viability & competitor report from our Idea Validator co-founder:\n"
                f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
                f"Please write your technical architecture and 3-month MVP timeline report, ensuring it addresses any market constraints or competitive features outlined by the Idea Validator."
            )
            cto_report = await call_gemini(CTO_SYSTEM_PROMPT, cto_user_prompt)
            with open("boardroom_reports/2_cto.md", "w", encoding="utf-8") as f:
                f.write(cto_report)

            # Step 5: CFO Search
            yield f"data: {json.dumps({'status': 'search', 'message': 'CFO searching for pricing models & server hosting costs...'})}\n\n"
            cfo_pricing_query = f"{startup_idea} pricing model subscription tier costs"
            cfo_hosting_query = "AWS RDS Postgres EC2 Stripe transaction pricing startup costs"
            cfo_pricing_results = await search_duckduckgo(cfo_pricing_query)
            cfo_hosting_results = await search_duckduckgo(cfo_hosting_query)
            cfo_search_context = f"=== Industry Pricing Search Context ===\n{cfo_pricing_results}\n\n=== Operational/Hosting Cost Search Context ===\n{cfo_hosting_results}"
            await asyncio.sleep(0.3)

            # Step 6: Run CFO Agent (receives Validator & CTO reports)
            yield f"data: {json.dumps({'status': 'cfo', 'message': 'CFO building pricing, operational expenses, and runway model...' })}\n\n"
            cfo_user_prompt = (
                f"Startup Idea: {startup_idea}\n\n"
                f"{consultation_context}"
                f"Search Context (real-time web search results):\n{cfo_search_context}\n\n"
                f"Here are the reports from our co-founders:\n"
                f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
                f"--- CTO REPORT ---\n{cto_report}\n\n"
                f"Please write your financial model, pricing tiers, and runway estimation report. Ensure the monthly burn rate incorporates the stack costs, tools, compliance costs, and timelines suggested by the CTO, and the pricing fits the validator's market expectations."
            )
            cfo_report = await call_gemini(CFO_SYSTEM_PROMPT, cfo_user_prompt)
            with open("boardroom_reports/3_cfo.md", "w", encoding="utf-8") as f:
                f.write(cfo_report)

            # Step 7: CMO Search
            yield f"data: {json.dumps({'status': 'search', 'message': 'CMO searching for go-to-market strategies & acquisition funnels...'})}\n\n"
            cmo_gtm_query = f"{startup_idea} marketing channels customer acquisition GTM strategy"
            cmo_audience_query = f"{startup_idea} target customer buyer persona demographics"
            cmo_gtm_results = await search_duckduckgo(cmo_gtm_query)
            cmo_audience_results = await search_duckduckgo(cmo_audience_query)
            cmo_search_context = f"=== GTM & Growth Search Context ===\n{cmo_gtm_results}\n\n=== Target Persona Search Context ===\n{cmo_audience_results}"
            await asyncio.sleep(0.3)

            # Step 8: Run CMO Agent (receives Validator, CTO, & CFO reports)
            yield f"data: {json.dumps({'status': 'cmo', 'message': 'CMO defining buyer personas and user acquisition channels...' })}\n\n"
            cmo_user_prompt = (
                f"Startup Idea: {startup_idea}\n\n"
                f"{consultation_context}"
                f"Search Context (real-time web search results):\n{cmo_search_context}\n\n"
                f"Here are the reports from our co-founders:\n"
                f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
                f"--- CTO REPORT ---\n{cto_report}\n\n"
                f"--- CFO REPORT ---\n{cfo_report}\n\n"
                f"Please write your target audience analysis and go-to-market strategy report, making sure it aligns with the product design, pricing tiers, and runway constraints established by the team."
            )
            cmo_report = await call_gemini(CMO_SYSTEM_PROMPT, cmo_user_prompt)
            with open("boardroom_reports/4_cmo.md", "w", encoding="utf-8") as f:
                f.write(cmo_report)

            # Step 9: Run Venture Critic Agent
            yield f"data: {json.dumps({'status': 'critic', 'message': 'Venture Critic auditing the business plan for fatal vulnerabilities...' })}\n\n"
            critic_user_prompt = (
                f"Startup Idea: {startup_idea}\n\n"
                f"{consultation_context}"
                f"Here are the reports generated by the startup co-founders:\n"
                f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
                f"--- CTO REPORT ---\n{cto_report}\n\n"
                f"--- CFO REPORT ---\n{cfo_report}\n\n"
                f"--- CMO REPORT ---\n{cmo_report}\n\n"
                f"Analyze these reports, audit their assumptions, verify if the numbers align, and list all fatal vulnerabilities and required corrections as instructed."
            )
            critic_report = await call_gemini(CRITIC_SYSTEM_PROMPT, critic_user_prompt)
            with open("boardroom_reports/5_venture_critic.md", "w", encoding="utf-8") as f:
                f.write(critic_report)

            # Step 10: Run Pitcher Agent to Synthesize the Blueprint
            yield f"data: {json.dumps({'status': 'pitcher', 'message': 'CEO compiling final blueprint and responding to Critic audit...' })}\n\n"
            pitcher_user_prompt = (
                f"You are the CEO. Synthesize the reports below into a single, cohesive, highly detailed Startup Blueprint.\n\n"
                f"You MUST use this exact structure of Markdown headers:\n"
                f"# [Startup Name] - Investor Pitch & Business Blueprint\n"
                f"## Executive Summary\n"
                f"## 1. Market Opportunity & Competitor Analysis\n"
                f"### SWOT Analysis\n"
                f"### Competitive Landscape\n"
                f"### Market Sizing (TAM, SAM, SOM) & KPIs\n"
                f"### Risk Rating & Initial Assessment\n"
                f"## 2. Product Stack & Technical MVP Timeline\n"
                f"### Technology Stack & API Protocols\n"
                f"### Compliance & Security Strategy\n"
                f"### 12-Week MVP Timeline\n"
                f"## 3. Financial Model, Pricing & Runway\n"
                f"### Pricing Tiers\n"
                f"### Detailed Operating Expenses & Monthly Burn Breakdown\n"
                f"### Runway & Break-Even Math\n"
                f"## 4. Go-To-Market & Growth Strategy\n"
                f"### Target Customer Persona Profile\n"
                f"### Customer Acquisition Channels\n"
                f"### Pre-Launch & Launch Schedule\n"
                f"## 5. Risk Assessment & Critic Response\n"
                f"### Venture Critic\'s Audit (Fatal Vulnerabilities & Required Corrections)\n"
                f"### Critic\'s Objections & Completed Mitigations\n"
                f"## Conclusion & Funding Requirements\n"
                f"### Confidence Scores & Action Items Summary\n\n"
                f"CRITICAL: Under \'### Critic\'s Objections & Completed Mitigations\', you must list each of the Critic\'s objections and write active, present-tense, completed mitigations (e.g. \'We have adjusted MoM growth rate to 12% to ensure sustainable scaling\', \'We have optimized AWS hosting costs to $1,500/mo by utilizing local SQLite sync caching\'). Do NOT say \'we will do it\' or leave them unmitigated.\n\n"
                f"CRITICAL: Replace \'[Startup Name]\' in the header and throughout the document with the actual startup/company name analyzed or invented in the validator\'s report. Do NOT leave \'[Startup Name]\' in the output.\n\n"
                f"CRITICAL: Under \'### Confidence Scores & Action Items Summary\', compile and list all the Confidence Scores and Action Items from each of the co-founder reports separately, grouped by co-founder, keeping their original scores.\n\n"
                f"Here are the reports:\n"
                f"--- IDEA VALIDATOR REPORT ---\n{validator_report}\n\n"
                f"--- CTO REPORT ---\n{cto_report}\n\n"
                f"--- CFO REPORT ---\n{cfo_report}\n\n"
                f"--- CMO REPORT ---\n{cmo_report}\n\n"
                f"--- VENTURE CRITIC REPORT ---\n{critic_report}\n\n"
                f"Output the complete, unified, highly detailed Markdown document according to the required headers, ensuring you replace any remaining bracket placeholders with real details."
            )
            blueprint_text = await call_gemini(PITCHER_SYSTEM_PROMPT, pitcher_user_prompt)

            # Save the file to blueprint_output.md
            with open("blueprint_output.md", "w", encoding="utf-8") as f:
                f.write(blueprint_text)
            with open("boardroom_reports/6_pitcher_blueprint.md", "w", encoding="utf-8") as f:
                f.write(blueprint_text)
            logger.info("Blueprint successfully written to blueprint_output.md and boardroom_reports/6_pitcher_blueprint.md in stream route")

            # Step 11: Completed successfully
            yield f"data: {json.dumps({'status': 'complete', 'blueprint': blueprint_text})}\n\n"

        except Exception as e:
            logger.exception("Error in event generation stream")
            yield f"data: {json.dumps({'status': 'error', 'message': f'Error generating blueprint: {str(e)}'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Self-contained HTML/CSS/JS frontend dashboard
HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LaunchPad AI - AI Co-Founder Boardroom</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500&family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-color: #020205;
            --card-bg: rgba(10, 11, 20, 0.65);
            --border-color: rgba(255, 255, 255, 0.05);
            --border-glow: rgba(139, 92, 246, 0.2);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent-primary: #8b5cf6;
            --accent-secondary: #06b6d4;
            --accent-green: #10b981;
            --accent-rose: #f43f5e;
            --accent-amber: #f59e0b;
            --accent-glow: rgba(139, 92, 246, 0.25);
            --font-display: 'Outfit', sans-serif;
            --font-sans: 'Inter', sans-serif;
            --font-mono: 'Fira Code', monospace;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: var(--font-sans);
            background-color: var(--bg-color);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            align-items: center;
            overflow-x: hidden;
            position: relative;
            padding-bottom: 5rem;
        }

        /* Beautiful glowing background */
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: 
                radial-gradient(circle at 10% 20%, rgba(139, 92, 246, 0.12) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(6, 182, 212, 0.12) 0%, transparent 40%),
                radial-gradient(circle at 50% 50%, rgba(2, 2, 5, 1) 0%, #020205 100%);
            z-index: -2;
            pointer-events: none;
        }

        body::after {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background-image: linear-gradient(rgba(255, 255, 255, 0.012) 1px, transparent 1px),
                              linear-gradient(90deg, rgba(255, 255, 255, 0.012) 1px, transparent 1px);
            background-size: 50px 50px;
            z-index: -1;
            pointer-events: none;
            opacity: 0.6;
        }

        /* Premium Top Navbar */
        .navbar {
            width: 100%;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.25rem 3rem;
            background: rgba(2, 2, 5, 0.75);
            backdrop-filter: blur(15px);
            -webkit-backdrop-filter: blur(15px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            position: sticky;
            top: 0;
            z-index: 100;
            box-sizing: border-box;
        }

        .nav-brand {
            display: flex;
            align-items: center;
            gap: 0.85rem;
        }

        .brand-logo {
            width: 32px;
            height: 32px;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            border-radius: 10px;
            box-shadow: 0 0 20px rgba(139, 92, 246, 0.4);
            position: relative;
        }

        .brand-logo::after {
            content: '';
            position: absolute;
            inset: 6px;
            background: #020205;
            border-radius: 6px;
        }

        .brand-text {
            font-family: var(--font-display);
            font-weight: 800;
            font-size: 1.45rem;
            letter-spacing: -0.02em;
            color: #fff;
        }

        .brand-text span {
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .brand-badge {
            font-size: 0.65rem;
            font-weight: 700;
            padding: 0.25rem 0.6rem;
            background: rgba(139, 92, 246, 0.1);
            border: 1px solid rgba(139, 92, 246, 0.2);
            color: #c084fc;
            border-radius: 6px;
            letter-spacing: 0.05em;
        }

        .nav-status {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            background: rgba(16, 185, 129, 0.06);
            border: 1px solid rgba(16, 185, 129, 0.15);
            padding: 0.45rem 1rem;
            border-radius: 30px;
        }

        .status-indicator {
            width: 8px;
            height: 8px;
            background-color: var(--accent-green);
            border-radius: 50%;
            box-shadow: 0 0 12px var(--accent-green);
            animation: pulse-green 2s infinite;
        }

        .status-text {
            font-size: 0.75rem;
            font-weight: 600;
            color: #a7f3d0;
            letter-spacing: 0.02em;
        }

        /* Container Layout */
        .container {
            width: 100%;
            max-width: 1350px;
            display: grid;
            grid-template-columns: 1fr;
            gap: 2.5rem;
            padding: 3rem 1.5rem;
            box-sizing: border-box;
            animation: fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1) both;
        }

        @media (min-width: 992px) {
            .container {
                grid-template-columns: 420px 1fr;
                align-items: start;
            }
            .container > .glass-card:first-child {
                position: sticky;
                top: 100px;
                max-height: calc(100vh - 140px);
                overflow-y: auto;
            }
            .container > .glass-card:first-child::-webkit-scrollbar {
                width: 4px;
            }
        }

        /* Modern Glass Cards */
        .glass-card {
            background: var(--card-bg);
            backdrop-filter: blur(25px);
            -webkit-backdrop-filter: blur(25px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 2.25rem;
            box-shadow: 0 20px 50px 0 rgba(0, 0, 0, 0.45);
            height: fit-content;
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            overflow: hidden;
        }

        .glass-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 1px;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.08), transparent);
        }

        .glass-card:hover {
            border-color: rgba(255, 255, 255, 0.08);
            box-shadow: 0 25px 60px 0 rgba(0, 0, 0, 0.55);
            transform: translateY(-2px);
        }

        .input-section h2, .status-section h2 {
            font-family: var(--font-display);
            font-size: 1.45rem;
            font-weight: 700;
            margin-bottom: 1.5rem;
            letter-spacing: -0.01em;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            color: #fff;
        }

        .input-section h2 svg {
            stroke: var(--accent-primary);
            filter: drop-shadow(0 0 8px rgba(139, 92, 246, 0.3));
        }

        textarea {
            width: 100%;
            height: 150px;
            background: rgba(5, 5, 10, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 14px;
            color: var(--text-primary);
            padding: 1.2rem;
            font-family: inherit;
            font-size: 0.95rem;
            line-height: 1.6;
            resize: none;
            outline: none;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            margin-bottom: 1.5rem;
        }

        textarea:focus {
            border-color: var(--accent-primary);
            background: rgba(5, 5, 10, 0.8);
            box-shadow: 0 0 25px rgba(139, 92, 246, 0.2);
        }

        button {
            width: 100%;
            background: linear-gradient(135deg, var(--accent-primary) 0%, #6d28d9 100%);
            border: none;
            border-radius: 14px;
            color: #fff;
            padding: 1.1rem;
            font-family: var(--font-display);
            font-weight: 600;
            font-size: 1.05rem;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 0.65rem;
            box-shadow: 0 5px 25px rgba(139, 92, 246, 0.35);
        }

        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(139, 92, 246, 0.55);
            background: linear-gradient(135deg, #9333ea 0%, #5b21b6 100%);
        }

        button:active {
            transform: translateY(0);
        }

        button:disabled {
            background: #1e1e24;
            color: #4b5563;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
            border: 1px solid rgba(255, 255, 255, 0.02);
        }

        /* Beautiful Incubator Timeline */
        .timeline {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
            margin-top: 2rem;
            position: relative;
            background: rgba(255, 255, 255, 0.015);
            border: 1px solid rgba(255, 255, 255, 0.03);
            padding: 1.5rem;
            border-radius: 20px;
        }

        .timeline::before {
            content: '';
            position: absolute;
            left: 35px;
            top: 25px;
            bottom: 25px;
            width: 2px;
            background: linear-gradient(to bottom, var(--border-color) 0%, rgba(139, 92, 246, 0.25) 50%, var(--border-color) 100%);
            z-index: 0;
        }

        .step {
            display: flex;
            align-items: center;
            gap: 1.25rem;
            opacity: 0.25;
            transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
            z-index: 1;
            padding: 0.5rem 0.75rem;
            border-radius: 12px;
        }

        .step.active {
            opacity: 1;
            background: rgba(255, 255, 255, 0.02);
        }

        .step.completed {
            opacity: 0.85;
        }

        .step-icon {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            border: 2px solid var(--border-color);
            background: #08090f;
            display: flex;
            justify-content: center;
            align-items: center;
            font-size: 0.85rem;
            font-weight: 700;
            flex-shrink: 0;
            transition: all 0.4s ease;
            position: relative;
            color: var(--text-secondary);
        }

        .step.active .step-icon {
            border-color: var(--accent-primary);
            box-shadow: 0 0 15px var(--accent-glow);
            background: var(--accent-primary);
            color: #fff;
            animation: pulse-border 1.5s infinite;
        }

        .step.completed .step-icon {
            border-color: var(--accent-green);
            background: var(--accent-green);
            color: #fff;
            box-shadow: 0 0 10px rgba(16, 185, 129, 0.2);
        }

        .step-info {
            display: flex;
            flex-direction: column;
        }

        .step-title {
            font-family: var(--font-display);
            font-size: 1rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .step-desc {
            font-size: 0.8rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }

        .result-container {
            display: flex;
            flex-direction: column;
            min-height: 650px;
        }

        .result-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1.5rem;
            margin-bottom: 2rem;
        }

        .result-title {
            font-family: var(--font-display);
            font-size: 1.55rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            color: #fff;
        }

        .result-title svg {
            stroke: var(--accent-secondary);
            filter: drop-shadow(0 0 8px rgba(6, 182, 212, 0.3));
        }

        .action-buttons {
            display: flex;
            gap: 1rem;
        }

        .btn-secondary {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.06);
            color: var(--text-primary);
            padding: 0.7rem 1.25rem;
            font-family: var(--font-display);
            font-size: 0.9rem;
            border-radius: 12px;
            font-weight: 600;
            width: auto;
            box-shadow: none;
            transition: all 0.3s ease;
        }

        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.07);
            border-color: rgba(255, 255, 255, 0.15);
            transform: translateY(-1px);
        }

        /* Beautiful Blueprint Document Output Styles */
        .blueprint-content {
            flex-grow: 1;
            background: rgba(5, 5, 10, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 20px;
            padding: 3rem;
            font-size: 1.05rem;
            line-height: 1.85;
            color: #cbd5e1;
            box-shadow: inset 0 0 35px rgba(0, 0, 0, 0.7);
        }

        .blueprint-content h1, .blueprint-content h2, .blueprint-content h3 {
            font-family: var(--font-display);
            margin-top: 2.25rem;
            margin-bottom: 1.25rem;
            font-weight: 700;
            letter-spacing: -0.02em;
        }

        .blueprint-content h1 {
            font-size: 2.5rem;
            color: #fff;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding-bottom: 0.75rem;
            margin-top: 0;
            background: linear-gradient(135deg, #ffffff 30%, #c084fc 70%, #22d3ee 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.03em;
        }

        .blueprint-content h2 { 
            font-size: 1.7rem; 
            color: #c084fc; 
            margin-top: 3rem; 
            border-left: 4px solid var(--accent-primary);
            padding-left: 0.75rem;
        }

        .blueprint-content h3 { 
            font-size: 1.25rem; 
            color: #22d3ee; 
            margin-top: 2rem;
        }

        .blueprint-content p { 
            margin-bottom: 1.5rem; 
            color: #cbd5e1; 
        }

        .blueprint-content ul, .blueprint-content ol { 
            margin-left: 2rem; 
            margin-bottom: 1.5rem; 
        }

        .blueprint-content li { 
            margin-bottom: 0.65rem; 
            color: #cbd5e1; 
        }
        
        .blueprint-content table {
            width: 100%;
            border-collapse: collapse;
            margin: 2rem 0;
            border-radius: 16px;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.06);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }
        
        .blueprint-content th {
            background: rgba(139, 92, 246, 0.08);
            color: #fff;
            font-weight: 600;
            border-bottom: 2px solid rgba(139, 92, 246, 0.3);
            padding: 1.1rem 1.4rem;
            text-align: left;
            font-size: 0.95rem;
        }
        
        .blueprint-content td {
            padding: 1rem 1.4rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            color: #cbd5e1;
            font-size: 0.95rem;
        }
        
        .blueprint-content tr:last-child td {
            border-bottom: none;
        }
        
        .blueprint-content tr:hover td {
            background: rgba(255, 255, 255, 0.02);
        }

        .blueprint-content blockquote {
            background: rgba(139, 92, 246, 0.04);
            border-left: 4px solid var(--accent-primary);
            padding: 1.5rem 2rem;
            border-radius: 12px;
            margin: 2.25rem 0;
            font-style: italic;
            color: #94a3b8;
        }

        .blueprint-content strong { 
            color: #fff; 
            font-weight: 600; 
        }

        /* Loading Boardroom Cards styling */
        .boardroom-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 1.5rem;
            width: 100%;
            margin: 2rem 0;
        }

        @media (min-width: 576px) {
            .boardroom-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }

        @media (min-width: 1200px) {
            .boardroom-grid {
                grid-template-columns: repeat(3, 1fr);
            }
        }

        .agent-card {
            background: rgba(255, 255, 255, 0.015);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 20px;
            padding: 1.5rem;
            display: flex;
            align-items: center;
            gap: 1.25rem;
            opacity: 0.35;
            transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            overflow: hidden;
        }

        .agent-card::after {
            content: '';
            position: absolute;
            bottom: 0; left: 0; right: 0; height: 3px;
            background: transparent;
            transition: background 0.3s ease;
        }

        .agent-card:hover {
            border-color: rgba(255, 255, 255, 0.08);
            box-shadow: 0 12px 35px rgba(0, 0, 0, 0.3);
            transform: translateY(-3px);
        }

        .agent-card.active {
            opacity: 1;
            transform: translateY(-5px);
        }

        .agent-card#card-validator.active {
            background: rgba(16, 185, 129, 0.05);
            border-color: var(--accent-green);
            box-shadow: 0 15px 35px rgba(16, 185, 129, 0.12);
        }
        .agent-card#card-validator.active::after { background: var(--accent-green); }

        .agent-card#card-cto.active {
            background: rgba(245, 158, 11, 0.05);
            border-color: var(--accent-amber);
            box-shadow: 0 15px 35px rgba(245, 158, 11, 0.12);
        }
        .agent-card#card-cto.active::after { background: var(--accent-amber); }

        .agent-card#card-cfo.active {
            background: rgba(6, 182, 212, 0.05);
            border-color: var(--accent-cyan);
            box-shadow: 0 15px 35px rgba(6, 182, 212, 0.12);
        }
        .agent-card#card-cfo.active::after { background: var(--accent-cyan); }

        .agent-card#card-cmo.active {
            background: rgba(236, 72, 153, 0.05);
            border-color: #ec4899;
            box-shadow: 0 15px 35px rgba(236, 72, 153, 0.12);
        }
        .agent-card#card-cmo.active::after { background: #ec4899; }

        .agent-card#card-critic.active {
            background: rgba(244, 63, 94, 0.05);
            border-color: var(--accent-rose);
            box-shadow: 0 15px 35px rgba(244, 63, 94, 0.15);
        }
        .agent-card#card-critic.active::after { background: var(--accent-rose); }

        .agent-card#card-pitcher.active {
            background: rgba(139, 92, 246, 0.05);
            border-color: var(--accent-purple);
            box-shadow: 0 15px 35px rgba(139, 92, 246, 0.15);
        }
        .agent-card#card-pitcher.active::after { background: var(--accent-purple); }

        .agent-card.completed {
            opacity: 0.95;
            background: rgba(16, 185, 129, 0.02);
            border-color: rgba(16, 185, 129, 0.4);
        }
        .agent-card.completed::after {
            background: var(--accent-green);
        }

        .agent-avatar {
            width: 50px;
            height: 50px;
            border-radius: 14px;
            background: rgba(0, 0, 0, 0.4);
            display: flex;
            justify-content: center;
            align-items: center;
            font-size: 1.6rem;
            border: 1px solid rgba(255, 255, 255, 0.08);
            transition: all 0.3s ease;
            flex-shrink: 0;
        }

        .agent-card.active .agent-avatar {
            transform: scale(1.05);
        }

        .agent-card#card-validator.active .agent-avatar { background: var(--accent-green); color: #fff; box-shadow: 0 0 15px var(--accent-green); }
        .agent-card#card-cto.active .agent-avatar { background: var(--accent-amber); color: #fff; box-shadow: 0 0 15px var(--accent-amber); }
        .agent-card#card-cfo.active .agent-avatar { background: var(--accent-cyan); color: #fff; box-shadow: 0 0 15px var(--accent-cyan); }
        .agent-card#card-cmo.active .agent-avatar { background: #ec4899; color: #fff; box-shadow: 0 0 15px #ec4899; }
        .agent-card#card-critic.active .agent-avatar { background: var(--accent-rose); color: #fff; box-shadow: 0 0 15px var(--accent-rose); }
        .agent-card#card-pitcher.active .agent-avatar { background: var(--accent-purple); color: #fff; box-shadow: 0 0 15px var(--accent-purple); }

        .agent-card.completed .agent-avatar {
            background: rgba(16, 185, 129, 0.15);
            border-color: var(--accent-green);
            color: #fff;
        }

        .agent-card-info {
            display: flex;
            flex-direction: column;
            text-align: left;
        }

        .agent-card-title {
            font-family: var(--font-display);
            font-size: 1rem;
            font-weight: 600;
            color: #fff;
        }

        .agent-card-role {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.25rem;
        }

        .agent-status-badge {
            position: absolute;
            top: 0.75rem;
            right: 0.75rem;
            font-size: 0.6rem;
            font-weight: 600;
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            background: rgba(255, 255, 255, 0.03);
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
            letter-spacing: 0.03em;
        }

        .agent-card.active .agent-status-badge {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
        }
        .agent-card#card-validator.active .agent-status-badge { border-color: var(--accent-green); }
        .agent-card#card-cto.active .agent-status-badge { border-color: var(--accent-amber); }
        .agent-card#card-cfo.active .agent-status-badge { border-color: var(--accent-cyan); }
        .agent-card#card-cmo.active .agent-status-badge { border-color: #ec4899; }
        .agent-card#card-critic.active .agent-status-badge { border-color: var(--accent-rose); color: #fca5a5; }
        .agent-card#card-pitcher.active .agent-status-badge { border-color: var(--accent-purple); }

        .agent-card.completed .agent-status-badge {
            background: rgba(16, 185, 129, 0.1);
            color: #a7f3d0;
            border-color: var(--accent-green);
        }

        /* Console styling */
        .terminal-log {
            width: 100%;
            background: #020204;
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 16px;
            padding: 1.25rem;
            font-family: var(--font-mono);
            font-size: 0.825rem;
            color: #38bdf8;
            text-align: left;
            height: 180px;
            overflow-y: auto;
            box-shadow: inset 0 0 25px rgba(0, 0, 0, 0.9), 0 10px 30px rgba(0, 0, 0, 0.3);
            position: relative;
        }

        .terminal-log::before {
            content: 'LIVE BOARDROOM PIPELINE';
            position: absolute;
            top: 0.5rem; right: 1rem;
            font-size: 0.6rem;
            font-weight: 700;
            color: rgba(255,255,255,0.15);
            letter-spacing: 0.1em;
        }

        .terminal-line {
            margin-bottom: 0.35rem;
            line-height: 1.5;
        }

        .terminal-time {
            color: var(--accent-primary);
            font-weight: 600;
            margin-right: 0.5rem;
        }

        /* Q&A panel */
        .q-input-group {
            display: flex;
            flex-direction: column;
            gap: 0.65rem;
            margin-bottom: 1.25rem;
            animation: fadeInUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
        }

        .q-label {
            font-family: var(--font-display);
            font-size: 0.9rem;
            font-weight: 600;
            color: #e2e8f0;
            text-align: left;
            line-height: 1.4;
            letter-spacing: -0.01em;
        }

        .q-input {
            width: 100%;
            background: rgba(5, 5, 10, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            color: var(--text-primary);
            padding: 0.85rem 1.1rem;
            font-family: inherit;
            font-size: 0.9rem;
            outline: none;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .q-input:focus {
            border-color: var(--accent-secondary);
            box-shadow: 0 0 20px rgba(6, 182, 212, 0.15);
            background: rgba(5, 5, 10, 0.8);
        }

        .spinner {
            width: 44px;
            height: 44px;
            border: 3px solid rgba(139, 92, 246, 0.1);
            border-radius: 50%;
            border-top-color: var(--accent-primary);
            animation: spin 1s ease-in-out infinite;
            margin-bottom: 1.5rem;
        }

        /* Placeholder box preview elements */
        .placeholder-box {
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            height: 100%;
            min-height: 520px;
            color: var(--text-secondary);
            padding: 3rem;
            animation: fadeIn 0.6s ease;
        }

        .placeholder-logo {
            width: 70px;
            height: 70px;
            background: rgba(139, 92, 246, 0.08);
            border: 1px solid rgba(139, 92, 246, 0.15);
            border-radius: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            margin-bottom: 1.5rem;
            color: var(--accent-purple);
            animation: float 4s ease-in-out infinite;
            box-shadow: 0 10px 25px rgba(139, 92, 246, 0.05);
        }

        .placeholder-logo svg {
            width: 36px;
            height: 36px;
        }

        .placeholder-title {
            font-family: var(--font-display);
            font-size: 1.6rem;
            font-weight: 700;
            color: #fff;
            margin-bottom: 0.5rem;
        }

        .placeholder-subtitle {
            font-size: 0.95rem;
            color: var(--text-secondary);
            max-width: 500px;
            line-height: 1.5;
            margin-bottom: 2.5rem;
        }

        .features-preview {
            display: grid;
            grid-template-columns: 1fr;
            gap: 1.25rem;
            width: 100%;
            max-width: 800px;
        }

        @media (min-width: 768px) {
            .features-preview {
                grid-template-columns: repeat(3, 1fr);
            }
        }

        .preview-item {
            background: rgba(255, 255, 255, 0.01);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 16px;
            padding: 1.25rem;
            text-align: left;
            transition: all 0.3s ease;
        }

        .preview-item:hover {
            background: rgba(255, 255, 255, 0.02);
            border-color: rgba(255, 255, 255, 0.06);
            transform: translateY(-2px);
        }

        .preview-number {
            font-family: var(--font-display);
            font-size: 1.2rem;
            font-weight: 800;
            color: var(--accent-cyan);
            opacity: 0.8;
            display: block;
            margin-bottom: 0.5rem;
        }

        .preview-item h4 {
            font-family: var(--font-display);
            font-size: 0.95rem;
            font-weight: 600;
            color: #fff;
            margin-bottom: 0.35rem;
        }

        .preview-item p {
            font-size: 0.775rem;
            color: var(--text-secondary);
            line-height: 1.45;
            margin-bottom: 0;
        }

        /* Animations */
        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-8px); }
        }

        @keyframes pulse-border {
            0% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.4); }
            70% { box-shadow: 0 0 0 10px rgba(139, 92, 246, 0); }
            100% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0); }
        }

        @keyframes pulse-green {
            0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.5); }
            70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
            100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }

        @keyframes fadeInDown {
            from { opacity: 0; transform: translateY(-20px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.08);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.15);
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <div class="nav-brand">
            <span class="brand-logo"></span>
            <span class="brand-text">LAUNCHPAD<span>AI</span></span>
            <span class="brand-badge">CO-FOUNDER BOARDROOM</span>
        </div>
        <div class="nav-status">
            <span class="status-indicator"></span>
            <span class="status-text">LLM Services: Connected</span>
        </div>
    </nav>

    <div class="container">
        <div class="glass-card">
            <div class="input-section" id="ideaSection">
                <h2>
                    <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
                    Your Idea
                </h2>
                <textarea id="ideaInput" placeholder="Describe your business idea in detail (e.g. A hospital-paid AI mental health app for nurses...)"></textarea>
                <button id="consultBtn" class="btn-primary" onclick="fetchQuestions()">
                    <span>Consult Co-founders</span>
                    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>
                </button>
            </div>

            <div class="input-section" id="consultSection" style="display: none; margin-top: 1.5rem; border-top: 1px solid var(--border-color); padding-top: 1.5rem;">
                <h2 style="color: var(--accent-secondary);">
                    <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/></svg>
                    Incubator Q&A
                </h2>
                <p style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 1.25rem; line-height: 1.45;">
                    The incubator team has 3 startup-specific clarifying questions. Provide answers to align them, or click "Skip" to use default co-founder assumptions.
                </p>
                
                <div id="questionsContainer" style="display: flex; flex-direction: column; gap: 1.1rem; margin-bottom: 1.5rem;">
                    <!-- Questions dynamically loaded -->
                </div>

                <div style="display: flex; gap: 0.75rem;">
                    <button id="submitAnswersBtn" class="btn-primary" onclick="startGeneration(false)" style="flex: 2;">
                        <span>Run Boardroom</span>
                        <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                    </button>
                    <button id="skipBtn" onclick="startGeneration(true)" class="btn-secondary" style="flex: 1; justify-content: center; height: auto; padding: 0.85rem 0;">
                        Skip
                    </button>
                </div>
            </div>

            <div class="timeline" id="timeline" style="display: none;">
                <div class="step" id="step-search">
                    <div class="step-icon">1</div>
                    <div class="step-info">
                        <span class="step-title">Web Context Search</span>
                        <span class="step-desc" id="desc-search">Queued</span>
                    </div>
                </div>
                <div class="step" id="step-validator">
                    <div class="step-icon">2</div>
                    <div class="step-info">
                        <span class="step-title">IdeaValidator Agent</span>
                        <span class="step-desc" id="desc-validator">Queued</span>
                    </div>
                </div>
                <div class="step" id="step-cto">
                    <div class="step-icon">3</div>
                    <div class="step-info">
                        <span class="step-title">CTO Agent</span>
                        <span class="step-desc" id="desc-cto">Queued</span>
                    </div>
                </div>
                <div class="step" id="step-cfo">
                    <div class="step-icon">4</div>
                    <div class="step-info">
                        <span class="step-title">CFO Agent</span>
                        <span class="step-desc" id="desc-cfo">Queued</span>
                    </div>
                </div>
                <div class="step" id="step-cmo">
                    <div class="step-icon">5</div>
                    <div class="step-info">
                        <span class="step-title">CMO Agent</span>
                        <span class="step-desc" id="desc-cmo">Queued</span>
                    </div>
                </div>
                <div class="step" id="step-critic">
                    <div class="step-icon">6</div>
                    <div class="step-info">
                        <span class="step-title">Venture Critic</span>
                        <span class="step-desc" id="desc-critic">Queued</span>
                    </div>
                </div>
                <div class="step" id="step-pitcher">
                    <div class="step-icon">7</div>
                    <div class="step-info">
                        <span class="step-title">Pitcher Synthesis</span>
                        <span class="step-desc" id="desc-pitcher">Queued</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="glass-card result-container" style="flex-grow: 1;">
            <div class="result-header">
                <div class="result-title">
                    <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                    Business Blueprint
                </div>
                <div class="action-buttons" id="actionButtons" style="display: none;">
                    <button class="btn-secondary" onclick="copyBlueprint()">Copy Text</button>
                    <button class="btn-secondary" onclick="downloadBlueprint()">Download .md</button>
                </div>
            </div>

            <div class="placeholder-box" id="placeholderBox">
                <div class="placeholder-logo">
                    <svg fill="none" stroke="currentColor" stroke-width="1.2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.97 5.97 0 00-.75-2.985m-.938-3.197A5.971 5.971 0 0012 10.5c-2.84 0-5.386 1.978-5.83 4.73m.062 3.498l.001-.031c0-.225.012-.447.037-.666A11.944 11.944 0 0012 3c2.17 0 4.207.576 5.963 1.584A6.062 6.062 0 0118 5.281m0 13.438a5.97 5.97 0 01-.75-2.985m-.938-3.197A5.971 5.971 0 0112 13.5c-2.84 0-5.386-1.978-5.83-4.73m0 0l-.001-.031c0-.225.012-.447.037-.666A11.944 11.944 0 0112 3c2.17 0 4.207.576 5.963 1.584A6.062 6.062 0 0112 5.281"/></svg>
                </div>
                <h3 class="placeholder-title">AI Founder Boardroom</h3>
                <p id="placeholderText" class="placeholder-subtitle">Enter your business idea and click "Consult Co-founders" to start the incubation process.</p>
                
                <div class="features-preview">
                    <div class="preview-item">
                        <span class="preview-number">01</span>
                        <h4>Clarify Goals</h4>
                        <p>Discuss details with the incubator team before running research.</p>
                    </div>
                    <div class="preview-item">
                        <span class="preview-number">02</span>
                        <h4>Collaborative Design</h4>
                        <p>Co-founders debate, validation reports compile, and Critic audits assumptions.</p>
                    </div>
                    <div class="preview-item">
                        <span class="preview-number">03</span>
                        <h4>Get Blueprint</h4>
                        <p>Receive a complete, investor-ready, risk-mitigated business plan.</p>
                    </div>
                </div>
            </div>

            <div class="blueprint-content" id="blueprintContent" style="display: none;"></div>
        </div>
    </div>

    <script>
        let generatedText = '';
        let timerInterval;
        let startTime;

        function startTimer() {
            startTime = Date.now();
            const timerVal = document.getElementById('timerVal');
            if (timerInterval) clearInterval(timerInterval);
            timerInterval = setInterval(() => {
                const elapsedMs = Date.now() - startTime;
                const totalSecs = Math.floor(elapsedMs / 1000);
                const mins = Math.floor(totalSecs / 60).toString().padStart(2, '0');
                const secs = (totalSecs % 60).toString().padStart(2, '0');
                if (timerVal) timerVal.textContent = `${mins}:${secs}`;
            }, 1000);
        }

        function stopTimer() {
            if (timerInterval) clearInterval(timerInterval);
        }

        function addLog(message) {
            const consoleBox = document.getElementById('consoleBox');
            if (!consoleBox) return;
            const elapsedMs = Date.now() - startTime;
            const totalSecs = Math.floor(elapsedMs / 1000);
            const mins = Math.floor(totalSecs / 60).toString().padStart(2, '0');
            const secs = (totalSecs % 60).toString().padStart(2, '0');
            
            const line = document.createElement('div');
            line.className = 'terminal-line';
            line.innerHTML = `<span class="terminal-time">[${mins}:${secs}]</span> ${message}`;
            consoleBox.appendChild(line);
            consoleBox.scrollTop = consoleBox.scrollHeight;
        }

        function setStepState(stepId, state, descText = '') {
            const stepEl = document.getElementById(`step-${stepId}`);
            const descEl = document.getElementById(`desc-${stepId}`);
            
            if (!stepEl || !descEl) return;
            
            if (descText) descEl.textContent = descText;

            stepEl.className = 'step';
            if (state === 'active') {
                stepEl.classList.add('active');
                descEl.textContent = descText || 'Running...';
            } else if (state === 'completed') {
                stepEl.classList.add('completed');
                descEl.textContent = descText || 'Done';
            } else if (state === 'queued') {
                descEl.textContent = descText || 'Queued';
            } else if (state === 'failed') {
                stepEl.classList.add('active');
                stepEl.style.opacity = '1';
                descEl.textContent = descText || 'Failed';
                descEl.style.color = '#ef4444';
            }
        }

        function updateAgentCard(cardId, state, statusText) {
            const cardEl = document.getElementById(`card-${cardId}`);
            const badgeEl = document.getElementById(`badge-${cardId}`);
            if (!cardEl) return;

            cardEl.className = 'agent-card';
            if (state === 'active') {
                cardEl.classList.add('active');
                if (badgeEl) badgeEl.textContent = statusText || 'Thinking...';
            } else if (state === 'completed') {
                cardEl.classList.add('completed');
                if (badgeEl) badgeEl.textContent = statusText || 'Ready';
            } else {
                if (badgeEl) badgeEl.textContent = 'Queued';
            }
        }

        async function fetchQuestions() {
            const ideaInput = document.getElementById('ideaInput');
            const consultBtn = document.getElementById('consultBtn');
            const consultSection = document.getElementById('consultSection');
            const questionsContainer = document.getElementById('questionsContainer');
            
            const idea = ideaInput.value.trim();
            if (!idea) {
                alert('Please enter a startup idea first!');
                return;
            }
            
            consultBtn.disabled = true;
            consultBtn.innerHTML = `
                <span class="spinner" style="width: 16px; height: 16px; border-width: 2px; margin-bottom: 0; display: inline-block; vertical-align: middle; margin-right: 0.5rem;"></span>
                Analyzing...
            `;
            
            // Clear any previous consultation questions view
            consultSection.style.display = 'none';
            
            try {
                const res = await fetch(`/api/consult?startup_idea=${encodeURIComponent(idea)}`);
                const data = await res.json();
                
                if (data.questions && data.questions.length === 3) {
                    questionsContainer.innerHTML = '';
                    data.questions.forEach((q, idx) => {
                        const formGroup = document.createElement('div');
                        formGroup.className = 'q-input-group';
                        
                        const label = document.createElement('label');
                        label.className = 'q-label';
                        label.textContent = `${idx + 1}. ${q}`;
                        
                        const input = document.createElement('input');
                        input.type = 'text';
                        input.id = `q${idx + 1}_answer`;
                        input.className = 'q-input';
                        input.placeholder = 'Provide details or leave blank for default co-founder assumptions...';
                        
                        formGroup.appendChild(label);
                        formGroup.appendChild(input);
                        questionsContainer.appendChild(formGroup);
                    });
                    
                    consultSection.style.display = 'block';
                    consultSection.scrollIntoView({ behavior: 'smooth' });
                } else {
                    alert('Failed to load consultation questions. Please try again.');
                }
            } catch (err) {
                console.error(err);
                alert('An error occurred while communicating with the co-founders.');
            } finally {
                consultBtn.disabled = false;
                consultBtn.innerHTML = `
                    <span>Consult Co-founders</span>
                    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>
                `;
            }
        }

        function startGeneration(skipAnswers) {
            const ideaInput = document.getElementById('ideaInput');
            const consultBtn = document.getElementById('consultBtn');
            const submitAnswersBtn = document.getElementById('submitAnswersBtn');
            const skipBtn = document.getElementById('skipBtn');
            const timeline = document.getElementById('timeline');
            const placeholderBox = document.getElementById('placeholderBox');
            const blueprintContent = document.getElementById('blueprintContent');
            const actionButtons = document.getElementById('actionButtons');

            const idea = ideaInput.value.trim();
            if (!idea) {
                alert('Please enter a startup idea first!');
                return;
            }

            let q1 = "";
            let q2 = "";
            let q3 = "";
            
            if (!skipAnswers) {
                const q1El = document.getElementById('q1_answer');
                const q2El = document.getElementById('q2_answer');
                const q3El = document.getElementById('q3_answer');
                if (q1El) q1 = q1El.value.trim();
                if (q2El) q2 = q2El.value.trim();
                if (q3El) q3 = q3El.value.trim();
            }

            consultBtn.disabled = true;
            if (submitAnswersBtn) submitAnswersBtn.disabled = true;
            if (skipBtn) skipBtn.disabled = true;
            ideaInput.disabled = true;
            
            timeline.style.display = 'flex';
            actionButtons.style.display = 'none';

            const steps = ['search', 'validator', 'cto', 'cfo', 'cmo', 'critic', 'pitcher'];
            steps.forEach(s => setStepState(s, 'queued', 'Queued'));

            // Show interactive boardroom layout
            placeholderBox.innerHTML = `
                <h3 style="font-family:'Outfit', sans-serif; font-size: 1.35rem; font-weight:700; margin-bottom:0.15rem; color:#fff; display: flex; align-items: center; gap: 0.5rem;">
                    <span class="spinner" style="width: 20px; height: 20px; border-width: 2px; margin-bottom: 0; display: inline-block;"></span>
                    Co-Founder Boardroom
                </h3>
                <p id="streamingStatus" style="font-size:0.9rem; color:var(--text-secondary); margin-bottom:0.75rem;">Setting up connection...</p>
                
                <div class="timer-display" style="font-size: 0.95rem; font-weight:600; color:var(--accent-secondary); margin-bottom:0.75rem; font-family:monospace; background: rgba(255,255,255,0.02); padding: 0.25rem 0.75rem; border-radius: 20px; border: 1px solid var(--border-color); width: fit-content;">
                    Elapsed Time: <span id="timerVal">00:00</span>
                </div>

                <!-- Boardroom Co-founder Grid with Critic -->
                <div class="boardroom-grid">
                    <div class="agent-card" id="card-validator">
                        <div class="agent-avatar">🔍</div>
                        <div class="agent-card-info">
                            <span class="agent-card-title">Idea Validator</span>
                            <span class="agent-card-role">TAM/SAM & SWOT Analysis</span>
                        </div>
                        <span class="agent-status-badge" id="badge-validator">Queued</span>
                    </div>

                    <div class="agent-card" id="card-cto">
                        <div class="agent-avatar">⚙️</div>
                        <div class="agent-card-info">
                            <span class="agent-card-title">CTO Co-founder</span>
                            <span class="agent-card-role">Tech Architecture & MVP</span>
                        </div>
                        <span class="agent-status-badge" id="badge-cto">Queued</span>
                    </div>

                    <div class="agent-card" id="card-cfo">
                        <div class="agent-avatar">📊</div>
                        <div class="agent-card-info">
                            <span class="agent-card-title">CFO Co-founder</span>
                            <span class="agent-card-role">Runway & Pricing Model</span>
                        </div>
                        <span class="agent-status-badge" id="badge-cfo">Queued</span>
                    </div>

                    <div class="agent-card" id="card-cmo">
                        <div class="agent-avatar">📣</div>
                        <div class="agent-card-info">
                            <span class="agent-card-title">CMO Co-founder</span>
                            <span class="agent-card-role">Buyer Persona & Launch</span>
                        </div>
                        <span class="agent-status-badge" id="badge-cmo">Queued</span>
                    </div>

                    <div class="agent-card" id="card-critic">
                        <div class="agent-avatar">⚖️</div>
                        <div class="agent-card-info">
                            <span class="agent-card-title" style="color: #fca5a5;">Venture Critic</span>
                            <span class="agent-card-role">Fatal Vulnerability Audit</span>
                        </div>
                        <span class="agent-status-badge" id="badge-critic" style="border-color: rgba(244, 63, 94, 0.2); color: #fca5a5;">Queued</span>
                    </div>

                    <div class="agent-card" id="card-pitcher">
                        <div class="agent-avatar">🎙️</div>
                        <div class="agent-card-info">
                            <span class="agent-card-title">CEO / Pitcher</span>
                            <span class="agent-card-role">Synthesis & Pitch Draft</span>
                        </div>
                        <span class="agent-status-badge" id="badge-pitcher">Queued</span>
                    </div>
                </div>

                <!-- Technical log console -->
                <div class="terminal-log" id="consoleBox"></div>
            `;
            placeholderBox.style.display = 'flex';
            blueprintContent.style.display = 'none';

            startTimer();
            addLog("Initializing AI Co-founder boardroom...");

            const url = `/api/generate-blueprint-stream?startup_idea=${encodeURIComponent(idea)}&q1_answer=${encodeURIComponent(q1)}&q2_answer=${encodeURIComponent(q2)}&q3_answer=${encodeURIComponent(q3)}`;
            const eventSource = new EventSource(url);

            let lastActiveStep = '';

            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                const statusEl = document.getElementById('streamingStatus');

                if (data.status === 'search') {
                    setStepState('search', 'active', data.message || 'Searching DDG...');
                    if (statusEl) statusEl.textContent = data.message;
                    addLog(data.message);
                    lastActiveStep = 'search';
                }
                else if (data.status === 'validator') {
                    if (lastActiveStep) setStepState(lastActiveStep, 'completed');
                    setStepState('validator', 'active', 'Analyzing market viability...');
                    updateAgentCard('validator', 'active', 'Thinking...');
                    if (statusEl) statusEl.textContent = data.message;
                    addLog("Sourced competitors, valuations, and market data sizing.");
                    addLog("Invoking IdeaValidator: performing TAM/SAM/SOM calculations & SWOT audit...");
                    lastActiveStep = 'validator';
                }
                else if (data.status === 'cto') {
                    if (lastActiveStep) setStepState(lastActiveStep, 'completed');
                    updateAgentCard('validator', 'completed', 'Ready');
                    setStepState('cto', 'active', 'Designing technology architecture...');
                    updateAgentCard('cto', 'active', 'Thinking...');
                    if (statusEl) statusEl.textContent = data.message;
                    addLog("IdeaValidator analysis complete.");
                    addLog("Sourced stack dependencies and compliance guidelines.");
                    addLog("Invoking CTO: sharing Validator report to design backend database, APIs, security compliance, and MVP timeline...");
                    lastActiveStep = 'cto';
                }
                else if (data.status === 'cfo') {
                    if (lastActiveStep) setStepState(lastActiveStep, 'completed');
                    updateAgentCard('cto', 'completed', 'Ready');
                    setStepState('cfo', 'active', 'Modeling pricing & operating metrics...');
                    updateAgentCard('cfo', 'active', 'Thinking...');
                    if (statusEl) statusEl.textContent = data.message;
                    addLog("CTO engineering roadmap complete.");
                    addLog("Sourced average pricing plans and hosting server operational costs.");
                    addLog("Invoking CFO: building pricing models, monthly infrastructure burn rate, realistic salaries, and break-even targets...");
                    lastActiveStep = 'cfo';
                }
                else if (data.status === 'cmo') {
                    if (lastActiveStep) setStepState(lastActiveStep, 'completed');
                    updateAgentCard('cfo', 'completed', 'Ready');
                    setStepState('cmo', 'active', 'Designing user acquisition strategy...');
                    updateAgentCard('cmo', 'active', 'Thinking...');
                    if (statusEl) statusEl.textContent = data.message;
                    addLog("CFO financial model complete.");
                    addLog("Sourced growth strategies, funnels, and demographic metrics.");
                    addLog("Invoking CMO: defining target customer buyer persona, acquisition channels, and structured waitlist GTM launches...");
                    lastActiveStep = 'cmo';
                }
                else if (data.status === 'critic') {
                    if (lastActiveStep) setStepState(lastActiveStep, 'completed');
                    updateAgentCard('cmo', 'completed', 'Ready');
                    setStepState('critic', 'active', 'Auditing business plan for fatal vulnerabilities...');
                    updateAgentCard('critic', 'active', 'Auditing...');
                    if (statusEl) statusEl.textContent = data.message;
                    addLog("CMO market launch plan complete.");
                    addLog("Invoking Venture Critic: auditing financial holes, compliance loopholes, and technical complexity risks...");
                    lastActiveStep = 'critic';
                }
                else if (data.status === 'pitcher') {
                    if (lastActiveStep) setStepState(lastActiveStep, 'completed');
                    updateAgentCard('critic', 'completed', 'Ready');
                    setStepState('pitcher', 'active', 'Compiling and synthesizing final pitch blueprint...');
                    updateAgentCard('pitcher', 'active', 'Synthesizing...');
                    if (statusEl) statusEl.textContent = data.message;
                    addLog("Venture Critic audit report complete.");
                    addLog("Invoking CEO/Pitcher: combining co-founder blueprints and addressing Critic fatal objections head-on...");
                    lastActiveStep = 'pitcher';
                }
                else if (data.status === 'complete') {
                    if (lastActiveStep) setStepState(lastActiveStep, 'completed');
                    updateAgentCard('pitcher', 'completed', 'Ready');
                    setStepState('pitcher', 'completed', 'Blueprint compiled!');
                    addLog("Final blueprint synthesis completed successfully.");
                    stopTimer();
                    
                    generatedText = data.blueprint;
                    blueprintContent.innerHTML = marked.parse(generatedText);
                    
                    placeholderBox.style.display = 'none';
                    blueprintContent.style.display = 'block';
                    actionButtons.style.display = 'flex';
                    
                    consultBtn.disabled = false;
                    if (submitAnswersBtn) submitAnswersBtn.disabled = false;
                    if (skipBtn) skipBtn.disabled = false;
                    ideaInput.disabled = false;
                    eventSource.close();
                }
                else if (data.status === 'error') {
                    if (lastActiveStep) setStepState(lastActiveStep, 'failed', 'Error occurred');
                    addLog(`Error: ${data.message}`);
                    stopTimer();
                    alert(data.message);
                    
                    placeholderBox.innerHTML = `
                        <svg width="48" height="48" fill="none" stroke="#ef4444" stroke-width="1.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
                        <h3 style="font-family:'Outfit', sans-serif; font-size:1.15rem; font-weight:600; color:#ef4444; margin-top:0.5rem; margin-bottom:0.35rem;">Generation Failed</h3>
                        <p style="font-size:0.9rem; color:var(--text-secondary); max-width:400px;">${data.message}</p>
                    `;
                    consultBtn.disabled = false;
                    if (submitAnswersBtn) submitAnswersBtn.disabled = false;
                    if (skipBtn) skipBtn.disabled = false;
                    ideaInput.disabled = false;
                    eventSource.close();
                }
            };

            eventSource.onerror = function(err) {
                console.error("EventSource failed:", err);
                if (lastActiveStep) setStepState(lastActiveStep, 'failed', 'Connection error');
                addLog("Error: Connection to server lost.");
                stopTimer();
                alert("Connection failed. Please verify that Ollama or Gemini services are active.");
                
                consultBtn.disabled = false;
                if (submitAnswersBtn) submitAnswersBtn.disabled = false;
                if (skipBtn) skipBtn.disabled = false;
                ideaInput.disabled = false;
                eventSource.close();
            };
        }

        function copyBlueprint() {
            if (!generatedText) return;
            navigator.clipboard.writeText(generatedText).then(() => {
                alert('Blueprint copied to clipboard!');
            }).catch(err => {
                console.error('Failed to copy text: ', err);
            });
        }

        function downloadBlueprint() {
            if (!generatedText) return;
            const blob = new Blob([generatedText], { type: 'text/markdown' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'startup_blueprint.md';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }
    </script>
    <footer style="margin-top: 5rem; padding: 2rem 0; border-top: 1px solid rgba(255,255,255,0.05); text-align: center; color: var(--text-muted); font-size: 0.85rem; width: 100%;">
        <p>Dashboard engineered by <strong style="color: #fff;">Mohibul Hoque</strong></p>
        <p style="margin-top: 0.5rem;">
            Email: <a href="mailto:hokworks@gmail.com" style="color: var(--accent-secondary); text-decoration: none;">hokworks@gmail.com</a> | 
            LinkedIn: <a href="https://www.linkedin.com/in/speedymohibul" target="_blank" style="color: var(--accent-secondary); text-decoration: none;">speedymohibul</a>
        </p>
    </footer>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTMLResponse(content=HTML_CONTENT, status_code=200)
