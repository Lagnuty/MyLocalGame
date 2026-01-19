from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import json
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dodger_battle_royale_secret'
socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25)

# Game state
GAME_WIDTH = 1200
GAME_HEIGHT = 600
OBSTACLE_WIDTH = 40
OBSTACLE_HEIGHT = 40
PLAYER_WIDTH = 30
PLAYER_HEIGHT = 30
OBSTACLE_SPEED_BASE = 5
OBSTACLE_SPEED_MAX = 13
WAVE_TICKS = 420  # ~7 секунд при 60 FPS
MAX_OBSTACLES = 10
SAFE_GAP = PLAYER_HEIGHT + 10
POWERUP_SIZE = 24
MAX_POWERUPS = 3
POWERUP_TYPES = ['bonus', 'shield', 'speed', 'freeze']  # bonus=+1 score, others=runes
RUNE_DURATION = 240  # ~4 сек при 60 FPS

class GameState:
    def __init__(self):
        self.players = {}  # {player_id: {name, x, y, alive, ready}}
        self.obstacles = []  # [{x, y}]
        self.round_active = False
        self.wave = 0
        self.spawn_counter = 0
        self.elimination_order = []  # [(player_id, timestamp)]
        self.last_spawn_y = None
        self.obstacle_speed = OBSTACLE_SPEED_BASE
        self.wave_timer = 0
        self.powerups = []  # [{x, y, type}]
        self.powerup_counter = 0
        self.last_broadcast_state = None
        self.broadcast_throttle = 0
        
    def add_player(self, player_id, name):
        self.players[player_id] = {
            'name': name,
            'nm': name,  # compact
            'x': GAME_WIDTH // 2,
            'y': GAME_HEIGHT - 60,
            'alive': True,
            'a': True,  # compact
            'score': 0,
            's': 0,  # compact
            'ready': False,
            'rd': False,  # compact
            'active_rune': None,
            'r': None,  # compact
            'rune_timer': 0,
            'ping': 0
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

    def all_ready(self):
        return len(self.players) > 0 and all(p.get('ready') for p in self.players.values())

game_state = GameState()

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def on_connect(auth=None):
    # auth arg is passed by recent Flask-SocketIO; keep compatible
    try:
        client_args = dict(request.args) if request else {}
    except Exception:
        client_args = {}
    print(f'Client connected: {client_args}')
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
        y = data.get('y', GAME_HEIGHT - PLAYER_HEIGHT)
        # Constrain to game bounds
        x = max(0, min(x, GAME_WIDTH - PLAYER_WIDTH))
        y = max(0, min(y, GAME_HEIGHT - PLAYER_HEIGHT))
        old_x, old_y = game_state.players[player_id]['x'], game_state.players[player_id]['y']
        # Only update if moved >2 pixels
        if abs(x - old_x) > 2 or abs(y - old_y) > 2:
            game_state.players[player_id]['x'] = x
            game_state.players[player_id]['y'] = y

@socketio.on('disconnect')
def on_disconnect():
    player_id = request.sid if request else None
    if player_id and player_id in game_state.players:
        player_name = game_state.players[player_id]['name']
        game_state.remove_player(player_id)
        print(f'Player left: {player_name}')
        broadcast_game_state()

def broadcast_game_state():
    if game_state.broadcast_throttle > 0:
        game_state.broadcast_throttle -= 1
        return
    game_state.broadcast_throttle = 1  # send every ~3 frames
    
    # Compact delta format
    state = {
        'p': {pid: {'x': p['x'], 'y': p['y'], 'a': p.get('a'), 'rd': p.get('rd'), 'r': p.get('r'), 'nm': p.get('nm'), 's': p.get('s'), 'ping': p.get('ping', 0)} 
              for pid, p in game_state.players.items()},
        'o': [[o['x'], o['y']] for o in game_state.obstacles],
        'u': [[u['x'], u['y'], u['type']] for u in game_state.powerups],
        'w': game_state.wave,
        'g': game_state.round_active
    }
    socketio.emit('gs', state)


def has_safe_gap(obstacles):
    # Ensure there is at least one vertical gap for the player to pass
    intervals = sorted((o['y'], o['y'] + OBSTACLE_HEIGHT) for o in obstacles)
    prev = 0
    for start, end in intervals:
        if start - prev >= SAFE_GAP:
            return True
        prev = max(prev, end)
    return GAME_HEIGHT - prev >= SAFE_GAP

def start_round(force=False):
    if len(game_state.players) >= 1 and (force or game_state.all_ready()):
        game_state.round_active = True
        game_state.wave = 1  # reset waves so they don't stack across rounds
        game_state.spawn_counter = 0
        game_state.obstacles = []
        game_state.powerups = []
        game_state.powerup_counter = 0
        game_state.elimination_order = []
        game_state.last_spawn_y = None
        game_state.obstacle_speed = OBSTACLE_SPEED_BASE
        game_state.wave_timer = 0
        
        # Reset all players
        for player in game_state.players.values():
            player['alive'] = True
            player['a'] = True
            player['x'] = GAME_WIDTH // 2
            player['y'] = GAME_HEIGHT - 60
            # Require повторное голосование в следующих раундах
            player['ready'] = False
            player['rd'] = False
        
        broadcast_game_state()
        print(f'Round started with {len(game_state.players)} players')

def game_loop():
    if not game_state.round_active:
        return

    # Wave progression and speed scaling
    game_state.wave_timer += 1
    if game_state.wave_timer % WAVE_TICKS == 0:
        game_state.wave += 1
        game_state.obstacle_speed = min(OBSTACLE_SPEED_MAX, OBSTACLE_SPEED_BASE + 1.0 * (game_state.wave - 1))

    # Spawn obstacles with guaranteed gap and cap
    game_state.spawn_counter += 1
    spawn_interval = max(5, 14 - game_state.wave)  # faster progression
    if len(game_state.obstacles) < MAX_OBSTACLES and game_state.spawn_counter % spawn_interval == 0:
        tries = 6
        candidate_y = None
        for _ in range(tries):
            base = game_state.last_spawn_y
            if base is None:
                y = random.randint(0, GAME_HEIGHT - OBSTACLE_HEIGHT)
            else:
                # bias away from last spawn to avoid stacking
                offset = random.choice([-1, 1]) * random.randint(OBSTACLE_HEIGHT, 3 * OBSTACLE_HEIGHT)
                y = max(0, min(GAME_HEIGHT - OBSTACLE_HEIGHT, base + offset))
            tmp_obstacles = game_state.obstacles + [{'x': GAME_WIDTH, 'y': y}]
            if has_safe_gap(tmp_obstacles):
                candidate_y = y
                break
        if candidate_y is not None:
            game_state.obstacles.append({'x': GAME_WIDTH, 'y': candidate_y})
            game_state.last_spawn_y = candidate_y

    # Spawn powerups/runes occasionally
    game_state.powerup_counter += 1
    if len(game_state.powerups) < MAX_POWERUPS and game_state.powerup_counter % 320 == 0:
        py = random.randint(0, GAME_HEIGHT - POWERUP_SIZE)
        ptype = random.choice(POWERUP_TYPES)
        game_state.powerups.append({'x': GAME_WIDTH, 'y': py, 'type': ptype})
    
    # Move obstacles (with freeze slowdown if rune active)
    has_freeze = any(p.get('active_rune') == 'freeze' for p in game_state.players.values())
    speed_mult = 0.35 if has_freeze else 1.0  # slow when freeze active
    for obstacle in game_state.obstacles[:]:
        obstacle['x'] -= game_state.obstacle_speed * speed_mult
        if obstacle['x'] < -OBSTACLE_WIDTH:
            game_state.obstacles.remove(obstacle)

    # Move powerups (slower than obstacles)
    for powerup in game_state.powerups[:]:
        powerup['x'] -= game_state.obstacle_speed * 0.6
        if powerup['x'] < -POWERUP_SIZE:
            game_state.powerups.remove(powerup)

    # Update rune timers and apply effects
    for player in game_state.players.values():
        if player.get('active_rune'):
            player['rune_timer'] -= 1
            if player['rune_timer'] <= 0:
                player['active_rune'] = None
    
    # Check collisions
    for player_id, player in game_state.players.items():
        if not player['alive']:
            continue
        
        px, py = player['x'], player['y']

        # Powerup pickup
        for powerup in game_state.powerups[:]:
            ux, uy = powerup['x'], powerup['y']
            if (px < ux + POWERUP_SIZE and
                px + PLAYER_WIDTH > ux and
                py < uy + POWERUP_SIZE and
                py + PLAYER_HEIGHT > uy):
                ptype = powerup.get('type', 'bonus')
                if ptype == 'bonus':
                    game_state.players[player_id]['score'] += 1
                    game_state.players[player_id]['s'] = game_state.players[player_id]['score']
                else:  # shield, speed, freeze
                    game_state.players[player_id]['active_rune'] = ptype
                    game_state.players[player_id]['r'] = ptype
                    game_state.players[player_id]['rune_timer'] = RUNE_DURATION
                game_state.powerups.remove(powerup)

        # Obstacle collisions (shield blocks damage)
        if player.get('active_rune') != 'shield':
            for obstacle in game_state.obstacles:
                ox, oy = obstacle['x'], obstacle['y']
                
                # Simple AABB collision
                if (px < ox + OBSTACLE_WIDTH and
                    px + PLAYER_WIDTH > ox and
                    py < oy + OBSTACLE_HEIGHT and
                    py + PLAYER_HEIGHT > oy):
                    player['alive'] = False
                    player['a'] = False
                    game_state.elimination_order.append((player_id, datetime.utcnow()))
    
    # Check if round is over
    alive_count = game_state.get_alive_count()
    if alive_count <= 1 and len(game_state.players) > 1:
        game_state.round_active = False
        winner_id = game_state.get_winner()

        # Determine placements: winner first, then last eliminated, etc.
        placements = []
        if winner_id:
            placements.append(winner_id)
        # Add eliminated players in reverse elimination (last longer = higher place)
        for pid, _ts in reversed(game_state.elimination_order):
            if pid not in placements:
                placements.append(pid)

        # Award points: 1st=3, 2nd=2, 3rd=1
        points_table = [3, 2, 1]
        placement_info = []
        for idx, pid in enumerate(placements):
            if pid in game_state.players and idx < len(points_table):
                pts = points_table[idx]
                game_state.players[pid]['score'] += pts
                game_state.players[pid]['s'] = game_state.players[pid]['score']
                placement_info.append({'name': game_state.players[pid]['name'], 'points': pts, 'place': idx + 1})

        # Reset wave counter after round ends
        game_state.wave = 0
        broadcast_game_state()
        socketio.emit('round_end', {
            'winner': game_state.players.get(winner_id, {}).get('name', 'Unknown'),
            'placements': placement_info
        })
    else:
        broadcast_game_state()

@socketio.on('start_round')
def on_start_round():
    # Manual start (host) still possible, bypassing ready-check if needed
    start_round(force=True)


@socketio.on('player_ready')
def on_player_ready():
    player_id = request.sid if request else None
    if not player_id or player_id not in game_state.players:
        return
    game_state.players[player_id]['ready'] = True
    game_state.players[player_id]['rd'] = True
    broadcast_game_state()
    if not game_state.round_active and game_state.all_ready():
        start_round()


@socketio.on('ping')
def on_ping(data):
    player_id = request.sid if request else None
    if player_id and player_id in game_state.players:
        client_time = data.get('t', 0)
        current_time = int(datetime.utcnow().timestamp() * 1000)  # ms
        ping = current_time - client_time
        game_state.players[player_id]['ping'] = max(0, ping)
    emit('pong', {'t': data.get('t', 0)})

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
