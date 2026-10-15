#!/usr/bin/env python3
"""Read-only, schema-aware comparison of X++ outputs; excludes only PDBs.
CIL uses the supplied Cecil comparator. .md payloads use Microsoft's original
reader/writer and retain each raw Declaration while testing only CRLF->LF there.
No input files are modified; output must be outside both input directories.
"""
import argparse, collections, hashlib, json, os, struct, subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

def digest(b): return hashlib.sha256(b).hexdigest()
def read_json_command(cmd, env=None):
 p=subprocess.run(cmd,env=env,capture_output=True,text=True,check=True,timeout=90)
 return json.loads(p.stdout)

def file_table(path):
 """Parse PE/CLI metadata File table, including netmodules, without loading code."""
 b=path.read_bytes()
 def u(at,n):
  if at<0 or at+n>len(b):raise ValueError('truncated PE')
  return int.from_bytes(b[at:at+n],'little')
 pe=u(0x3c,4);assert b[pe:pe+4]==b'PE\0\0'
 ns=u(pe+6,2);opt=pe+24;magic=u(opt,2);assert magic in (0x10b,0x20b)
 dd=opt+(96 if magic==0x10b else 112);section=opt+u(pe+20,2)
 def rva(v):
  for i in range(ns):
   at=section+40*i;size=max(u(at+8,4),u(at+16,4));start=u(at+12,4)
   if start<=v<start+size:return u(at+20,4)+v-start
  raise ValueError('RVA not in a section')
 cli=rva(u(dd+14*8,4));md=rva(u(cli+8,4));assert b[md:md+4]==b'BSJB'
 pos=(md+16+u(md+12,4)+3)&~3;count=u(pos+2,2);pos+=4;streams={}
 for _ in range(count):
  off,size=u(pos,4),u(pos+4,4);end=b.index(0,pos+8);name=b[pos+8:end].decode('ascii');streams[name]=(md+off,size);pos=(end+4)&~3
 t=streams.get('#~',streams.get('#-'))[0];hs=u(t+6,1);valid=u(t+8,8);pos=t+24;rows={}
 for k in range(64):
  if valid>>k&1:rows[k]=u(pos,4);pos+=4
 s=4 if hs&1 else 2;g=4 if hs&2 else 2;blob=4 if hs&4 else 2
 def idx(k):return 4 if rows.get(k,0)>=65536 else 2
 def coded(bits,*tables):return 4 if max([rows.get(k,0) for k in tables])>=(1<<(16-bits)) else 2
 td=coded(2,2,1,27);res=coded(2,0,26,35,1);mr=coded(3,2,1,26,6,27)
 hc=coded(2,4,8,23);hca=coded(5,6,4,1,2,8,9,10,0,14,23,20,17,26,27,32,35,38,39,40,42,44,43)
 cat=coded(3,6,10);hfm=coded(1,4,8);hds=coded(2,2,6,32);hsem=coded(1,20,23);mdr=coded(1,6,10);mf=coded(1,4,6)
 sizes=[2+s+3*g,res+2*s,4+2*s+td+idx(4)+idx(6),idx(4),2+s+blob,idx(6),8+s+blob+idx(8),idx(8),4+s,idx(2)+td,mr+s+blob,2+hc+blob,hca+cat+blob,hfm+blob,2+hds+blob,6+idx(2),4+idx(4),blob,idx(2)+idx(20),idx(20),2+s+td,idx(2)+idx(23),idx(23),2+s+blob,2+idx(6)+hsem,idx(2)+2*mdr,s,blob,2+mf+s+idx(26),4+idx(4),8,4,16+blob+2*s,4,12,12+2*blob+2*s,4+idx(35),12+idx(35),4+s+blob]
 offsets={}
 for k in range(39):offsets[k]=pos;pos+=rows.get(k,0)*sizes[k]
 def string(i):
  st,sz=streams['#Strings'];assert i<sz;e=b.index(0,st+i,st+sz);return b[st+i:e].decode('utf8')
 def bl(i):
  st,sz=streams['#Blob'];assert i<sz;at=st+i;first=u(at,1)
  if first<128:n=first;at+=1
  elif first<192:n=((first&63)<<8)|u(at+1,1);at+=2
  elif first<224:n=((first&31)<<24)|(u(at+1,1)<<16)|(u(at+2,1)<<8)|u(at+3,1);at+=4
  else:raise ValueError('invalid compressed blob length')
  assert at+n<=st+sz;return b[at:at+n]
 algorithms={0x8003:'md5',0x8004:'sha1',0x800c:'sha256',0x800d:'sha384',0x800e:'sha512'}
 algorithm=algorithms[u(offsets[32],4)];out=[]
 for i in range(rows.get(38,0)):
  at=offsets[38]+i*sizes[38];flags=u(at,4);name=string(u(at+4,s));h=bl(u(at+4+s,blob)).hex()
  if Path(name).name!=name or '\\' in name:raise ValueError('linked file not a local basename')
  target=path.parent/name;actual=hashlib.new(algorithm,target.read_bytes()).hexdigest()
  out.append(dict(file=name,flags=flags,algorithm=algorithm,storedHash=h,actualHash=actual,valid=h==actual))
 return out

