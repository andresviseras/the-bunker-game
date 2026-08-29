import json
import logging
from typing import Dict, List, Optional
from google import genai
from google.genai import types

# Configure logging for production-level error tracking
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def generate_and_distribute_roles(api_key: str, players: List[str], current_scenario: str, language: str) -> Optional[Dict]:
    """
    Communicates with Gemini to asynchronously generate roles using the room's API key.
    """
    if not api_key:
        logger.error("No API key provided for role generation.")
        return None
        
    client = genai.Client(api_key=api_key)

    prompt = f"""
    LANGUAGE REQUIREMENT: You MUST generate all the output text entirely in this language: {language}.
    You are the ruthless Game Master of a social deduction and extreme survival game. 
    The current crisis scenario is: {current_scenario}.
    The players are: {', '.join(players)}.
    GOLDEN RULE: Mathematically, exactly HALF of these players can survive in the bunker. (IMPORTANT: If the total number of players is odd, you MUST round down).

    Your goal is to generate a brutal, strategic, and paranoid debate. Design the roles applying this logic:

    1. REAL UTILITY & HYBRID ROLES: All roles must be vital and unquestionable. FORBIDDEN to invent niche or ultra-specific roles that seem useless on their own. MANDATORY: Encourage HYBRID OR MULTI-DISCIPLINARY ROLES (e.g., a botanist who generates FOOD and purifies OXYGEN). This forces capabilities to overlap, making the group debate who is more expendable. Explain the direct utility without fluff.
    2. FUTURE FLAWS (THE LATENT DANGER): Flaws MUST NOT be things that have already happened. They must be catastrophic actions, diseases, or betrayals that WILL happen once inside the bunker. IMPORTANT: Disconnect utility from severity. STRICT PROHIBITION OF CLICHÉS: Do not limit yourself to 'psychotic breaks', 'stealing medicine', or 'opening the airlock'. Invent creative threats (rare phobias, contagious diseases, political blackmail, sabotage due to panic, etc.).
    3. AT LEAST ONE LETHAL THREAT: Among all players, there MUST ALWAYS be at least one flaw that is a direct death threat to the group (e.g., asymptomatic carrier of a plague, an infiltrated spy, a serial killer).
    4. NEUTRALIZATION INTERACTIONS (OCCASIONAL): OCCASIONALLY, design roles so that one player's skill interacts with another's flaw. If a skill neutralizes or detonates a flaw, the EXACT MECHANISM must be explicitly written in the 'skill' text without revealing any secret.
    5. CIRCULAR BLACKMAIL NETWORK (NO COUPLES): It is FORBIDDEN to cross secrets mutually (If A knows B's secret, B cannot know A's). You must create a circular extortion chain (A knows B, B knows C, C knows D...). IMPORTANT: Disconnect neutralizations from secrets. A player CANNOT receive the secret of the person their skill neutralizes.
    6. REDUNDANCY & NO MONOPOLIES (CRITICAL): Usually there should not be absolute monopolies on essential survival needs. Not compulsory always. Usually TWO different players must have overlapping or backup capabilities for critical infrastructure (e.g., two people who can handle water/oxygen, or two people who understand energy/maintenance). However to people should not have exacttly all the same abilities. 

    Generate a role for EACH player strictly following this format:
    1. 'role': The official job title.
    2. 'skill': FIRST PERSON. CONCISE (MAX 3 SHORT SENTENCES). Explain the vital utility.
    3. 'flaw': SECOND PERSON. VERY SHORT (1 sentence). Written in FUTURE or CONDITIONAL tense.
    4. 'secret_of_another': THIRD PERSON. VERY SHORT. Must explicitly include the real name of the player who owns the flaw to maintain the circular chain.

    Finally, design the SECRET IDEAL SOLUTION. Choose exactly half of the players that make up the viable combination. Explain the winning strategy. If the strategy implies long-term survival, the chosen team MUST collectively cover all basic needs.
    
    CRITICAL FORMATTING RULE: 
    - All text values inside the JSON MUST be written in a single continuous line. 
    - STRICTLY FORBIDDEN: Do NOT use unescaped double quotes, and do NOT use physical line breaks or newline characters (\\n) inside the text strings. Keep every description as a single paragraph.
    Return ONLY a valid JSON with this exact structure, with no markdown formatting or extra text:
    {{
      "players": {{
        "PlayerName1": {{
          "role": "Job title",
          "skill": "First person text...",
          "flaw": "Second person future text...",
          "secret_of_another": "Third person text..."
        }}
      }},
      "ai_verdict": {{
        "ideal_survivors": ["Name1", "Name2"],
        "explanation": "Detailed explanation of the solution."
      }}
    }}
    """
    
    try:
        chat = client.aio.chats.create(
            model='gemini-3.5-flash',
            config=types.GenerateContentConfig(
                temperature=0.9,
                response_mime_type="application/json" 
            )
        )
        response = await chat.send_message(prompt)
        
        raw_json = response.text
        
        if raw_json.startswith("```json"):
            raw_json = raw_json.replace("```json", "").replace("```", "").strip()
            
        return json.loads(raw_json)
        
    except json.JSONDecodeError as e:
        logger.error("\n--- JSON SYNTAX ERROR FROM AI ---")
        logger.error(f"Error details: {e}")
        logger.error(f"Raw text returned:\n{raw_json}")
        logger.error("---------------------------------------\n")
        return None
    except Exception as e:
        logger.error(f"General AI Error: {e}")
        return None

