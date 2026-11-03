"""Conservative grouping of categorical tiles with bounded boundary movement.

No resampling is returned: groups name one original representative. Inputs are
not modified. Exact hierarchical row/column colour-order signatures and exact
4-connected component counts must match. Every colour sample must find the
same colour within tolerance pixels in the other tile, checked in both native
grids after centre-nearest resizing. Corresponding ordered transitions and
hierarchical block boundaries must also stay within the native-pixel bound;
nearby repeated separators cannot substitute for each other. This is a discrete sample guarantee; it
does not establish geometric equivalence below the input pixel resolution.
"""
from numbers import Integral
import numpy as np


def _words(array):
    words=[]
    for row in array:
        changes=np.r_[True,row[1:]!=row[:-1]]
        word=tuple(int(x) for x in row[changes])
        if not words or words[-1]!=word:
            words.append(word)
    return tuple(words)


def _component_counts(array):
    # Run-based union-find: far fewer nodes than pixels for window facades.
    parent=[];colors=[];previous=[]
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(a,b):
        a=find(a);b=find(b)
        if a!=b:parent[b]=a
    for row in array:
        starts=np.flatnonzero(np.r_[True,row[1:]!=row[:-1]])
        ends=np.r_[starts[1:],len(row)]
        current=[]
        for left,right in zip(starts,ends):
            node=len(parent);parent.append(node);colors.append(int(row[left]))
            current.append((int(left),int(right),int(row[left]),node))
        j=0
        for left,right,color,node in current:
            while j<len(previous) and previous[j][1]<=left:j+=1
            k=j
            while k<len(previous) and previous[k][0]<right:
                pl,pr,pc,pn=previous[k]
                if pc==color:union(node,pn)
                k+=1
        previous=current
    counts={}
    for i,color in enumerate(colors):
        if find(i)==i:counts[color]=counts.get(color,0)+1
    return tuple(sorted(counts.items()))


def _signature(array):
    return (_words(array),_words(array.T),_component_counts(array))


def _axis_profile(array):
    """Hierarchical RLE blocks with each row's ordered transition positions."""
    blocks=[]
    for y,row in enumerate(array):
        transitions=np.flatnonzero(row[1:]!=row[:-1])+1
        word=tuple(int(x) for x in row[np.r_[0,transitions]])
        if not blocks or blocks[-1][0]!=word:
            blocks.append([word,y,y+1,[transitions]])
        else:
            blocks[-1][2]=y+1;blocks[-1][3].append(transitions)
    return blocks


def _ordered_axis_match(a,b,shape_a,shape_b,tolerance):
    """Match kth boundaries, in both native grids; no nearest-line substitution."""
    ha,wa=shape_a;hb,wb=shape_b
    if len(a)!=len(b):return False
    epsilon=1e-8
    for ba,bb in zip(a,b):
        word_a,start_a,end_a,rows_a=ba
        word_b,start_b,end_b,rows_b=bb
        if word_a!=word_b:return False
        for ya,yb in [(start_a,start_b),(end_a,end_b)]:
            if abs(ya/ha-yb/hb)*max(ha,hb)>tolerance+epsilon:return False
        # Use normalized position *inside the corresponding RLE block*.
        # Check both mappings because a shorter block may skip a row on one pass.
        for source,target,ws,wt in [(rows_a,rows_b,wa,wb),(rows_b,rows_a,wb,wa)]:
            for j,positions in enumerate(source):
                k=min(len(target)-1,int((j+.5)*len(target)/len(source)))
                other=target[k]
                if len(positions)!=len(other):return False
                if np.any(np.abs(positions/ws-other/wt)*max(ws,wt)>tolerance+epsilon):return False
    return True


def _resize_nearest(array,shape):
    h,w=shape;sh,sw=array.shape
    if shape==array.shape:return array
    yy=np.minimum(sh-1,((np.arange(h)+.5)*sh/h).astype(int))
    xx=np.minimum(sw-1,((np.arange(w)+.5)*sw/w).astype(int))
    return array[np.ix_(yy,xx)]


def _within_native(reference,other,tolerance):
    other=_resize_nearest(other,reference.shape)
    found=reference==other
    if found.all():return True
    h,w=reference.shape
    for dy in range(-tolerance,tolerance+1):
        for dx in range(-tolerance,tolerance+1):
            if not dx and not dy:continue
            y0=max(0,-dy);y1=min(h,h-dy);x0=max(0,-dx);x1=min(w,w-dx)
            if y0>=y1 or x0>=x1:continue
            found[y0:y1,x0:x1]|=reference[y0:y1,x0:x1]==other[y0+dy:y1+dy,x0+dx:x1+dx]
            if found.all():return True
    return False


def group_tiles(tiles,tolerance=1):
    """Return [{'representative': index, 'members': [indices]}], largest first.

    A member is compared directly with its final representative, never merely
    with another member; grouping cannot accumulate a chain of boundary shifts.
    Native-pixel tolerance uses the Chebyshev metric (including diagonals).
    """
    if not isinstance(tolerance,Integral) or isinstance(tolerance,bool) or tolerance<0:
        raise ValueError('tolerance must be a nonnegative integer')
    tiles=list(tiles)
    for a in tiles:
        if not isinstance(a,np.ndarray) or a.ndim!=2 or not a.size or a.dtype!=np.uint8:
            raise ValueError('tiles must be nonempty 2D numpy uint8 arrays')
    order=sorted(range(len(tiles)),key=lambda i:(-tiles[i].size,-max(tiles[i].shape),i))
    groups=[];buckets={};profiles={}
    for i in order:
        tile=tiles[i];profiles[i]=(_axis_profile(tile),_axis_profile(tile.T))
        signature=(tuple(b[0] for b in profiles[i][0]),tuple(b[0] for b in profiles[i][1]),_component_counts(tile));matched=False
        for gid in buckets.get(signature,[]):
            ri=groups[gid]['representative'];representative=tiles[ri]
            ordered=(_ordered_axis_match(profiles[i][0],profiles[ri][0],tile.shape,representative.shape,tolerance)
                     and _ordered_axis_match(profiles[i][1],profiles[ri][1],tile.T.shape,representative.T.shape,tolerance))
            if ordered and _within_native(tile,representative,tolerance) and _within_native(representative,tile,tolerance):
                groups[gid]['members'].append(i);matched=True;break
        if not matched:
            buckets.setdefault(signature,[]).append(len(groups))
            groups.append({'representative':i,'members':[i]})
    return groups
