"""Farm fleet engine: 2 AMRs working 8 garden beds.

Task flow:  go to pickup point -> collect tool -> go to bed (work point)
            -> drive the bed row doing the work -> go to finish point -> return tool / unload harvest

To connect real robots: replace the motion in move() with poses reported by the robot
(e.g. a ROS 2 subscriber), and send each goal from retarget() to the robot's navigation API.
"""
import heapq
import math
import time

from world import (PX, V_MAX, ACC, LOAD_T, N, EDGES, BEDS, TYPES, PRANK, PICKS, FINISHES, WAIT,
                   name, bed_of_work, work_duration)


def now_ms():
    return int(time.time() * 1000)


def sign(v):
    return (v > 0) - (v < 0)


class FarmEngine:
    def __init__(self):
        self.handlers = {}
        self.adj = {}
        for a, b in EDGES:
            self.adj.setdefault(a, []).append(b)
            self.adj.setdefault(b, []).append(a)
        self.S = None
        self.amrs = []
        self.speed = 1
        self.dispatch_acc = 0.0
        self.auto_acc = 0.0

    # ---------------- events ----------------
    def on(self, ev, fn):
        self.handlers.setdefault(ev, []).append(fn)

    def emit(self, ev, payload=None):
        for fn in self.handlers.get(ev, []):
            try:
                fn(payload)
            except Exception as e:  # never let a listener stop the farm
                print('listener error:', e)

    def log(self, msg, kind=''):
        e = {'t': now_ms(), 'msg': msg, 'kind': kind}
        self.S['feed'].insert(0, e)
        del self.S['feed'][300:]
        self.emit('log', e)

    def changed(self):
        self.emit('changed')

    # ---------------- helpers ----------------
    @staticmethod
    def nd(a, b):
        return math.hypot(N[a]['x'] - N[b]['x'], N[a]['y'] - N[b]['y'])

    def route(self, s, g, avoid=None):
        """Shortest path over the track graph (Dijkstra)."""
        if s == g:
            return [s]
        dist, prev, done, heap = {s: 0.0}, {}, set(), [(0.0, s)]
        while heap:
            d, u = heapq.heappop(heap)
            if u in done:
                continue
            if u == g:
                break
            done.add(u)
            for v in self.adj.get(u, []):
                if avoid and v in avoid and v != g:
                    continue
                x = d + self.nd(u, v)
                if v not in dist or x < dist[v]:
                    dist[v] = x
                    prev[v] = u
                    heapq.heappush(heap, (x, v))
        if g not in dist:
            return None
        out = [g]
        while out[0] != s:
            out.insert(0, prev[out[0]])
        return out

    def amr_by_id(self, aid):
        return next((a for a in self.amrs if a['id'] == aid), None)

    def task_of(self, a):
        return next((t for t in self.S['tasks'] if t['id'] == a['taskId']), None)

    @staticmethod
    def bed_label(node):
        b = bed_of_work(node)
        return f"{b['id']} {b['crop']}" if b else name(node)

    # ---------------- state ----------------
    def seed(self):
        now, m = now_ms(), 60000
        start = {'B1': (62, 55, 70, True), 'B2': (34, 40, 45, True), 'B3': (18, 30, 60, True), 'B4': (75, 65, 88, True),
                 'B5': (50, 20, 15, True), 'B6': (28, 45, 35, True), 'B7': (80, 70, 95, True), 'B8': (10, 10, 0, False)}
        beds = {}
        for bid in BEDS:
            mo, nu, gr, pl = start[bid]
            beds[bid] = {'moisture': mo, 'nutrients': nu, 'growth': gr, 'planted': pl, 'lastWatered': now - (100 - mo) * 15000,
                         'lastFertilized': None, 'lastSeeded': None, 'lastHarvested': None, 'dryWarned': False}

        def ev(t, msg):
            return {'t': t, 'msg': msg}

        def T(tid, ttype, work, amount, assignee, priority, ago):
            return {'id': tid, 'type': ttype, 'pickup': TYPES[ttype]['tool'], 'work': work, 'finish': TYPES[ttype]['finish'],
                    'amount': amount, 'assignee': assignee, 'priority': priority, 'status': 'queued', 'amr': None,
                    'createdAt': now - ago * m, 'startedAt': None, 'edits': 0, 'distance': 0, 'progress': 0,
                    'events': [ev(now - ago * m, 'Created')]}

        return {
            'seq': 1004, 'feed': [], 'beds': beds,
            'store': {'kg': 18.5, 'byCrop': {'Tomato': 8.5, 'Okra': 10}},
            'auto': {'water': True, 'threshold': 25, 'liters': 20},
            'tasks': [T('T-1002', 'water', 'V2a', 20, 'auto', 'high', 3), T('T-1003', 'harvest', 'V2b', 2, 'auto', 'normal', 2),
                      T('T-1004', 'seed', 'V3b', 200, 'AMR 02', 'normal', 1)],
            'history': [
                {'id': 'T-1001', 'type': 'fertilize', 'pickup': 'PF', 'work': 'V0a', 'finish': 'PF', 'amount': 4, 'assignee': 'auto', 'priority': 'normal',
                 'status': 'completed', 'amr': 'AMR 01', 'createdAt': now - 50 * m, 'startedAt': now - 49 * m, 'finishedAt': now - 46 * m, 'edits': 0,
                 'distance': 21.4, 'progress': 1, 'events': [ev(now - 50 * m, 'Created'), ev(now - 49 * m, 'Assigned to AMR 01'),
                 ev(now - 48 * m, 'Collected Fertilizer at fertilizer'), ev(now - 47 * m, 'Fertilizing B1 Tomato done'), ev(now - 46 * m, 'Returned tool to fertilizer')]},
                {'id': 'T-1000', 'type': 'harvest', 'pickup': 'PC', 'work': 'V3a', 'finish': 'HS', 'amount': 2, 'assignee': 'auto', 'priority': 'normal',
                 'status': 'completed', 'amr': 'AMR 02', 'createdAt': now - 80 * m, 'startedAt': now - 79 * m, 'finishedAt': now - 75 * m, 'edits': 0,
                 'distance': 15.8, 'progress': 1, 'harvestKg': 10, 'events': [ev(now - 80 * m, 'Created'), ev(now - 79 * m, 'Assigned to AMR 02'),
                 ev(now - 77 * m, 'Harvested 10 kg Okra from B4'), ev(now - 75 * m, 'Unloaded 10 kg at harvest_store')]},
            ],
        }

    @staticmethod
    def mk_amr(aid, cls, node, battery):
        return {'id': aid, 'cls': cls, 'x': N[node]['x'], 'y': N[node]['y'], 'heading': -math.pi / 2, 'target': -math.pi / 2, 'v': 0.0,
                'cell': node, 'claim': None, 'path': [], 'dest': None, 'goal': None, 'phase': 'none', 'mission': None, 'taskId': None,
                'carrying': None, 'loadKind': None, 'loadT': 0.0, 'battery': battery, 'odo': 0.0, 'paused': False, 'hold': '', 'holdT': 0.0,
                'blocker': None, 'cool': 0.0, 'idleT': 0.0, 'rest': 'charging', 'yielding': False, 'yieldT': 0.0, 'resume': None,
                'workSpeed': 0.0, 'workLen': 0.0, 'workDone': 0.0}

    def fresh(self):
        self.S = self.seed()
        self.amrs = [self.mk_amr('AMR 01', 'a1', 'C1', 78), self.mk_amr('AMR 02', 'a2', 'C2', 64)]
        self.speed = 1

    def init(self, saved=None):
        if saved and isinstance(saved, dict) and saved.get('S') and isinstance(saved.get('AMRS'), list) and saved['S'].get('beds'):
            self.S, self.amrs, self.speed = saved['S'], saved['AMRS'], saved.get('speed', 1)
            self.log('Farm fleet resumed from saved state', 'ok')
        else:
            self.fresh()
            self.log('Farm fleet started · AMR 01, AMR 02 · 8 garden beds', 'ok')

    def export_state(self):
        return {'S': self.S, 'AMRS': self.amrs, 'speed': self.speed, 'savedAt': now_ms()}

    # ---------------- planning ----------------
    def plan_path(self, a, target, avoid=None):
        start, prefix = a['cell'], []
        if a['claim'] and a['path'] and a['path'][0] == a['claim'] and N[a['claim']]['t'] != 'lane':
            start, prefix = a['claim'], [a['claim']]
        r = self.route(start, target, avoid)
        if not r:
            return False
        a['path'] = prefix + r[1:]
        a['dest'] = target
        return True

    def retarget(self, a, node, kind):
        a['goal'] = {'node': node, 'kind': kind}
        a['yielding'] = False
        a['rest'] = None
        a['idleT'] = 0
        if a['phase'] == 'work':          # finish the bed row first
            return
        a['phase'] = 'drive'
        self.plan_path(a, node)

    def send_to(self, a, node, kind, mission):
        a['mission'] = mission
        self.retarget(a, node, kind)

    def stop_at(self, a):
        mid = a['claim'] and N[a['claim']]['t'] != 'lane'
        target = a['claim'] if mid else a['cell']
        a['path'] = [a['claim']] if mid else []
        a['goal'] = {'node': target, 'kind': 'idle'}
        a['dest'] = target
        a['phase'] = 'drive'
        a['yielding'] = False

    def occupied(self, node, except_amr):
        return any(o is not except_amr and (o['cell'] == node or o['claim'] == node or (o['goal'] and o['goal']['node'] == node))
                   for o in self.amrs)

    @staticmethod
    def busy(a):
        return a['phase'] == 'work' or bool(a['loadKind'])

    def go_charge(self, a, why=None):
        if self.busy(a):
            return {'ok': False, 'msg': f"{a['id']} is working; try again when it finishes the row"}
        pref = ['C1', 'C2'] if a['id'] == 'AMR 01' else ['C2', 'C1']
        cid = next((c for c in pref if not self.occupied(c, a)), pref[0])
        if a['cell'] == cid and a['phase'] == 'none':
            a['rest'] = 'charging'
            return {'ok': True}
        self.send_to(a, cid, 'charge', 'charge')
        self.log(f"{a['id']} {why or 'heading to'} {name(cid)}")
        return {'ok': True, 'msg': f"{a['id']} → {name(cid)}"}

    def go_park(self, a):
        if self.busy(a):
            return {'ok': False, 'msg': f"{a['id']} is working; try again when it finishes the row"}
        pid = next((k for k in [WAIT[a['id']], 'K1', 'K2'] if not self.occupied(k, a)), WAIT[a['id']])
        self.send_to(a, pid, 'park', 'park')
        self.log(f"{a['id']} heading to {name(pid)}")
        return {'ok': True, 'msg': f"{a['id']} → {name(pid)}"}

    @staticmethod
    def at_charger(a):
        return a['cell'] in ('C1', 'C2')

    # ---------------- safe distance between AMRs ----------------
    def blocked_by(self, a, nxt):
        for o in self.amrs:
            if o is a:
                continue
            occ = {x for x in (o['cell'], o['claim']) if x}
            if nxt in occ:
                return {'msg': f"Holding: {o['id']} in the way", 'o': o['id']}
            if len(a['path']) > 1 and a['path'][1] in occ:
                return {'msg': f"Keeping safe distance from {o['id']}", 'o': o['id']}
        return None

    def bfs_nodes(self, start):
        seen, q, out = {start}, [(start, 0)], []
        while q:
            u, d = q.pop(0)
            out.append((u, d))
            for v in self.adj.get(u, []):
                if v not in seen:
                    seen.add(v)
                    q.append((v, d + 1))
        return out

    def nudge(self, o, a):
        if o['cell'] not in self.adj:
            return
        bad = {x for x in [a['cell'], a['claim'], *a['path']] if x}
        for u, d in self.bfs_nodes(o['cell']):
            if d == 0 or u in bad or self.occupied(u, o) or N[u]['t'] in ('pick', 'store', 'work'):
                continue
            o['mission'] = None
            o['goal'] = {'node': u, 'kind': 'idle'}
            o['phase'] = 'drive'
            o['rest'] = None
            o['idleT'] = 0
            self.plan_path(o, u)
            self.log(f"{o['id']} moved aside for {a['id']}", 'warn')
            return

    def yield_from(self, a, o):
        if a['cell'] not in self.adj:
            return
        bad = {x for x in [o['cell'], o['claim'], *o['path'][:6]] if x}
        for u, d in self.bfs_nodes(a['cell']):
            if d == 0 or u in bad:
                continue
            r = self.route(a['cell'], u, bad)
            if r:
                a['resume'] = a['dest']
                a['path'] = r[1:]
                a['dest'] = u
                a['yielding'] = True
                a['yieldT'] = 3
                a['holdT'] = 0
                self.log(f"{a['id']} giving way to {o['id']}", 'warn')
                return

    def resolve(self, a):
        if a['phase'] == 'work' or a['holdT'] < 2.5 or a['cool'] > 0 or not a['blocker']:
            return
        a['cool'] = 1.5
        o = self.amr_by_id(a['blocker'])
        if o['phase'] == 'none' and not o['paused'] and not o['loadKind']:
            self.nudge(o, a)
            a['holdT'] = 0
            return
        if o['phase'] == 'work' or not a['dest']:
            return
        avoid = {x for x in [o['cell'], o['claim'], *o['path'][:3]] if x}
        if a['dest'] in avoid:
            return
        before = list(a['path'])
        if self.plan_path(a, a['dest'], avoid) and a['path'] != before:
            a['holdT'] = 0
            self.log(f"{a['id']} re-routed around {o['id']}", 'warn')
            return
        if o['blocker'] == a['id'] and o['hold'] and a['id'] > o['id']:
            self.yield_from(a, o)

    # ---------------- motion ----------------
    @staticmethod
    def remaining(a):
        d, px, py = 0.0, a['x'], a['y']
        for nid in a['path']:
            p = N[nid]
            d += math.hypot(p['x'] - px, p['y'] - py)
            px, py = p['x'], p['y']
        return d

    def move(self, a, dt, fixed=None):
        if not a['path']:
            a['v'] = 0
            return 0.0
        a['v'] = fixed if fixed else min(V_MAX, a['v'] + ACC * dt, max(math.sqrt(2 * ACC * self.remaining(a)), 5))
        d, moved = a['v'] * dt, 0.0
        while d > 0 and a['path']:
            nid = a['path'][0]
            p = N[nid]
            if a['claim'] != nid:
                b = self.blocked_by(a, nid)
                if b:
                    a['v'] = 0
                    a['hold'] = b['msg']
                    a['holdT'] += dt
                    a['blocker'] = b['o']
                    self.resolve(a)
                    break
                a['claim'] = nid
                a['hold'] = ''
                a['holdT'] = 0
                a['blocker'] = None
            dx, dy = p['x'] - a['x'], p['y'] - a['y']
            L = math.hypot(dx, dy)
            if L > 0.01:
                a['target'] = math.atan2(dy, dx)
            if d >= L:
                a['x'], a['y'] = p['x'], p['y']
                d -= L
                moved += L
                a['path'].pop(0)
                a['cell'] = nid
                a['claim'] = None
            else:
                a['x'] += dx / L * d
                a['y'] += dy / L * d
                moved += d
                d = 0
        if moved:
            a['odo'] += moved / PX
            a['battery'] = max(0, a['battery'] - moved / PX * 0.12)
            t = self.task_of(a)
            if t and a['mission'] == 'task':
                t['distance'] += moved / PX
        if not a['path']:
            a['v'] = 0
        return moved

    # ---------------- bed work ----------------
    def start_work(self, a, t):
        bed = bed_of_work(t['work'])
        a['phase'] = 'work'
        a['path'] = list(bed['lane'])
        a['hold'] = ''
        length, px, py = 0.0, a['x'], a['y']
        for nid in a['path']:
            length += math.hypot(N[nid]['x'] - px, N[nid]['y'] - py)
            px, py = N[nid]['x'], N[nid]['y']
        a['workLen'] = length
        a['workDone'] = 0
        a['workSpeed'] = length / work_duration(t['type'], t['amount'])
        t['status'] = 'working'
        t['progress'] = 0
        B = self.S['beds'][bed['id']]
        if t['type'] == 'seed':
            B['planted'] = True
            B['growth'] = 0
        if t['type'] == 'harvest':
            t['harvestKg'] = round((B['growth'] / 100 if B['planted'] else 0) * 6 * t['amount'], 1)
        verb = TYPES[t['type']]['verb']
        t['events'].append({'t': now_ms(), 'msg': f"{verb} {bed['id']} {bed['crop']} started"})
        self.log(f"{a['id']} {verb.lower()} {bed['id']} {bed['crop']}", 'warn')
        self.changed()

    def apply_work(self, a, t, dp):
        bed = bed_of_work(t['work'])
        B = self.S['beds'][bed['id']]
        if t['type'] == 'water':
            B['moisture'] = min(100, B['moisture'] + t['amount'] * 3.2 * dp)
            B['lastWatered'] = now_ms()
            if B['moisture'] > 30:
                B['dryWarned'] = False
        elif t['type'] == 'fertilize':
            B['nutrients'] = min(100, B['nutrients'] + t['amount'] * 12 * dp)
            B['lastFertilized'] = now_ms()
        elif t['type'] == 'seed':
            B['lastSeeded'] = now_ms()
        elif t['type'] == 'harvest':
            B['growth'] = max(0, B['growth'] - 100 * dp)
        if a['carrying'] and t['type'] != 'harvest':
            a['carrying']['left'] = max(0, a['carrying']['left'] - t['amount'] * dp)

    def finish_work(self, a, t):
        bed = bed_of_work(t['work'])
        B = self.S['beds'][bed['id']]
        a['phase'] = 'drive'
        t['progress'] = 1
        if t['type'] == 'harvest':
            B['planted'] = False
            B['growth'] = 0
            B['lastHarvested'] = now_ms()
            a['carrying'] = {'type': 'harvest', 'item': f"{bed['crop']} {t['harvestKg']} kg", 'amount': t['harvestKg'], 'unit': 'kg', 'left': t['harvestKg']}
            msg = f"Harvested {t['harvestKg']} kg {bed['crop']} from {bed['id']}"
        else:
            if a['carrying']:
                a['carrying']['left'] = 0
            msg = f"{TYPES[t['type']]['verb']} {bed['id']} {bed['crop']} done"
        t['events'].append({'t': now_ms(), 'msg': msg})
        self.log(f"{a['id']}: {msg}", 'ok')
        t['status'] = 'to_finish'
        self.retarget(a, t['finish'], 'finish')
        self.changed()

    # ---------------- robot tick ----------------
    def finish_task(self, t, status, msg):
        t['status'] = status
        t['finishedAt'] = now_ms()
        t['distance'] = round(t['distance'], 1)
        t['events'].append({'t': now_ms(), 'msg': msg})
        self.S['tasks'] = [x for x in self.S['tasks'] if x is not t]
        self.S['history'].insert(0, t)
        del self.S['history'][1000:]

    def arrive_goal(self, a):
        g, t = a['goal'], self.task_of(a)
        a['path'] = []
        a['v'] = 0
        if g['kind'] == 'pickup' and t:
            a['loadKind'] = 'collect'
            a['loadT'] = LOAD_T
            t['status'] = 'collecting'
            t['events'].append({'t': now_ms(), 'msg': f"Arrived at {name(t['pickup'])}"})
            self.log(f"{a['id']} at {name(t['pickup'])} · collecting {TYPES[t['type']]['item']}", 'warn')
            self.changed()
            return
        if g['kind'] == 'work' and t:
            other = next((o for o in self.amrs if o is not a and o['phase'] == 'work' and self.task_of(o)
                          and self.task_of(o)['work'] == t['work']), None)
            if other:
                a['hold'] = f"Waiting: {other['id']} is working this bed"
                return
            self.start_work(a, t)
            return
        if g['kind'] == 'finish' and t:
            a['loadKind'] = 'return'
            a['loadT'] = LOAD_T
            t['status'] = 'returning'
            self.log(f"{a['id']} at {name(t['finish'])} · {'unloading harvest' if t['type'] == 'harvest' else 'returning tool'}", 'warn')
            self.changed()
            return
        a['phase'] = 'none'
        a['goal'] = None
        mission, a['mission'] = a['mission'], None
        a['rest'] = 'charging' if g['kind'] == 'charge' else 'parked' if g['kind'] == 'park' else 'idle'
        if a['rest'] != 'idle':
            a['idleT'] = 0
        if mission == 'manual':
            self.log(f"{a['id']} reached {name(g['node'])}", 'ok')
        if g['kind'] == 'charge':
            self.log(f"{a['id']} docked at {name(g['node'])} · charging", 'ok')
        if g['kind'] == 'park':
            self.log(f"{a['id']} parked at {name(g['node'])}")

    def tick_amr(self, a, dt):
        a['cool'] = max(0, a['cool'] - dt)
        if not a['paused']:
            df = a['target'] - a['heading']
            df = math.atan2(math.sin(df), math.cos(df))
            a['heading'] += sign(df) * min(abs(df), 4 * dt)
            a['heading'] = math.atan2(math.sin(a['heading']), math.cos(a['heading']))
        if a['paused']:
            a['v'] = 0
            return
        if a['loadKind']:
            a['loadT'] -= dt
            if a['loadT'] <= 0:
                t, kind = self.task_of(a), a['loadKind']
                a['loadKind'] = None
                if not t:
                    a['phase'] = 'none'
                    a['carrying'] = None
                    return
                if kind == 'collect':
                    T = TYPES[t['type']]
                    a['carrying'] = {'type': t['type'], 'item': T['item'], 'amount': t['amount'], 'unit': T['unit'], 'left': t['amount']}
                    t['status'] = 'to_work'
                    t['events'].append({'t': now_ms(), 'msg': f"Collected {T['item']} ({t['amount']} {T['unit']}) at {name(t['pickup'])}"})
                    self.retarget(a, t['work'], 'work')
                    self.log(f"{a['id']} collected {T['item']} {t['amount']} {T['unit']} · to {self.bed_label(t['work'])}")
                else:
                    tid = t['id']
                    if t['type'] == 'harvest':
                        crop = bed_of_work(t['work'])['crop']
                        st = self.S['store']
                        st['kg'] = round(st['kg'] + t['harvestKg'], 1)
                        st['byCrop'][crop] = round(st['byCrop'].get(crop, 0) + t['harvestKg'], 1)
                        msg = f"Unloaded {t['harvestKg']} kg at {name(t['finish'])}"
                    else:
                        msg = f"Returned tool to {name(t['finish'])}"
                    self.finish_task(t, 'completed', msg)
                    a.update({'carrying': None, 'mission': None, 'taskId': None, 'phase': 'none', 'goal': None, 'rest': 'idle', 'idleT': 0})
                    self.log(f"{tid} completed by {a['id']}", 'ok')
                self.changed()
            return

        phase = a['phase']
        if phase == 'none':
            a['v'] = 0
            if a['rest'] == 'charging':
                if self.at_charger(a):
                    a['battery'] = min(100, a['battery'] + 0.9 * dt)
            elif a['rest'] == 'idle':
                a['idleT'] += dt
                if a['idleT'] > 3:
                    a['idleT'] = 0
                    self.go_charge(a, 'all tasks done · returning to')
        elif phase == 'drive':
            self.move(a, dt)
            if not a['path']:
                if a['yielding']:
                    a['hold'] = 'Giving way'
                    a['yieldT'] -= dt
                    if a['yieldT'] <= 0:
                        a['yielding'] = False
                        a['hold'] = ''
                        self.plan_path(a, a['resume'])
                elif a['goal'] and a['cell'] == a['goal']['node']:
                    self.arrive_goal(a)
                elif a['goal']:
                    self.plan_path(a, a['goal']['node'])
        elif phase == 'work':
            t = self.task_of(a)
            if not t:
                a['phase'] = 'drive'
                self.plan_path(a, a['cell'])
                return
            moved = self.move(a, dt, a['workSpeed'])
            if moved:
                dp = moved / a['workLen']
                a['workDone'] = min(1, a['workDone'] + dp)
                t['progress'] = a['workDone']
                self.apply_work(a, t, dp)
            if not a['path']:
                self.finish_work(a, t)

    # ---------------- beds over time ----------------
    def tick_beds(self, dt):
        for bid, B in self.S['beds'].items():
            B['moisture'] = max(0, B['moisture'] - 0.05 * dt)
            B['nutrients'] = max(0, B['nutrients'] - 0.012 * dt)
            if B['planted'] and B['moisture'] > 25 and B['growth'] < 100:
                B['growth'] = min(100, B['growth'] + 0.07 * (0.5 + B['nutrients'] / 100) * dt)
            if B['moisture'] < 20 and not B['dryWarned']:
                B['dryWarned'] = True
                self.log(f"{bid} {BEDS[bid]['crop']} is dry ({round(B['moisture'])}% moisture)", 'bad')

    def auto_water(self):
        auto = self.S['auto']
        if not auto['water']:
            return
        for bid, B in self.S['beds'].items():
            if B['moisture'] >= auto['threshold']:
                continue
            work = BEDS[bid]['work']
            if any(t['type'] == 'water' and t['work'] == work for t in self.S['tasks']):
                continue
            self.S['seq'] += 1
            tid = f"T-{self.S['seq']}"
            self.S['tasks'].append({'id': tid, 'type': 'water', 'pickup': 'PW', 'work': work, 'finish': 'PW', 'amount': auto['liters'],
                                    'assignee': 'auto', 'priority': 'high', 'status': 'queued', 'amr': None, 'createdAt': now_ms(),
                                    'startedAt': None, 'edits': 0, 'distance': 0, 'progress': 0, 'auto': True,
                                    'events': [{'t': now_ms(), 'msg': f"Created automatically: moisture {round(B['moisture'])}% < {auto['threshold']}%"}]})
            self.log(f"{tid} auto-created · water {bid} {BEDS[bid]['crop']} ({round(B['moisture'])}% moisture)", 'warn')
            self.changed()

    # ---------------- dispatcher ----------------
    def available(self, a):
        return (not a['paused'] and a['mission'] not in ('task', 'manual') and not a['loadKind'] and a['phase'] != 'work'
                and a['battery'] >= (30 if a['rest'] == 'charging' else 15))

    def queued(self):
        q = [t for t in self.S['tasks'] if t['status'] == 'queued']
        return sorted(q, key=lambda t: (PRANK[t['priority']], t['createdAt']))

    def dispatch(self):
        for t in self.queued():
            if any(o is not t and o['status'] != 'queued' and o['work'] == t['work'] for o in self.S['tasks']):
                continue  # one robot per bed
            cands = [a for a in self.amrs if self.available(a) and t['assignee'] in ('auto', a['id'])]
            if not cands:
                continue
            a = min(cands, key=lambda x: self.nd(x['cell'], t['pickup']))
            t['status'] = 'to_pickup'
            t['amr'] = a['id']
            t['startedAt'] = now_ms()
            t['events'].append({'t': now_ms(), 'msg': f"Assigned to {a['id']}"})
            a['taskId'] = t['id']
            self.send_to(a, t['pickup'], 'pickup', 'task')
            self.log(f"{t['id']} assigned to {a['id']} · {TYPES[t['type']]['label']} {self.bed_label(t['work'])}")
            self.changed()

    def step(self, real_dt):
        rem = real_dt * self.speed
        while rem > 0:
            dt = min(rem, 0.05)
            rem -= dt
            for a in self.amrs:
                self.tick_amr(a, dt)
            self.tick_beds(dt)
            self.dispatch_acc += dt
            if self.dispatch_acc > 0.5:
                self.dispatch_acc = 0
                self.dispatch()
            self.auto_acc += dt
            if self.auto_acc > 2:
                self.auto_acc = 0
                self.auto_water()

    # ---------------- operator commands ----------------
    def cancel_task(self, tid):
        t = next((x for x in self.S['tasks'] if x['id'] == tid), None)
        if not t:
            return {'ok': False, 'msg': f'{tid} not found'}
        a = self.amr_by_id(t['amr']) if t['amr'] else None
        self.finish_task(t, 'cancelled', 'Cancelled by operator')
        if a and a['taskId'] == tid:
            a['taskId'] = None
            a['loadKind'] = None
            a['mission'] = None
            if a['carrying']:
                self.log(f"{a['id']} still carries {a['carrying']['item']}; it will wait at the charger for the operator", 'warn')
            if a['phase'] == 'work':
                a['phase'] = 'drive'
                a['path'] = a['path'][-1:]
                a['goal'] = {'node': a['path'][0] if a['path'] else a['cell'], 'kind': 'idle'}
            else:
                self.stop_at(a)
        self.log(f"{tid} cancelled{' · ' + a['id'] + ' released' if a else ''}", 'bad')
        self.changed()
        return {'ok': True, 'msg': f'{tid} cancelled'}

    def cmd(self, m):
        m = m or {}
        op = m.get('op')
        a = self.amr_by_id(m.get('id')) if m.get('id') else None

        if op in ('task.create', 'task.update'):
            ttype = m.get('type')
            if ttype not in TYPES:
                return {'ok': False, 'msg': 'Choose a task type'}
            T = TYPES[ttype]
            try:
                amount = round(float(m.get('amount')), 1)
            except (TypeError, ValueError):
                amount = -1
            if not (T['min'] <= amount <= T['max']):
                return {'ok': False, 'msg': f"{T['label']} amount must be {T['min']}–{T['max']} {T['unit']}"}
            if m.get('pickup') not in PICKS:
                return {'ok': False, 'msg': 'Choose a pickup point'}
            if not bed_of_work(m.get('work')):
                return {'ok': False, 'msg': 'Choose a garden bed as the work point'}
            if m.get('finish') not in FINISHES:
                return {'ok': False, 'msg': 'Choose where the AMR goes after the work'}
            assignee = m.get('assignee') if m.get('assignee') in ('auto', 'AMR 01', 'AMR 02') else 'auto'
            priority = m.get('priority') if m.get('priority') in PRANK else 'normal'
            if amount == int(amount):
                amount = int(amount)

            if op == 'task.create':
                self.S['seq'] += 1
                tid = f"T-{self.S['seq']}"
                self.S['tasks'].append({'id': tid, 'type': ttype, 'pickup': m['pickup'], 'work': m['work'], 'finish': m['finish'],
                                        'amount': amount, 'assignee': assignee, 'priority': priority, 'status': 'queued', 'amr': None,
                                        'createdAt': now_ms(), 'startedAt': None, 'edits': 0, 'distance': 0, 'progress': 0,
                                        'events': [{'t': now_ms(), 'msg': 'Created'}]})
                self.log(f"{tid} created · {T['label']} {self.bed_label(m['work'])} · {amount} {T['unit']} · {'auto' if assignee == 'auto' else assignee}")
                self.changed()
                return {'ok': True, 'msg': f'{tid} added to queue', 'id': tid}

            t = next((x for x in self.S['tasks'] if x['id'] == m.get('taskId')), None)
            if not t:
                return {'ok': False, 'msg': 'Task no longer exists'}
            if t['status'] in ('working', 'returning'):
                return {'ok': False, 'msg': f"The AMR is {'working the bed' if t['status'] == 'working' else 'returning the tool'}; this task can't be edited now"}
            started = t['status'] != 'queued'
            collected = t['status'] in ('to_work', 'to_finish')
            worked = t['status'] == 'to_finish'
            nx = {'type': t['type'] if started else ttype, 'amount': t['amount'] if collected else amount,
                  'pickup': t['pickup'] if collected else m['pickup'], 'work': t['work'] if worked else m['work'],
                  'finish': m['finish'], 'assignee': t['assignee'] if started else assignee, 'priority': priority}
            ch = []
            if nx['type'] != t['type']:
                ch.append(f"type {TYPES[t['type']]['label']} → {TYPES[nx['type']]['label']}")
            if nx['amount'] != t['amount']:
                ch.append(f"amount {t['amount']} → {nx['amount']} {TYPES[nx['type']]['unit']}")
            if nx['pickup'] != t['pickup']:
                ch.append(f"pickup {name(t['pickup'])} → {name(nx['pickup'])}")
            if nx['work'] != t['work']:
                ch.append(f"work point {self.bed_label(t['work'])} → {self.bed_label(nx['work'])}")
            if nx['finish'] != t['finish']:
                ch.append(f"finish {name(t['finish'])} → {name(nx['finish'])}")
            if nx['assignee'] != t['assignee']:
                ch.append(f"assigned {t['assignee']} → {nx['assignee']}")
            if nx['priority'] != t['priority']:
                ch.append(f"priority {t['priority']} → {nx['priority']}")
            if not ch:
                return {'ok': True, 'msg': 'No changes to save'}
            pc, wc, fc = nx['pickup'] != t['pickup'], nx['work'] != t['work'], nx['finish'] != t['finish']
            t.update(nx)
            t['edits'] += 1
            t['events'].append({'t': now_ms(), 'msg': 'Edited: ' + ', '.join(ch)})
            r = self.amr_by_id(t['amr']) if t['amr'] else None
            if r and r['taskId'] == t['id']:
                if t['status'] == 'to_pickup' and pc:
                    self.retarget(r, t['pickup'], 'pickup')
                    self.log(f"{r['id']} re-routed to {name(t['pickup'])}", 'warn')
                if t['status'] == 'to_work' and wc:
                    self.retarget(r, t['work'], 'work')
                    self.log(f"{r['id']} re-routed to {self.bed_label(t['work'])}", 'warn')
                if t['status'] == 'to_finish' and fc:
                    self.retarget(r, t['finish'], 'finish')
                    self.log(f"{r['id']} re-routed to {name(t['finish'])}", 'warn')
            self.log(f"{t['id']} updated · {', '.join(ch)}")
            self.changed()
            return {'ok': True, 'msg': f"{t['id']} updated"}

        if op == 'task.cancel':
            return self.cancel_task(m.get('taskId'))
        if op == 'bed.quick':
            b = BEDS.get(m.get('bed'))
            if not b:
                return {'ok': False, 'msg': 'Unknown bed'}
            ttype = m.get('type') if m.get('type') in TYPES else 'water'
            T = TYPES[ttype]
            return self.cmd({'op': 'task.create', 'type': ttype, 'pickup': T['tool'], 'work': b['work'], 'finish': T['finish'],
                             'amount': T['def'], 'assignee': 'auto', 'priority': 'high'})
        if op == 'auto.set':
            auto = self.S['auto']
            auto['water'] = bool(m.get('water'))
            try:
                if m.get('threshold') is not None:
                    auto['threshold'] = max(5, min(80, int(float(m['threshold']))))
                if m.get('liters') is not None:
                    auto['liters'] = max(5, min(60, int(float(m['liters']))))
            except (TypeError, ValueError):
                pass
            self.log(f"Auto-watering {'on · below ' + str(auto['threshold']) + '% moisture, ' + str(auto['liters']) + ' L' if auto['water'] else 'off'}",
                     'ok' if auto['water'] else 'warn')
            self.changed()
            return {'ok': True}
        if op == 'amr.pause' and a:
            a['paused'] = not a['paused']
            self.log(f"{a['id']} {'paused' if a['paused'] else 'resumed'} by operator", 'warn' if a['paused'] else 'ok')
            return {'ok': True}
        if op == 'amr.cancel' and a:
            if a['mission'] == 'task' and a['taskId']:
                return self.cancel_task(a['taskId'])
            if not a['goal']:
                return {'ok': False, 'msg': f"{a['id']} has nothing to cancel"}
            a['mission'] = None
            self.stop_at(a)
            a['idleT'] = -20
            self.log(f"{a['id']} goal cancelled · stopping at next waypoint", 'warn')
            return {'ok': True}
        if op in ('amr.charge', 'amr.park') and a:
            if a['mission'] == 'task':
                return {'ok': False, 'msg': f"{a['id']} is running {a['taskId']}. Cancel it first."}
            return self.go_charge(a, 'sent to') if op == 'amr.charge' else self.go_park(a)
        if op == 'amr.goal' and a:
            node = m.get('node')
            if node not in N or N[node]['t'] == 'lane':
                return {'ok': False, 'msg': 'Pick a valid waypoint'}
            if a['mission'] == 'task':
                return {'ok': False, 'msg': f"{a['id']} is running {a['taskId']}. Cancel it first or use the other AMR."}
            if self.busy(a):
                return {'ok': False, 'msg': f"{a['id']} is busy; try again in a moment"}
            kind = 'charge' if N[node]['t'] == 'chg' else 'park' if N[node]['t'] == 'park' else 'manual'
            self.send_to(a, node, kind, 'manual' if kind == 'manual' else kind)
            self.log(f"{a['id']} goal → {name(node)}")
            return {'ok': True, 'msg': f"{a['id']} → {name(node)}"}
        if op == 'sim.speed':
            try:
                v = float(m.get('value'))
            except (TypeError, ValueError):
                v = 0
            if v not in (0.5, 1, 2, 4):
                return {'ok': False, 'msg': 'Speed must be 0.5, 1, 2 or 4'}
            self.speed = int(v) if v == int(v) else v
            return {'ok': True}
        if op == 'sim.reset':
            self.fresh()
            self.log('Demo data reset by operator', 'warn')
            self.changed()
            return {'ok': True, 'msg': 'Demo reset'}
        return {'ok': False, 'msg': 'Unknown command or AMR'}

    # ---------------- what viewers receive ----------------
    def snapshot(self):
        amrs = []
        for a in self.amrs:
            c = a['carrying']
            amrs.append({'id': a['id'], 'cls': a['cls'], 'x': round(a['x'], 1), 'y': round(a['y'], 1), 'heading': round(a['heading'], 3),
                         'v': round(a['v'], 2), 'path': a['path'], 'cell': a['cell'], 'phase': a['phase'], 'mission': a['mission'],
                         'taskId': a['taskId'], 'carrying': ({**c, 'left': round(c['left'], 1)} if c else None), 'loadKind': a['loadKind'],
                         'loadT': round(a['loadT'], 2), 'battery': round(a['battery'], 1), 'paused': a['paused'], 'hold': a['hold'],
                         'rest': a['rest'], 'goal': a['goal'], 'yielding': a['yielding'], 'odo': round(a['odo'], 1), 'workDone': round(a['workDone'], 3)})
        beds = {k: {'moisture': round(B['moisture'], 1), 'nutrients': round(B['nutrients'], 1), 'growth': round(B['growth'], 1),
                    'planted': B['planted'], 'lastWatered': B['lastWatered'], 'lastFertilized': B['lastFertilized'],
                    'lastSeeded': B['lastSeeded'], 'lastHarvested': B['lastHarvested']} for k, B in self.S['beds'].items()}
        return {'t': now_ms(), 'speed': self.speed, 'amrs': amrs, 'beds': beds}

    def data_state(self):
        return {'tasks': self.S['tasks'], 'history': self.S['history'][:300], 'store': self.S['store'], 'auto': self.S['auto'], 'seq': self.S['seq']}

    def feed(self):
        return self.S['feed'][:100]
