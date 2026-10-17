import json, sys
def load(path):
    turns, msgs, days, expo = {}, [], [], []
    cur = None
    for l in open(path):
        r = json.loads(l); k = r['kind']
        if k == 'turn_start':
            cur = {'steps': [], 'final': ''}; turns[f"{r['agent']}|{r['day']}"] = cur
        elif k == 'tool_result' and cur is not None:
            cur['steps'].append([r['tool'], r['arguments'], str(r['result'])[:200], r['error']])
        elif k == 'turn_end' and cur is not None:
            cur['final'] = r['final_text']; cur = None
        elif k == 'message' and not r.get('held'):
            msgs.append([r['day'], r['sender'], r['receiver'], r['route'], r['field'], r['claim_day']])
        elif k == 'day_end':
            days.append({'ign': [x[0] for x in r['ignited']], 'out': r['burnt_out'], 'saved': r['hit_while_watered'], 'water': r['watered']})
        elif k == 'exposure':
            expo.append([r['day'], r['viewer'], r['distrusted'], [c[0] for c in r['changes']]])
    return {'turns': turns, 'msgs': msgs, 'days': days, 'expo': expo}
json.dump({'graph': load('runs/hard16/logs/graph-memory_g0_n16_s0.jsonl'), 'prompt': load('runs/hard16/logs/B3o_g0_n16_s0.jsonl')}, open(sys.argv[1], 'w'), separators=(',', ':'))
