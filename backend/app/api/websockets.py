import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict

from app.game.engine import BunkerEngine
from app.services.llm_service import generate_and_distribute_roles, generate_final_verdict

router = APIRouter()

# MAIN DICTIONARY: { "room_code": BunkerEngine }
rooms: Dict[str, BunkerEngine] = {}

# Tracks active WebSocket connections per room
# Structure: { "room_code": { "player_name": WebSocket } }
active_connections: Dict[str, Dict[str, WebSocket]] = {}

async def broadcast_to_room(room_code: str, message: dict) -> None:
    """Sends a message to all connected players in a specific room."""
    if room_code in active_connections:
        connections = active_connections[room_code].values()
        tasks = [asyncio.create_task(conn.send_json(message)) for conn in connections]
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

async def send_personal_to_room(room_code: str, player_name: str, message: dict) -> None:
    """Sends a private message to a specific player in a room."""
    if room_code in active_connections and player_name in active_connections[room_code]:
        try:
            await active_connections[room_code][player_name].send_json(message)
        except Exception:
            pass

@router.websocket("/ws/{room_code}/{player_name}")
async def websocket_endpoint(websocket: WebSocket, room_code: str, player_name: str, api_key: str = ""):
    room_code = room_code.lower()
    
    # 1. ROOM MANAGEMENT
    if room_code not in rooms:
        # If the room doesn't exist, only allow creation if an API KEY is provided
        if not api_key:
            await websocket.accept()
            await websocket.send_json({"type": "error", "message": "Room not found."})
            await websocket.close()
            return
        rooms[room_code] = BunkerEngine(api_key=api_key)
        active_connections[room_code] = {}
    
    engine = rooms[room_code]
    
    await websocket.accept()
    active_connections[room_code][player_name] = websocket
    
    # Connect player. If api_key is provided, treat them as creator/host
    is_creator = bool(api_key)
    engine.connect_player(player_name, is_creator)
    
    # 2. RECONNECTION LOGIC
    if engine.game_phase == "playing" and player_name in engine.player_roles:
        await send_personal_to_room(room_code, player_name, {
            "type": "role_reveal",
            "scenario": engine.current_scenario,
            "data": engine.player_roles[player_name],
            "all_players": list(engine.players.keys())
        })
    elif engine.game_phase == "verdict" and engine.final_results:
        await send_personal_to_room(room_code, player_name, {
            "type": "show_verdict", 
            "data": engine.final_results
        })

    # Broadcast lobby state
    await broadcast_to_room(room_code, {
        "type": "lobby_update", 
        "players": list(engine.players.keys()),
        "active_players": engine.active_player_names,
        "host": engine.host
    })
    
    try:
        while True:
            # 3. MESSAGE HANDLING
            data = await websocket.receive_text()
            msg = json.loads(data)
            action = msg.get("action")
            
            # Reset Game
            if action == "reset_game":
                engine.game_phase = "lobby"
                engine.player_roles = {}
                engine.final_results = None
                engine.secret_verdict = None
                
                await broadcast_to_room(room_code, {
                    "type": "lobby_update", 
                    "players": list(engine.players.keys()),
                    "active_players": engine.active_player_names,
                    "host": engine.host
                })
                continue
            
            # --- HOST EXCLUSIVE ACTIONS ---
            if player_name == engine.host:
                if action == "start_game":
                    scenario = msg.get("scenario", "Default scenario")
                    language = msg.get("language", "en")
                    
                    engine.start_game(scenario, language)
                    await broadcast_to_room(room_code, {"type": "game_starting"})
                    
                    ai_data = await generate_and_distribute_roles(
                        engine.api_key,
                        engine.active_player_names, 
                        scenario, 
                        language
                    )
                    
                    if ai_data:
                        engine.set_ai_roles(ai_data.get("players", {}), ai_data.get("ai_verdict", {}))
                        for p_name, role_data in engine.player_roles.items():
                            await send_personal_to_room(room_code, p_name, {
                                "type": "role_reveal",
                                "scenario": scenario,
                                "data": role_data,
                                "all_players": list(engine.players.keys())
                            })
                    else:
                        await broadcast_to_room(room_code, {"type": "error", "message": "AI Game Master failed. Check your API Key."})

                elif action == "submit_host_selection":
                    chosen = msg.get("survivors", [])
                    
                    await broadcast_to_room(room_code, {
                        "type": "info",
                        "message": "The host has passed judgment! Evaluating variables..."
                    })
                    await broadcast_to_room(room_code, {"type": "generating_verdict"})
                    
                    ideal_team = engine.secret_verdict.get("ideal_survivors", [])
                    
                    final_data = await generate_final_verdict(
                        engine.api_key,
                        engine.game_language,
                        engine.current_scenario,
                        engine.player_roles,
                        ideal_team,
                        chosen
                    )
                    
                    if final_data:
                        final_data["player_survivors"] = chosen 
                        final_data["ai_ideal_survivors"] = ideal_team
                        
                        # Apply encapsulation here!
                        engine.set_final_verdict(final_data)
                        await broadcast_to_room(room_code, {"type": "show_verdict", "data": final_data})
                    else:
                        await broadcast_to_room(room_code, {"type": "error", "message": "Failed to generate the final verdict."})

    except WebSocketDisconnect:
        # 4. DISCONNECTION HANDLING
        if room_code in active_connections and player_name in active_connections[room_code]:
            del active_connections[room_code][player_name]
            
        if room_code in rooms:
            rooms[room_code].disconnect_player(player_name)
            
            # Cleanup: Delete room if empty
            if not active_connections[room_code]:
                del rooms[room_code]
                del active_connections[room_code]
            else:
                await broadcast_to_room(room_code, {
                    "type": "lobby_update", 
                    "players": list(rooms[room_code].players.keys()),
                    "active_players": rooms[room_code].active_player_names,
                    "host": rooms[room_code].host
                })