def runtime(path):
 text=path.read_bytes().decode('utf-8-sig');lines=text.splitlines();kind=path.name.split('.')[-2]
 if kind in ('ClassExtends','EdtExtends','TableExtends','ODataExtensionsExtends'):
  pairs={}
  for line in lines:
   if not line.strip():continue
   p=line.split('\t')
   if len(p)!=2 or p[0].casefold() in pairs:raise ValueError('invalid/duplicate extends record')
   pairs[p[0].casefold()]=p # preserve spelling as a fact
  return dict(kind='extends-map',entries=sorted(pairs.values()))
 if kind=='ODataExtends':
  if any(lines):raise ValueError('nonempty OData delimiter schema not implemented: fail closed')
  return dict(kind='odata-empty-map',entries=[])
 if kind=='DeleteActions':
  assert lines and lines[0]=='VERSION=1; HeaderTable   LineTable1  LineRelation1 LineDeleteAction1   LineTable2  LineRelation2 LineDeleteAction2   ...'
  entries={}
  for line in lines[1:]:
   p=line.split('\t');assert len(p)>=2 and p[-1]=='' and (len(p)-2)%3==0
   if p[0] in entries:raise ValueError('duplicate delete-action key')
   entries[p[0]]=[p[i:i+3] for i in range(1,len(p)-1,3)]
  return dict(kind='delete-action-map',entries=entries)
 if kind=='TableMappings':
  assert lines and lines[0]=='VERSION=1; | Map MapField1  MapField2 ...  \\n - Table   TableField1   TableField2'
  result={};fields=None;name=None
  for line in lines[1:]:
   p=line.split('\t');assert len(p)>=2
   if p[0]=='|':name=p[1];fields=p[2:];assert name not in result;result[name]={}
   elif p[0]=='-':
    assert fields is not None and len(p)-2==len(fields) and p[1] not in result[name]
    result[name][p[1]]=dict(zip(fields,p[2:]));assert len(result[name][p[1]])==len(fields)
   else:raise ValueError('invalid table-map record')
  return dict(kind='table-map',entries=result)
 raise ValueError('unrecognized runtime schema '+kind)

def xml(path):
 raw=path.read_bytes();assert b'<!DOCTYPE' not in raw
 root=ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
 assert root.tag in ('ExtensionClasses','ChainOfCommand','EventHandlersSubscriptions')
 def node(e):
  # These generated resource schemas use whitespace for element indentation;
  # retain nonempty text, ordered children and every attribute exactly.
  assert isinstance(e.tag,str), 'XML comment/PI unsupported; classify explicitly'
  assert not e.tail or not e.tail.strip()
  text=e.text if e.text and e.text.strip() else None
  return dict(tag=e.tag,attributes=dict(sorted(e.attrib.items())),text=text,children=[node(c) for c in e])
 return node(root)

