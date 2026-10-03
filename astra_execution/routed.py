"""Decode authenticated parent/self-CPI relationships without guessing stack depth."""
from astra_dex import pumpswap
from astra_observer.spine import require

def decode_routed(inners,keys):
    out=[]
    for index,parent in enumerate(inners):
        pi=parent.get('programIdIndex');require(type(pi)==int and 0<=pi<len(keys),'invalid_inner_program')
        if keys[pi]!=pumpswap.PROGRAM:continue
        try:data=pumpswap.b58decode(parent['data'])
        except (ValueError,KeyError,TypeError):out.append({'status':'error','reason':'invalid_inner_data','parent_inner_index':index});continue
        if data.startswith(pumpswap.EVENT_TAG):continue
        depth=parent.get('stackHeight')
        if type(depth)!=int or depth<2:out.append({'status':'unresolved','reason':'parent_depth_missing','parent_inner_index':index});continue
        children=[];positions=[];invalid=False
        for j in range(index+1,len(inners)):
            child=inners[j];h=child.get('stackHeight')
            if type(h)!=int or h<2:invalid=True;break
            if h<=depth:break
            if h==depth+1:
                normalized=dict(child,stackHeight=2);children.append(normalized);positions.append(j)
        if invalid:out.append({'status':'unresolved','reason':'subtree_depth_missing','parent_inner_index':index});continue
        try:
            result=pumpswap.decode(parent,children,keys)
            if result['status']=='decoded':
                e=result['event'];e['inner_instruction_index']=positions[e['inner_instruction_index']];e['parent_inner_index']=index;e['call_depth']=depth
            result['parent_inner_index']=index;out.append(result)
        except (ValueError,TypeError,KeyError,IndexError):out.append({'status':'error','reason':'routed_protocol_evidence_invalid','parent_inner_index':index})
    return out
