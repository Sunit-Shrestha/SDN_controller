import heapq
links = {
    ('s1x2', 1): {'dst': ('s1x3', 1), 'cost': 1},
    ('s1x3', 1): {'dst': ('s1x2', 1), 'cost': 1},
    
    ('s1x2', 2): {'dst': ('s2x2', 1), 'cost': 2},
    ('s2x2', 1): {'dst': ('s1x2', 2), 'cost': 2},
    
    ('s2x2', 2): {'dst': ('s2x3', 1), 'cost': 1},
    ('s2x3', 1): {'dst': ('s2x2', 2), 'cost': 1},
    
    ('s1x3', 2): {'dst': ('s2x3', 2), 'cost': 1},
    ('s2x3', 2): {'dst': ('s1x3', 2), 'cost': 1},
}

def dijkstra(src_dpid, dst_dpid):
    queue = []
    heapq.heappush(queue, (0, src_dpid, []))
    min_cost = {src_dpid: 0}
    
    while queue:
        current_cost, current_dpid, path = heapq.heappop(queue)
        
        if current_dpid == dst_dpid:
            return path, current_cost
            
        if current_cost > min_cost.get(current_dpid, float('inf')):
            continue
            
        for (s_dpid, s_port), link_info in links.items():
            if s_dpid != current_dpid:
                continue
                
            d_dpid, _d_port = link_info['dst']
            link_cost = int(link_info.get('cost', 1))
            new_cost = current_cost + link_cost
            
            if new_cost < min_cost.get(d_dpid, float('inf')):
                min_cost[d_dpid] = new_cost
                new_path = path + [(current_dpid, s_port)]
                heapq.heappush(queue, (new_cost, d_dpid, new_path))
                
    return None, float('inf')

print(dijkstra('s1x2', 's2x3'))
