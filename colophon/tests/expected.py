"""Independent Overview oracle, expressed from D1/D5/D6 and spec §5.2/5.9.

No application imports: the compiler supplies facts; this module computes
expected panel values directly from those facts in the requested viewer zone.
"""
from datetime import datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo


def known(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def overall(row, payload, archived=True):
    """All-session totals: own usage plus each reachable descendant once.

    Unlike Overview, this includes untimed units; cached reads and reasoning
    remain subsets rather than additions to the input+output token count.
    """
    units, seen, pending = [row], {row['id']}, list(row['children'])
    while pending:
        identifier = pending.pop(0)
        if identifier in seen or identifier not in payload['subagents']:
            continue
        seen.add(identifier)
        child = payload['subagents'][identifier]
        if not archived and child['archived']:
            continue
        units.append(child)
        pending.extend(child['children'])
    fields = ('input', 'cached_input', 'cache_write', 'output', 'reasoning', 'unpriced_tokens')
    result = {field: sum(item['own_usage'][field] for item in units) for field in fields}
    result['tokens'] = result['input'] + result['output']
    costs = [item['own_usage']['cost_usd'] for item in units]
    result['cost_usd'] = sum(costs) if all(known(value) for value in costs) else None
    result['subagents'] = len(units) - 1
    return result


def local(ms, zone='UTC'):
    return datetime.fromtimestamp(ms / 1000, ZoneInfo(zone))


def window(state, now, zone='UTC'):
    day = local(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    period = state.get('p', '90d')
    if period == 'all':
        return float('-inf'), now + 1
    if period == 'custom':
        first = datetime.fromisoformat(state['from']).replace(tzinfo=ZoneInfo(zone))
        last = datetime.fromisoformat(state['to']).replace(tzinfo=ZoneInfo(zone)) + timedelta(days=1)
        return first.timestamp() * 1000, last.timestamp() * 1000
    first = day.replace(day=1) if period == 'mtd' else day - timedelta(days=int(period[:-1]) - 1)
    return first.timestamp() * 1000, now + 1


def inside(ms, bounds):
    return known(ms) and bounds[0] <= ms < bounds[1]


def descendants(row, payload, state):
    result, seen, pending = [], {row['id']}, list(row['children'])
    while pending:
        identifier = pending.pop(0)
        if identifier in seen or identifier not in payload['subagents']:
            continue
        seen.add(identifier)
        child = payload['subagents'][identifier]
        if state.get('a', '1') == '0' and child['archived']:
            continue
        result.append(child)
        pending.extend(child['children'])
    return result


def buckets(row, bounds):
    return [b for b in row['buckets'] if known(b[0]) and inside(b[0] * 900_000, bounds)]


def own_match(row, state, bounds, zone):
    if state.get('a', '1') == '0' and row['archived']:
        return False
    span = known(row['start_ms']) and known(row['end_ms']) and row['start_ms'] <= row['end_ms'] and row['start_ms'] < bounds[1] and row['end_ms'] >= bounds[0]
    if not span and not buckets(row, bounds):
        return False
    turns = [t for t in row['turns'] if inside(t['start_ms'], bounds)]
    text = [row['title_full']] + [r['text'] for t in row['turns'] for r in t['requests']] + [r['text'] for r in row['session_voice']['requests']]
    return (all(state.get(k) is None or state[k] == row[k] for k in ('workspace', 'subfolder'))
        and (not state.get('ws') or state['ws'] == row['workspace'])
        and (not state.get('sub') or state['sub'] == row['subfolder'])
        and (not state.get('q') or any(state['q'].lower() in s.lower() for s in text))
        and (not state.get('model') or any(b[1] == state['model'] for b in buckets(row, bounds)))
        and (not state.get('st') or any(t['status'] == state['st'] for t in turns))
        and (not state.get('day') or any(local(t['start_ms'], zone).strftime('%Y-%m-%d') == state['day'] for t in turns))
        and (not state.get('how') or any(f"{local(t['start_ms'], zone).weekday()}-{local(t['start_ms'], zone).hour}" == state['how'] for t in turns)))


def selected(payload, state, now, zone='UTC', bounds=None):
    bounds = bounds or window(state, now, zone)
    return [s for s in payload['sessions'] if not (state.get('a', '1') == '0' and s['archived']) and any(own_match(row, state, bounds, zone) for row in [s] + descendants(s, payload, state))]


def intervals(row, bounds):
    result = []
    for turn in row['turns']:
        if turn['status'] not in ('completed', 'aborted', 'interrupted', 'running') or not all(known(turn[k]) for k in ('start_ms', 'end_ms', 'duration_ms')) or turn['duration_ms'] < 0:
            continue
        first, last = max(turn['start_ms'], bounds[0]), min(turn['end_ms'], bounds[1])
        if last > first:
            result.append((first, last))
    return result


def union(parts):
    total, edge = 0, float('-inf')
    for first, last in sorted(parts):
        total += max(0, last - max(first, edge))
        edge = max(edge, last)
    return total


def kpis(payload, state, now, zone='UTC', bounds=None):
    bounds = bounds or window(state, now, zone)
    rows = selected(payload, state, now, zone, bounds)
    children = {r['id']: r for s in rows for r in descendants(s, payload, state)}
    turns = [t for s in rows for t in s['turns'] if inside(t['start_ms'], bounds)]
    usage = [b for r in rows + list(children.values()) for b in buckets(r, bounds)]
    durations = [t['duration_ms'] for t in turns if t['status'] != 'abandoned' and known(t['duration_ms'])]
    return dict(sessions=len(rows), active_ms=union([p for s in rows for p in intervals(s, bounds)]),
        agent_ms=sum(union(intervals(c, bounds)) for c in children.values()), turns=len(turns),
        average_ms=sum(durations) / len(durations) if durations else None,
        input=sum(b[3] for b in usage), tokens=sum(b[3] + b[6] for b in usage),
        cached_share=sum(b[4] for b in usage) / sum(b[3] for b in usage) if sum(b[3] for b in usage) else None,
        cost=sum(b[8] for b in usage if known(b[8])), unpriced=any(b[8] is None for b in usage),
        aborted=sum(t['status'] == 'aborted' for t in turns), interrupted=sum(t['status'] == 'interrupted' for t in turns),
        abandoned=sum(t['status'] == 'abandoned' for t in turns))


def calendar(payload, state, now, zone='UTC'):
    bounds = window(state, now, zone)
    rows = selected(payload, state, now, zone)
    children = {r['id']: r for s in rows for r in descendants(s, payload, state)}
    first = bounds[0]
    if not isfinite(first):
        activity = [t['start_ms'] for r in rows + list(children.values()) for t in r['turns'] if inside(t['start_ms'], bounds)] + [b[0] * 900_000 for r in rows + list(children.values()) for b in buckets(r, bounds)]
        first = min(activity, default=now)
        day = local(first, zone).replace(hour=0, minute=0, second=0, microsecond=0)
        first = (day - timedelta(days=day.weekday())).timestamp() * 1000
    day = local(first, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    result = []
    while day.timestamp() * 1000 < bounds[1]:
        day_end = day + timedelta(days=1)
        clip = max(bounds[0], day.timestamp() * 1000), min(bounds[1], day_end.timestamp() * 1000)
        starts = [r['id'] for r in rows if any(inside(t['start_ms'], clip) for t in r['turns'])]
        usage = [b for r in rows + list(children.values()) for b in buckets(r, clip)]
        result.append(dict(day=day.strftime('%Y-%m-%d'), sessions=len(starts),
            active_ms=union([p for s in rows for p in intervals(s, clip)]),
            tokens=sum(b[3] + b[6] for b in usage), cost=sum(b[8] for b in usage if known(b[8])),
            unpriced=any(b[8] is None for b in usage)))
        day = day_end
    return result


def hour_weekday(payload, state, now, zone='UTC'):
    bounds, counts = window(state, now, zone), [[0] * 24 for _ in range(7)]
    for row in selected(payload, state, now, zone):
        for turn in row['turns']:
            if inside(turn['start_ms'], bounds):
                instant = local(turn['start_ms'], zone)
                counts[instant.weekday()][instant.hour] += 1
    return counts


def rollups(payload, state, now, zone='UTC'):
    bounds = window(state, now, zone)
    rows = selected(payload, state, now, zone)
    units = {r['id']: r for s in rows for r in [s] + descendants(s, payload, state)}
    workspaces, models = {}, {}
    for row in units.values():
        item = workspaces.setdefault(row['workspace'], dict(active_ms=0, tokens=0))
        if row in rows:
            item['active_ms'] += union(intervals(row, bounds))
        for bucket in buckets(row, bounds):
            item['tokens'] += bucket[3] + bucket[6]
            model = models.setdefault(bucket[1], dict(tokens=0, cost=0, unpriced=False))
            model['tokens'] += bucket[3] + bucket[6]
            model['cost'] += bucket[8] if known(bucket[8]) else 0
            model['unpriced'] |= bucket[8] is None
    # Workspace active time is a union across own sessions in that workspace.
    for key, item in workspaces.items():
        item['active_ms'] = union([p for s in rows if s['workspace'] == key for p in intervals(s, bounds)])
    return workspaces, models


def recent(payload, state, now, zone='UTC'):
    return [r['id'] for r in sorted(selected(payload, state, now, zone), key=lambda r: (not known(r['start_ms']), -(r['start_ms'] or 0), r['id']))[:5]]


def previous_window(state, now, zone='UTC'):
    first,last = window(state, now, zone)
    if state['p'] in ('all','custom'):
        return None
    if state['p'] == 'mtd':
        month = local(first,zone)
        prior = (month - timedelta(days=1)).replace(day=1)
        return prior.timestamp()*1000, min(first,prior.timestamp()*1000 + last-first)
    return first-(last-first),first


def workspaces(payload,state,now,zone='UTC'):
    return rollups(payload,state,now,zone)[0]


def models(payload,state,now,zone='UTC'):
    return rollups(payload,state,now,zone)[1]


def notable(payload,state,now,zone='UTC'):
    days = calendar(payload,state,now,zone)
    nonempty = [d for d in days if d['sessions']]
    active = [d for d in days if d['active_ms']]
    rows = selected(payload,state,now,zone)
    fanouts = [(s['id'],len(descendants(s,payload,state))) for s in rows]
    best_fanout = max(fanouts,key=lambda item:item[1],default=(None,0))
    runs,run = [],[]
    for day in days:
        if day['sessions']:
            run.append(day['day'])
        else:
            if run: runs.append(run)
            run=[]
    if run: runs.append(run)
    longest=max(runs,key=len,default=[])
    return dict(busiest=max(nonempty,key=lambda day:day['sessions'],default=None),
        active=max(active,key=lambda day:day['active_ms'],default=None),
        fanout=dict(id=best_fanout[0],count=best_fanout[1]) if best_fanout[1] else None,
        streak=dict(from_=longest[0],to=longest[-1],count=len(longest)) if longest else None)
