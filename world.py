"""Farm map and task definitions.

Edit this file to change the farm: move points (x, y), rename crops, add beds or task types.
The dashboard receives the same data through /world.js, so the map always matches.
"""
import json

PX = 40          # 40 map units = 1 metre
V_MAX = 22       # drive speed (0.55 m/s)
ACC = 22         # acceleration
LOAD_T = 4       # seconds to collect / return a tool

# ---- waypoints: t = pick (tool pickup), work (garden bed), store, park, chg (charger), tr (transit), lane (inside a bed) ----
N = {
    # tool shed pickup points
    'PW': {'x': 100, 'y': 160, 't': 'pick', 'n': 'water_tools'},
    'PS': {'x': 175, 'y': 160, 't': 'pick', 'n': 'seed_box'},
    'PF': {'x': 250, 'y': 160, 't': 'pick', 'n': 'fertilizer'},
    # barn
    'PC': {'x': 730, 'y': 160, 't': 'pick', 'n': 'harvest_crates'},
    'HS': {'x': 890, 'y': 160, 't': 'store', 'n': 'harvest_store'},
    # north track
    'A1': {'x': 100, 'y': 220, 't': 'tr', 'n': 'TR1'}, 'A2': {'x': 175, 'y': 220, 't': 'tr', 'n': 'TR2'},
    'A3': {'x': 250, 'y': 220, 't': 'tr', 'n': 'TR3'}, 'A4': {'x': 410, 'y': 220, 't': 'tr', 'n': 'TR4'},
    'A5': {'x': 570, 'y': 220, 't': 'tr', 'n': 'TR5'}, 'A6': {'x': 730, 'y': 220, 't': 'tr', 'n': 'TR6'},
    'A7': {'x': 890, 'y': 220, 't': 'tr', 'n': 'TR7'},
    # west track with parking + chargers
    'L1': {'x': 100, 'y': 305, 't': 'tr', 'n': 'TR8'}, 'L2': {'x': 100, 'y': 385, 't': 'tr', 'n': 'TR9'},
    'L3': {'x': 100, 'y': 465, 't': 'tr', 'n': 'TR10'}, 'L4': {'x': 100, 'y': 550, 't': 'tr', 'n': 'TR11'},
    'K1': {'x': 30, 'y': 305, 't': 'park', 'n': 'PARK_1'}, 'K2': {'x': 30, 'y': 465, 't': 'park', 'n': 'PARK_2'},
    'C1': {'x': 178, 'y': 385, 't': 'chg', 'n': 'CHG_1'}, 'C2': {'x': 178, 'y': 465, 't': 'chg', 'n': 'CHG_2'},
}
EDGES = [['PW', 'A1'], ['PS', 'A2'], ['PF', 'A3'], ['PC', 'A6'], ['HS', 'A7'],
         ['A1', 'A2'], ['A2', 'A3'], ['A3', 'A4'], ['A4', 'A5'], ['A5', 'A6'], ['A6', 'A7'],
         ['A1', 'L1'], ['L1', 'L2'], ['L2', 'L3'], ['L3', 'L4'], ['K1', 'L1'], ['K2', 'L3'], ['C1', 'L2'], ['C2', 'L3']]

# vertical tracks between the beds
XS = [250, 410, 570, 730, 890]
COL = ['A3', 'A4', 'A5', 'A6', 'A7']
for i, x in enumerate(XS):
    N[f'V{i}a'] = {'x': x, 'y': 305, 't': 'tr', 'n': f'TR{12 + i * 4}'}
    N[f'V{i}m'] = {'x': x, 'y': 385, 't': 'tr', 'n': f'TR{13 + i * 4}'}
    N[f'V{i}b'] = {'x': x, 'y': 465, 't': 'tr', 'n': f'TR{14 + i * 4}'}
    N[f'V{i}z'] = {'x': x, 'y': 550, 't': 'tr', 'n': f'TR{15 + i * 4}'}
    EDGES += [[COL[i], f'V{i}a'], [f'V{i}a', f'V{i}m'], [f'V{i}m', f'V{i}b'], [f'V{i}b', f'V{i}z']]
    if i > 0:
        EDGES += [[f'V{i-1}m', f'V{i}m'], [f'V{i-1}z', f'V{i}z']]