def md_semantic(e,canonical):
 keys=('key','modelId','lowerModelIds','kind')
 return [dict({k:v[k] for k in keys},payload=v.get('declarationLineEndingsCanonicalPayloadSha256',v['payloadSha256']) if canonical else v['payloadSha256']) for v in e['entries']]

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('windows_bin',type=Path);ap.add_argument('mac_bin',type=Path);ap.add_argument('report_dir',type=Path)
 ap.add_argument('--original-package',type=Path,required=True,help='Original compiler package directory containing the unchanged metadata reader/writer DLLs');ap.add_argument('--mono',default='mono')
 ap.add_argument('--canonicalizer',type=Path,default=Path(__file__).with_name('CanonicalCil.exe'));ap.add_argument('--metadata-inspector',type=Path,default=Path(__file__).with_name('AuxInspect.exe'));args=ap.parse_args()
 roots={'windows':args.windows_bin.resolve(),'mac':args.mac_bin.resolve()};out=args.report_dir.resolve()
 assert all(p.is_dir() for p in roots.values()) and all(out!=p and p not in out.parents for p in roots.values());out.mkdir(parents=True,exist_ok=True)
 files={k:{str(p.relative_to(root)):p for p in root.rglob('*') if p.is_file()} for k,root in roots.items()};metadata={}
 for side in roots:
  paths=sorted(p for p in files[side].values() if p.suffix.lower()=='.md');env=dict(os.environ,MONO_PATH=str(args.original_package))
  p=subprocess.run([args.mono,str(args.metadata_inspector)]+list(map(str,paths)),env=env,capture_output=True,text=True,check=True,timeout=90)
  entries=[json.loads(x) for x in p.stdout.splitlines()];metadata[side]={Path(e['path']).name:e for e in entries}
  (out/(side+'-metadata.json')).write_text(json.dumps(entries,indent=2)+'\n')
 report={'provenance':{'canonicalizer':str(args.canonicalizer),'canonicalizerSha256':digest(args.canonicalizer.read_bytes()),'metadataInspector':str(args.metadata_inspector),'metadataInspectorSha256':digest(args.metadata_inspector.read_bytes()),'metadataStorageSha256':digest((args.original_package/'Microsoft.Dynamics.AX.Metadata.Storage.dll').read_bytes()),'metadataCoreSha256':digest((args.original_package/'Microsoft.Dynamics.AX.Metadata.Core.dll').read_bytes()),'metadataModelSha256':digest((args.original_package/'Microsoft.Dynamics.AX.Metadata.dll').read_bytes())},'inputs':{s:str(p) for s,p in roots.items()},'scope':'All generated files except PDB; declarations/IL canonical comparison; native PE identities and physical row offsets retained in raw hashes. Declaration line-ending differences classified separately, not silently erased.','files':[],'linkedFiles':{}}
 for side in roots:
  report['linkedFiles'][side]={n:file_table(p) for n,p in files[side].items() if p.suffix.lower()=='.dll'}
 for name in sorted(set(files['windows'])|set(files['mac'])):
  row={'path':name};paths=[files[s].get(name) for s in roots]
  if Path(name).suffix.lower()=='.pdb':row['status']='excluded-pdb';report['files'].append(row);continue
  if any(p is None for p in paths):row['status']='missing-file';report['files'].append(row);continue
  a,b=paths;row['sha256']={s:digest(p.read_bytes()) for s,p in zip(roots,paths)};row['byteEqual']=a.read_bytes()==b.read_bytes();ext=a.suffix.lower()
  if ext=='.md':
   x,y=[metadata[s][name] for s in roots]
   exact=md_semantic(x,False)==md_semantic(y,False);canonical=md_semantic(x,True)==md_semantic(y,True)
   row.update(status='identical' if row['byteEqual'] else 'archive-order-only' if exact else 'declaration-line-endings-and-archive-layout-only' if canonical else 'metadata-difference',entryCount=len(x['entries']))
   row['declarationDifferences']=[{'key':u['key'],'windows':u.get('declaration'),'mac':v.get('declaration')} for u,v in zip(x['entries'],y['entries']) if u.get('declaration')!=v.get('declaration')]
  elif ext in ('.runtime','.xml'):
   parse=runtime if ext=='.runtime' else xml;x,y=map(parse,paths);row['status']='identical' if row['byteEqual'] else 'formatting-or-map-order-only' if x==y else 'resource-difference';row['parsedWindows']=x;row['parsedMac']=y
  elif ext in ('.dll','.netmodule'):
   values=[]
   for side,p in zip(roots,paths):
    val=read_json_command([args.mono,str(args.canonicalizer),str(p)]);(out/(side+'-'+name+'.canonical.json')).write_text(json.dumps(val,sort_keys=True,indent=2)+'\n');values.append(val)
   x,y=values;exact=x==y
   if not exact:
    # Stored link hashes are derived from independently validated exact files.
    # Resource name/type/attributes/file remain in the comparison.
    for v in values:
     for r in v['resources']:
      if 'file' in r and 'hash' in r:r['hash']='verified-in-linkedFiles'
   row['status']='canonical-cil-equal' if exact else 'canonical-cil-equal-except-verified-link-hashes' if x==y else 'cil-difference'
  else:row['status']='identical' if row['byteEqual'] else 'unclassified-difference'
  report['files'].append(row)
 report['counts']=dict(collections.Counter(r['status'] for r in report['files']));report['allLinkedFileHashesValid']=all(e['valid'] for side in report['linkedFiles'].values() for entries in side.values() for e in entries)
 failures={'missing-file','metadata-difference','resource-difference','cil-difference','unclassified-difference'}
 report['result']='all-differences-classified' if report['allLinkedFileHashesValid'] and not any(r['status'] in failures for r in report['files']) else 'unresolved-differences'
 (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ('result','counts','allLinkedFileHashesValid')}));return report['result']!='all-differences-classified'
if __name__=='__main__':raise SystemExit(main())
