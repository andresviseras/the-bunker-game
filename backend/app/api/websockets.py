import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set

from app.game.engine import BunkerEngine
from app.services.llm_service import generate_and_distribute_roles, generate_final_verdict

router = APIRouter()

# DICCIONARIO PRINCIPAL: { "codigo_sala": BunkerEngine }
rooms: Dict[str, BunkerEngine] = {}

# Mantiene un registro de las conexiones WebSocket activas por sala
# Estructura: { "codigo_sala": { "nombre_jugador": WebSocket } }
active_connections: Dict[str, Dict[str, WebSocket]] = {}

async def broadcast_to_room(room_code: str, message: dict) -> None:
    """Envía un mensaje a todos los jugadores conectados de una sala específica."""
    if room_code in active_connections:
        connections = active_connections[room_code].values()
        tasks = []
        for connection in connections:
            tasks.append(asyncio.create_task(connection.send_json(message)))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

async def send_personal_to_room(room_code: str, player_name: str, message: dict) -> None:
    """Envía un mensaje privado a un jugador de una sala."""
    if room_code in active_connections and player_name in active_connections[room_code]:
        try:
            await active_connections[room_code][player_name].send_json(message)
        except Exception:
            pass

@router.websocket("/ws/{room_code}/{player_name}")
async def websocket_endpoint(websocket: WebSocket, room_code: str, player_name: str, api_key: str = ""):
    room_code = room_code.lower()
    
    # 1. GESTIÓN DE SALAS
    if room_code not in rooms:
        # Si la sala no existe, solo permitimos crearla si hay una API KEY
        if not api_key:
            await websocket.accept()
            await websocket.send_json({"type": "error", "message": "Sala no encontrada."})
            await websocket.close()
            return
        # Creamos la sala con la clave proporcionada
        rooms[room_code] = BunkerEngine(api_key=api_key)
        active_connections[room_code] = {}
    
    # Referencia rápida al motor de esta sala
    engine = rooms[room_code]
    
    await websocket.accept()
    active_connections[room_code][player_name] = websocket
    
    # Conectamos al jugador. Si mandó api_key, lo tratamos como creador/host
    is_creator = bool(api_key)
    engine.connect_player(player_name, is_creator)
    
    # 2. LOGICA DE RECONEXIÓN
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

    # Avisamos del estado del lobby
    await broadcast_to_room(room_code, {
        "type": "lobby_update", 
        "players": list(engine.players.keys()),
        "active_players": engine.active_player_names,
        "host": engine.host
    })
    
    try:
        while True:
            # 3. RECEPCIÓN DE MENSAJES
            data = await websocket.receive_text()
            msg = json.loads(data)
            action = msg.get("action")
            
            # Resetear Juego (Cualquiera puede, pero generalmente lo hará el host)
            if action == "reset_game":
                engine.game_phase = "lobby"
                engine.player_roles = {}
                engine.votes = {}
                engine.final_results = None
                engine.secret_verdict = None
                
                await broadcast_to_room(room_code, {
                    "type": "lobby_update", 
                    "players": list(engine.players.keys()),
                    "active_players": engine.active_player_names,
                    "host": engine.host
                })
                continue
            
            # --- ACCIONES EXCLUSIVAS DEL HOST ---
            if player_name == engine.host:
                if action == "start_game":
                    scenario = msg.get("scenario", "Default scenario")
                    language = msg.get("language", "en")
                    
                    engine.start_game(scenario, language)
                    await broadcast_to_room(room_code, {"type": "game_starting"})
                    
                    # Llamamos al LLM con la API key específica de la sala
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
                        await broadcast_to_room(room_code, {"type": "error", "message": "Fallo en el Game Master de IA. Comprueba la API Key."})

                elif action == "submit_host_selection":
                    chosen = msg.get("survivors", [])
                    
                    await broadcast_to_room(room_code, {
                        "type": "info",
                        "message": "¡El anfitrión ha dictado sentencia! Evaluando variables..."
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
                        
                        engine.final_results = final_data
                        engine.game_phase = "verdict"
                        await broadcast_to_room(room_code, {"type": "show_verdict", "data": final_data})
                    else:
                        await broadcast_to_room(room_code, {"type": "error", "message": "Fallo al generar el veredicto final."})

    except WebSocketDisconnect:
        # 4. MANEJO DE DESCONEXIONES
        if room_code in active_connections and player_name in active_connections[room_code]:
            del active_connections[room_code][player_name]
            
        # Si la sala existe, desconectamos al jugador en el motor
        if room_code in rooms:
            rooms[room_code].disconnect_player(player_name)
            
            # Limpieza: Si no queda nadie conectado, borramos la sala entera
            if not active_connections[room_code]:
                del rooms[room_code]
                del active_connections[room_code]
            else:
                # Avisar al resto de que alguien se ha ido
                await broadcast_to_room(room_code, {
                    "type": "lobby_update", 
                    "players": list(rooms[room_code].players.keys()),
                    "active_players": rooms[room_code].active_player_names,
                    "host": rooms[room_code].host
                })