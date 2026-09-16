"""Capture GT-renderer beauty plus six-pass evidence and gate-compatible geometry.
Run with Blender -b -P this.py -- --job job.json --regions regions.json.
regions.json: {"regions":[{"id":"barrel","index":1,"objects":["barrel_body"]}]}.
Object names must match imported mesh names; unmapped meshes fail closed.
Uses GT renderer in-process without changing its files or modeling the asset.
"""
import argparse, hashlib, importlib.util, json, sys
from pathlib import Path
import bpy

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--regions',required=True)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);job=json.loads(Path(a.job).read_text());regions=json.loads(Path(a.regions).read_text())['regions']
    assert job.get('normalize')=='none' and job.get('source_frame')=='y_up'
    assert job.get('material')=='file_embedded' and job.get('scene')=='mesh'
    assert job.get('frames',1)==1,'One named camera per job'
    out=Path(job['out_dir']).resolve();out.mkdir(parents=True,exist_ok=True)
    table={};ids=set()
    for r in regions:
        assert 0<int(r['index'])<=32767 and r['index'] not in ids
        ids.add(r['index'])
        for n in r['objects']:
            assert n not in table;table[n]=r
    renderer=Path('/gs/fs/tga-koike-shanda4/yurh/blender_kit/scripts/render.py')
    sys.path.insert(0,str(renderer.parent.parent))
    spec=importlib.util.spec_from_file_location('gt_renderer',renderer);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    original=mod.make_rgb_only_step
    def factory(args,scene_obj,material_fn,hdri):
        build,cfg=original(args,scene_obj,material_fn,hdri)
        def build_with_evidence(fi):
            build(fi);objects=sorted([o for o in bpy.context.scene.objects if o.type=='MESH'],key=lambda o:o.name)
            missing=[o.name for o in objects if o.name not in table]
            if missing:raise ValueError('Unmapped mesh objects: '+repr(missing))
            absent=set(table)-{o.name for o in objects}
            if absent:raise ValueError('Region map references absent objects: '+repr(sorted(absent)))
            materials=sorted({m for o in objects for m in o.data.materials if m},key=lambda m:m.name)
            for i,m in enumerate(materials,1):m.pass_index=i
            meshes=[];dg=bpy.context.evaluated_depsgraph_get()
            for o in objects:
                o.pass_index=int(table[o.name]['index']);ev=o.evaluated_get(dg);me=ev.to_mesh();me.calc_loop_triangles();verts=[]
                for v in me.vertices:
                    q=ev.matrix_world@v.co;verts.append([q.x,q.z,-q.y])
                meshes.append(dict(id=o.name,semantic_id=table[o.name]['id'],vertices=verts,indices=[list(t.vertices) for t in me.loop_triangles]))
                ev.to_mesh_clear()
            (out/'meshes.json').write_text(json.dumps({'coordinate_frame':'source_y_up_world','meshes':meshes}))
            (out/'regions.json').write_text(json.dumps({'regions':regions,'material_ids':{str(m.pass_index):m.name for m in materials}},indent=2))
            vl=bpy.context.view_layer
            for flag in ['use_pass_z','use_pass_normal','use_pass_object_index','use_pass_material_index']:setattr(vl,flag,True)
        def configure(path):
            cfg(path);sc=bpy.context.scene;sc.use_nodes=True;nt=sc.node_tree;nt.nodes.clear();rl=nt.nodes.new('CompositorNodeRLayers');comp=nt.nodes.new('CompositorNodeComposite');nt.links.new(rl.outputs['Image'],comp.inputs['Image'])
            f=nt.nodes.new('CompositorNodeOutputFile');f.base_path=str(out/'channels')+'/';f.format.file_format='OPEN_EXR_MULTILAYER';f.format.color_depth='32';f.format.exr_codec='ZIP';f.layer_slots.clear()
            for name,socket in [('beauty','Image'),('alpha-silhouette','Alpha'),('semantic-id','IndexOB'),('depth','Depth'),('normal','Normal'),('roughness-material-id','IndexMA')]:
                f.layer_slots.new(name);nt.links.new(rl.outputs[socket],f.inputs[name])
        return build_with_evidence,configure
    mod.make_rgb_only_step=factory
    ap=argparse.ArgumentParser();mod.add_args(ap);args=ap.parse_args([]);job['outputs']='rgb';mod.run_one_job(mod._merge(args,job))
    files=list(out.rglob('*.exr'));assert files and (out/'f0000.png').exists()
    receipt={'schema':'pxform-blender-evidence-v1','authority':'blender_kit','renderer':str(renderer),'renderer_sha256':sha(renderer),'source_glb':job['mesh'],'source_sha256':sha(job['mesh']),'job':job,'passes':['beauty','alpha-silhouette','semantic-id','depth','normal','roughness-material-id'],'last_pass_encoding':'material-index, NOT roughness','depth_encoding':'Blender Depth pass, raw scene units; background sentinel retained','normal_encoding':'Blender world-space normal (Z-up)','geometry_frame':'source_y_up_world','semantic_mapping':'agent-authored labels; numerical object IDs alone do not prove semantics','paired_GT_passes':False,'files':{str(f.relative_to(out)):sha(f) for f in [out/'f0000.png',out/'meshes.json',out/'regions.json']+files}}
    (out/'evidence.json').write_text(json.dumps(receipt,indent=2));print('Evidence saved:',out)
if __name__=='__main__':main()
