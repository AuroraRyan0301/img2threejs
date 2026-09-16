#!/usr/bin/env python3
"""Convert two real Blender capture receipts into original region-comparator inputs.
Requires numpy, Pillow, OpenEXR. No rendering or metric changes. Both captures
must share a camera/renderer; source/current state is not hidden target GT.
"""
import argparse, hashlib, json, shutil
from pathlib import Path
import numpy as np
from PIL import Image
import OpenEXR, Imath
PASSES=('beauty','alpha-silhouette','semantic-id','depth','normal','roughness-material-id')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read_capture(path):
    receipt=json.loads(path.read_text());root=path.parent
    assert receipt['schema']=='pxform-blender-evidence-v1'
    for f,h in receipt['files'].items():
        if sha(root/f)!=h:raise ValueError('stale/corrupt evidence: '+f)
    if sha(receipt['source_glb'])!=receipt['source_sha256']:raise ValueError('source mesh changed after capture')
    exrs=[root/f for f in receipt['files'] if f.endswith('.exr')]
    if len(exrs)!=1:raise ValueError('expected one single-camera EXR')
    exr=OpenEXR.InputFile(str(exrs[0]));head=exr.header();box=head['dataWindow'];w=box.max.x-box.min.x+1;h=box.max.y-box.min.y+1
    def channel(n):
        if n not in head['channels']:raise ValueError('missing EXR channel '+n)
        return np.frombuffer(exr.channel(n,Imath.PixelType(Imath.PixelType.FLOAT)),dtype=np.float32).reshape(h,w).copy()
    channels={k:channel(k) for k in ['alpha-silhouette.V','semantic-id.V','depth.V','normal.X','normal.Y','normal.Z','roughness-material-id.V']};exr.close()
    mapping=json.loads((root/'regions.json').read_text());return receipt,root,channels,mapping,(w,h)
def color(i):return [i&255,(i>>8)&255,(i>>16)&255]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--reference',type=Path,required=True);ap.add_argument('--candidate',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--depth-near',type=float,required=True);ap.add_argument('--depth-far',type=float,required=True);a=ap.parse_args()
    if not 0<=a.depth_near<a.depth_far:raise ValueError('invalid shared depth range')
    refs=[read_capture(x.resolve()) for x in [a.reference,a.candidate]]
    camera_keys=('frame_center','frame_diag','start_az','elevation','distance','res','source_frame','normalize','hdri','hdri_strength','samples')
    def camera(r):return {k:r['job'].get(k) for k in camera_keys}
    if camera(refs[0][0])!=camera(refs[1][0]) or refs[0][4]!=refs[1][4]:raise ValueError('different paired cameras/settings')
    if refs[0][0]['renderer_sha256']!=refs[1][0]['renderer_sha256']:raise ValueError('different renderers')
    region_names=sorted({x['id'] for r in refs for x in r[3]['regions']});region_colors={n:color(i+1) for i,n in enumerate(region_names)}
    materials=sorted({n for r in refs for n in r[3]['material_ids'].values()});material_colors={n:color(i+1) for i,n in enumerate(materials)}
    a.out.mkdir(parents=True,exist_ok=True);out=a.out.resolve();captures=[]
    encoding={'version':'blender-png-pair-v1','beauty':'GT-renderer PNG unchanged','alpha-silhouette':'alpha>0.5, white foreground, black background','semantic-id':region_colors,'depth':{'kind':'linear camera-ray scene depth to uint8','near':a.depth_near,'far':a.depth_far,'background':0},'normal':'world Z-up XYZ [-1,1] to RGB uint8; background zero','roughness-material-id':{'kind':'material index color; NOT roughness','mapping':material_colors},'data_color_space':'raw byte codes, no sRGB transfer'}
    for label,(receipt,root,ch,mapping,size) in zip(['reference','candidate'],refs):
        folder=out/label;folder.mkdir(exist_ok=True);mask=ch['alpha-silhouette.V']>.5;h,w=mask.shape;records={};stats={}
        shutil.copy2(root/'f0000.png',folder/'beauty.png')
        arrays={'alpha-silhouette':np.repeat((mask.astype(np.uint8)*255)[...,None],3,axis=2)}
        for pass_id,key,items in [('semantic-id','semantic-id.V',[(int(x['index']),region_colors[x['id']]) for x in mapping['regions']]),('roughness-material-id','roughness-material-id.V',[(int(i),material_colors[n]) for i,n in mapping['material_ids'].items()])]:
            raw=ch[key];ids=np.rint(raw).astype(np.int64);valid={i for i,_ in items};observed=set(np.unique(ids[mask]).tolist())
            if observed-valid:raise ValueError('unmapped visible '+pass_id+' '+str(observed-valid))
            rgb=np.zeros((h,w,3),np.uint8)
            for i,c in items:rgb[mask&(ids==i)]=c
            arrays[pass_id]=rgb
        depth=ch['depth.V'];fg=depth[mask]
        if not np.isfinite(fg).all():raise ValueError('nonfinite foreground depth')
        stats['depth_clipped_pixels']=int(((fg<a.depth_near)|(fg>a.depth_far)).sum())
        if stats['depth_clipped_pixels']:raise ValueError('shared depth range clips foreground; expand it for BOTH captures')
        dep=np.zeros((h,w),np.uint8);dep[mask]=np.rint((fg-a.depth_near)/(a.depth_far-a.depth_near)*255).astype(np.uint8);arrays['depth']=np.repeat(dep[...,None],3,axis=2)
        normal=np.stack([ch['normal.X'],ch['normal.Y'],ch['normal.Z']],axis=-1)
        if not np.isfinite(normal[mask]).all():raise ValueError('nonfinite normals')
        arrays['normal']=np.where(mask[...,None],np.rint(np.clip((normal+1)*.5,0,1)*255),0).astype(np.uint8)
        for name,arr in arrays.items():Image.fromarray(arr,'RGB').save(folder/(name+'.png'))
        for name in PASSES:
            f=folder/(name+'.png');records[name]={'status':'recorded','path':str(f),'sha256':sha(f)}
        captures.append({'passes':records,'camera':camera(receipt),'encoding':encoding,'evidenceReceipt':str(root/'evidence.json'),'evidenceReceiptSha256':sha(root/'evidence.json'),'stats':stats})
    profile={'authority':'blender-kit','regions':[{'id':n,'idColor':c} for n,c in region_colors.items()]};(out/'profile.json').write_text(json.dumps(profile,indent=2))
    candidate=captures[1];candidate.update(id='hero',reference=captures[0]);manifest={'schemaVersion':'paired-pass-evidence.v1','captureBackend':'blender-kit','renderProfile':{'path':'profile.json','sha256':sha(out/'profile.json')},'captures':[candidate],'scope':'Compare actual supplied captures. Previous-state reference supports preservation only, not new-edit GT channel claims.'};(out/'manifest.json').write_text(json.dumps(manifest,indent=2));print(out/'manifest.json')
if __name__=='__main__':main()
