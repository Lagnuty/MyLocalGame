from flask import Flask, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import json
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dodger_battle_royale_secret'
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25)

# Game state
GAME_WIDTH = 800
GAME_HEIGHT = 400
OBSTACLE_WIDTH = 40
OBSTACLE_HEIGHT = 40
PLAYER_WIDTH = 30
PLAYER_HEIGHT = 30
OBSTACLE_SPEED = 5

class GameState:
    def __init__(self):
        self.players = {}  # {player_id: {name, x, y, alive}}
        self.obstacles = []  # [{x, y}]
        self.round_active = False
        self.wave = 0
        self.spawn_counter = 0
        
    def add_player(self, player_id, name):
        self.players[player_id] = {
            'name': name,
            'x': GAME_WIDTH // 2,
            'y': GAME_HEIGHT - 50,
            'alive': True,
            'score': 0
        }
        
    def remove_player(self, player_id):
        if player_id in self.players:
            del self.players[player_id]
            
    def get_alive_count(self):
        return sum(1 for p in self.players.values() if p['alive'])
    
    def get_winner(self):
        for pid, p in self.players.items():
            if p['alive']:
                return pid
        return None

game_state = GameState()

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def on_connect():
    print(f'Client connected: {dict(request.args)}')
    emit('connection_response', {'data': 'Connected'})

@socketio.on('join_game')
def on_join_game(data):
    player_id = request.sid
    player_name = data.get('name', f'Player {len(game_state.players) + 1}')[:15]
    
    game_state.add_player(player_id, player_name)
    print(f'Player joined: {player_name} ({player_id})')
    
    # Broadcast updated player list
    broadcast_game_state()

@socketio.on('player_move')
def on_player_move(data):
    player_id = request.sid
    if player_id in game_state.players:
        x = data.get('x', 0)
        # Constrain to game bounds
        x = max(0, min(x, GAME_WIDTH - PLAYER_WIDTH))
        game_state.players[player_id]['x'] = x

@socketio.on('disconnect')
def on_disconnect():
    player_id = request.sid
    if player_id in game_state.players:
        player_name = game_state.players[player_id]['name']
        game_state.remove_player(player_id)
        print(f'Player left: {player_name}')
        broadcast_game_state()

def broadcast_game_state():
    state = {
        'players': game_state.players,
        'obstacles': game_state.obstacles,
        'round_active': game_state.round_active,
        'wave': game_state.wave
    }
    socketio.emit('game_state', state, to=None)

def start_round():
    if len(game_state.players) >= 1:
        game_state.round_active = True
        game_state.wave += 1
        game_state.spawn_counter = 0
        game_state.obstacles = []
        
        # Reset all players
        for player in game_state.players.values():
            player['alive'] = True
            player['x'] = GAME_WIDTH // 2
        
        broadcast_game_state()
        print(f'Round {game_state.wave} started with {len(game_state.players)} players')

def game_loop():
    if not game_state.round_active:
        return
    
    # Spawn obstacles
    game_state.spawn_counter += 1
    if game_state.spawn_counter % max(1, 15 - game_state.wave) == 0:
        game_state.obstacles.append({
            'x': GAME_WIDTH,
            'y': random.randint(0, GAME_HEIGHT - OBSTACLE_HEIGHT)
        })
    
    # Move obstacles
    for obstacle in game_state.obstacles[:]:
        obstacle['x'] -= OBSTACLE_SPEED
        if obstacle['x'] < -OBSTACLE_WIDTH:
            game_state.obstacles.remove(obstacle)
    
    # Check collisions
    for player_id, player in game_state.players.items():
        if not player['alive']:
            continue
        
        px, py = player['x'], player['y']
        for obstacle in game_state.obstacles:
            ox, oy = obstacle['x'], obstacle['y']
            
            # Simple AABB collision
            if (px < ox + OBSTACLE_WIDTH and
                px + PLAYER_WIDTH > ox and
                py < oy + OBSTACLE_HEIGHT and
                py + PLAYER_HEIGHT > oy):
                player['alive'] = False
    
    # Check if round is over
    alive_count = game_state.get_alive_count()
    if alive_count <= 1 and len(game_state.players) > 1:
        game_state.round_active = False
        winner_id = game_state.get_winner()
        if winner_id and winner_id in game_state.players:
            game_state.players[winner_id]['score'] += 1
        
        broadcast_game_state()
        socketio.emit('round_end', {'winner': game_state.players.get(winner_id, {}).get('name', 'Unknown')})
    else:
        broadcast_game_state()

@socketio.on('start_round')
def on_start_round():
    start_round()

def game_tick():
    while True:
        game_loop()
        socketio.sleep(0.016)  # ~60 FPS

if __name__ == '__main__':
    import threading
    
    # Start game loop in separate thread
    game_thread = threading.Thread(target=game_tick, daemon=True)
    game_thread.start()
    
    print("="*50)
    print("🎮 Dodger Battle Royale Server")
    print("="*50)
    print("Server running on: http://0.0.0.0:5000")
    print("Players can join via: http://<your_ip>:5000")
    print("="*50)
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
