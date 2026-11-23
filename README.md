# Farm AMR Console (Python)

Always-on Python server for **2 farm AMRs and 8 garden beds**, with a live web dashboard.
The robots, beds and tasks run in the Python server, so the farm keeps working when no browser is open.

**No packages to install.** It uses only the Python standard library (Python 3.9 or newer).

## Run
```bash
cd farm-py
python3 server.py              # → http://localhost:3000
```
- Different port: `PORT=8080 python3 server.py`
- Stop: Ctrl + C. State is saved to `data/state.json` and restored on the next start.
- Start fresh: delete the `data` folder, or press **RESET DEMO** in the dashboard.

Keep it running 24/7 with pm2: `pm2 start ecosystem.config.js && pm2 save`. The process is named `farm-py`.
Or use Docker: `docker compose up -d --build`.

## Files
| File | What it does |
|---|---|
| `world.py` | Farm map: waypoints, tracks, beds, crops, task types. Edit this to change the farm. |
| `engine.py` | `FarmEngine`: robots, routing (Dijkstra), safe distance, tasks, bed moisture and growth, auto-water |
| `server.py` | asyncio HTTP + WebSocket server, 20 ticks/s, live stream 10/s, saves state every 3 s |
| `public/index.html`, `public/app.js` | Dashboard (HTML/JavaScript, served by Python). `/world.js` is generated from `world.py`. |

## How a task works
1. **Pickup point:** the AMR collects the tool (water_tools, seed_box, fertilizer, harvest_crates).
2. **Work point:** it drives along the garden bed row, watering, seeding, fertilizing or harvesting.
3. **Finish point:** it returns the tool, or unloads the harvest at harvest_store, then goes back to charge when it has no tasks left.

## REST API
```bash
curl http://localhost:3000/api/state
curl -X POST http://localhost:3000/api/tasks -H "Content-Type: application/json" \
  -d '{"type":"water","pickup":"PW","work":"V2a","finish":"PW","amount":20,"assignee":"auto","priority":"high"}'
curl -X POST http://localhost:3000/api/tasks/T-1005/cancel
curl -X POST http://localhost:3000/api/cmd -H "Content-Type: application/json" -d '{"op":"bed.quick","bed":"B3","type":"water"}'
```
Work points: B1 `V0a`, B2 `V1a`, B3 `V2a`, B4 `V3a`, B5 `V0b`, B6 `V1b`, B7 `V2b`, B8 `V3b`.
Pickup points: `PW` water, `PS` seeds, `PF` fertilizer, `PC` crates. Finish points: any of those, or `HS` harvest store.

## Use the engine from your own Python code
```python
from engine import FarmEngine
farm = FarmEngine()
farm.on('log', lambda e: print(e['msg']))
farm.init(None)
farm.cmd({'op': 'task.create', 'type': 'water', 'pickup': 'PW', 'work': 'V2a', 'finish': 'PW', 'amount': 20})
for _ in range(2000):
    farm.step(0.05)          # advance 0.05 s each call
print(farm.snapshot()['amrs'])
```

## Connecting real robots (ROS 2)
In `engine.py`:
- `move()` currently simulates driving. Replace it with the pose your robot publishes (for example an `rclpy` subscriber to `/amcl_pose`).
- `retarget()` decides each new goal. Send it to the robot instead, for example a Nav2 `NavigateToPose` action.

Keep everything else as it is: tasks, beds, history and the dashboard.