EDGES.append(['L4', 'V0z'])

# ---- garden beds: work point = track node at the bed's west end; the AMR drives the bed row (lane) ----
CROPS = ['Tomato', 'Chili', 'Brinjal', 'Okra', 'Beans', 'Cabbage', 'Carrot', 'Leeks']
BEDS = {}
for ri, (r, cy) in enumerate([('a', 305), ('b', 465)]):
    for c in range(4):
        i = ri * 4 + c + 1
        bid, x0, work = f'B{i}', XS[c], f'V{c}{r}'
        N[work]['t'] = 'work'
        N[work]['n'] = f'{bid}_{CROPS[i - 1].lower()}'
        N[bid + 'L1'] = {'x': x0 + 40, 'y': cy, 't': 'lane', 'n': bid + '_row_w'}
        N[bid + 'L2'] = {'x': x0 + 122, 'y': cy, 't': 'lane', 'n': bid + '_row_e'}
        BEDS[bid] = {'id': bid, 'crop': CROPS[i - 1], 'work': work, 'x': x0 + 18, 'y': cy - 50, 'w': 124, 'h': 100, 'cy': cy,
                     'lane': [bid + 'L1', bid + 'L2', bid + 'L1', work]}

# ---- task types ----
TYPES = {
    'water':     {'label': 'Watering',    'verb': 'Watering',    'tool': 'PW', 'finish': 'PW', 'item': 'Water tank',     'unit': 'L',      'def': 20,  'min': 5,  'max': 60,   'secPer': 1.5},
    'seed':      {'label': 'Seeding',     'verb': 'Seeding',     'tool': 'PS', 'finish': 'PS', 'item': 'Seed box',       'unit': 'g',      'def': 200, 'min': 50, 'max': 1000, 'secPer': 0.12},
    'fertilize': {'label': 'Fertilizing', 'verb': 'Fertilizing', 'tool': 'PF', 'finish': 'PF', 'item': 'Fertilizer',     'unit': 'kg',     'def': 5,   'min': 1,  'max': 20,   'secPer': 5},
    'harvest':   {'label': 'Harvesting',  'verb': 'Harvesting',  'tool': 'PC', 'finish': 'HS', 'item': 'Harvest crates', 'unit': 'crates', 'def': 2,   'min': 1,  'max': 6,    'secPer': 14},
}
PRANK = {'high': 0, 'normal': 1, 'low': 2}
PICKS = ['PW', 'PS', 'PF', 'PC']
FINISHES = ['PW', 'PS', 'PF', 'PC', 'HS']
WAIT = {'AMR 01': 'K1', 'AMR 02': 'K2'}


def name(node_id):
    return N[node_id]['n'] if node_id in N else node_id


def bed_of_work(node):
    for b in BEDS.values():
        if b['work'] == node:
            return b
    return None


def work_duration(task_type, amount):
    return max(15, min(120, amount * TYPES[task_type]['secPer']))


def client_js():
    """JavaScript for the dashboard: the same map data plus small helper functions."""
    data = {'PX': PX, 'V_MAX': V_MAX, 'ACC': ACC, 'LOAD_T': LOAD_T, 'N': N, 'EDGES': EDGES, 'BEDS': BEDS, 'CROPS': CROPS,
            'TYPES': TYPES, 'PRANK': PRANK, 'PICKS': PICKS, 'FINISHES': FINISHES, 'WAIT': WAIT, 'XS': XS}
    return ('(function(){var W=' + json.dumps(data) + ';'
            'W.name=function(id){return W.N[id]?W.N[id].n:id;};'
            'W.bedOfWork=function(node){return Object.values(W.BEDS).find(function(b){return b.work===node;});};'
            'W.workDuration=function(t,a){return Math.max(15,Math.min(120,a*W.TYPES[t].secPer));};'
            'window.WORLD=W;})();')