async def generate_final_verdict(api_key: str, game_language: str, current_scenario: str, player_roles: dict, ideal_survivors: list, chosen_survivors: list) -> Optional[Dict]:
    """
    Generates the final verdict using the room's API key.
    """
    if not api_key:
        logger.error("No API key provided for verdict generation.")
        return None
        
    client = genai.Client(api_key=api_key)

    prompt = f"""
    LANGUAGE REQUIREMENT: You MUST generate all output entirely in this language: {game_language}.
    Scenario: {current_scenario}
    Players and Roles: {json.dumps(player_roles, ensure_ascii=False)}
    The Ideal Logical Team: {ideal_survivors}
    The Host's Chosen Team: {chosen_survivors}.
    
    Write a brutally honest, analytical, and completely objective narrative. 
    
    CRITICAL TONE RULES: 
    - DO NOT use first-person pronouns (I, me, my, "as an AI", "I believe", etc.). 
    - Keep it strictly impersonal, clinical, and objective (e.g., "El análisis de los perfiles indica que...", "La combinación seleccionada resulta en...").
    
    1. Objective analysis of the Host's team: Detail exactly what happens to the chosen team inside the bunker. Explicitly mention their "toxic synergies" (how one player's flaw ruins another's work) or "incomplete synergies" (critical survival needs left unmet).
    2. Justification of the Ideal Team: Provide a cold, logical explanation of why the Ideal Logical Team ({ideal_survivors}) would have been a mathematically and practically superior choice based on their complementary skills and manageable flaws.
    
    CRITICAL FORMATTING RULE: 
    - All text values inside the JSON MUST be written in a single continuous line. 
    - STRICTLY FORBIDDEN: Do NOT use unescaped double quotes, and do NOT use physical line breaks or newline characters (\\n) inside the text strings. Keep every description as a single paragraph.
    
    Return ONLY a valid JSON with this exact structure, with no markdown formatting or extra text:
    {{
      "player_outcome": "Objective analysis of what happens to the Host's team, highlighting toxic or incomplete synergies...",
      "ai_smackdown": "Objective justification of why the Ideal Team was logically superior..."
    }}
    """
    
    try:
        chat = client.aio.chats.create(
            model='gemini-3.5-flash',
            config=types.GenerateContentConfig(
                temperature=0.9,
                response_mime_type="application/json"
            )
        )
        response = await chat.send_message(prompt)
        
        return json.loads(response.text)
        
    except Exception as e:
        logger.error(f"AI Error (Verdict): {e}")
        return None