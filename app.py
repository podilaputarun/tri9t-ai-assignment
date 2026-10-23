"""Small, explicit MVP for versioned PDF manuals and generated test ideas."""
import hashlib, json, os, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fitz
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, String, Text, Integer, ForeignKey, UniqueConstraint, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, relationship

BASE = Path(__file__).resolve().parent
DB_PATH = os.getenv('DATABASE_URL', f'sqlite:///{BASE / "tri9t.db"}')
engine = create_engine(DB_PATH, connect_args={"check_same_thread": False} if DB_PATH.startswith('sqlite') else {})
Session = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase): pass
class ManualVersion(Base):
    __tablename__ = 'versions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String, unique=True, index=True)
    filename: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=lambda: datetime.now(timezone.utc).isoformat())
class Node(Base):
    __tablename__ = 'nodes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('versions.id'), index=True)
    logical_key: Mapped[str] = mapped_column(String, index=True)
    heading: Mapped[str] = mapped_column(String, default='')
    section_number: Mapped[str] = mapped_column(String, default='')
    parent_key: Mapped[str] = mapped_column(String, default='')
    body: Mapped[str] = mapped_column(Text, default='')
    content_hash: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String, default='section')
    __table_args__ = (UniqueConstraint('version_id', 'logical_key', name='uq_version_logical'),)
class Selection(Base):
    __tablename__ = 'selections'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    version_id: Mapped[int] = mapped_column(ForeignKey('versions.id'))
    node_ids_json: Mapped[str] = mapped_column(Text)
    source_snapshot: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=lambda: datetime.now(timezone.utc).isoformat())
class GeneratedTests(Base):
    __tablename__ = 'generated_tests'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    selection_id: Mapped[int] = mapped_column(ForeignKey('selections.id'), index=True)
    source_hash: Mapped[str] = mapped_column(String)
    output_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=lambda: datetime.now(timezone.utc).isoformat())
Base.metadata.create_all(engine)

app = FastAPI(title='Tri9T Manual Versioning API', version='0.1.0', description='MVP: extract, compare, select, generate and assess staleness.')

# Supports numbered headings and common PDF text extraction quirks. Body text is retained verbatim per section.
HEADING_RE = re.compile(r'^\s*(\d+(?:\.\d+)*)\.?\s+(.{2,100}?)\s*$')
def digest(text: str) -> str:
    normalized = re.sub(r'\s+', ' ', text).strip()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
def clean(text: str) -> str:
    return re.sub(r'[ \t]+', ' ', text).strip()
def extract_sections(pdf_path: str):
    doc = fitz.open(pdf_path)
    lines = []
    for page in doc:
        lines.extend(page.get_text('text').splitlines())
    sections=[]; current=None
    for raw in lines:
        line=clean(raw)
        if not line or line.startswith('<PARSED TEXT FOR PAGE:'):
            continue
        match=HEADING_RE.match(line)
        # Avoid interpreting decimal/table data as headings; require a plausible heading title.
        is_heading=bool(match and len(match.group(2).split()) <= 12 and not re.match(r'^(0|\d{1,3})\s*(mmHg|bpm|%)?$', match.group(2), re.I) and not ('.' not in match.group(1) and re.match(r'^(Normal|Elevated|Hypertension|Hypertensive Crisis)\b', match.group(2), re.I)))
        if is_heading:
            if current:
                current['body']=clean(' '.join(current['body']))
                current['content_hash']=digest(current['body'])
                sections.append(current)
            number,title=match.group(1),match.group(2).strip().rstrip('.')
            parent='.'.join(number.split('.')[:-1])
            key=f'{number}:{re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")}'
            current={'logical_key':key,'section_number':number,'heading':title,'parent_key':parent,'body':[],'kind':'section'}
        elif current:
            current['body'].append(line)
        else:
            # Document title and any pre-heading text are preserved as an intro node.
            if line and not sections:
                if not current: current={'logical_key':'document:introduction','section_number':'','heading':'Document introduction','parent_key':'','body':[],'kind':'document'}
                current['body'].append(line)
    if current:
        current['body']=clean(' '.join(current['body']))
        current['content_hash']=digest(current['body'])
        sections.append(current)
    # merge duplicate heading keys conservatively rather than dropping repeated content
    merged=[]; seen={}
    for sec in sections:
        key=sec['logical_key']
        if key in seen:
            existing=merged[seen[key]]
            existing['body']=clean(existing['body']+' '+sec['body'])
            existing['content_hash']=digest(existing['body'])
        else:
            seen[key]=len(merged); merged.append(sec)
    return merged

def import_pdf(path: str, label: str):
    with Session() as db:
        old=db.scalar(select(ManualVersion).where(ManualVersion.label==label))
        if old:
            return old.id
        version=ManualVersion(label=label, filename=Path(path).name); db.add(version); db.flush()
        for sec in extract_sections(path):
            db.add(Node(version_id=version.id, logical_key=sec['logical_key'], heading=sec['heading'], section_number=sec['section_number'], parent_key=sec['parent_key'], body=sec['body'], content_hash=sec['content_hash'], kind=sec['kind']))
        db.commit(); return version.id

class ImportRequest(BaseModel):
    pdf_path: str
    label: str = Field(min_length=1, max_length=50)
class SelectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    version: str
    node_ids: list[int] = Field(min_length=1)
class GenerateRequest(BaseModel):
    force: bool = False

def version_by_label(db, label):
    v=db.scalar(select(ManualVersion).where(ManualVersion.label==label))
    if not v: raise HTTPException(404, f'Unknown version: {label}')
    return v
def node_dict(n):
    return {'id':n.id,'version_id':n.version_id,'logical_key':n.logical_key,'section_number':n.section_number,'heading':n.heading,'parent_key':n.parent_key,'kind':n.kind,'text':n.body,'content_hash':n.content_hash}

@app.get('/health')
def health(): return {'status':'ok'}
@app.post('/versions/import')
def api_import(req: ImportRequest):
    if not Path(req.pdf_path).is_file(): raise HTTPException(400, 'pdf_path must point to a readable local PDF file')
    try: vid=import_pdf(req.pdf_path, req.label)
    except Exception as e: raise HTTPException(400, f'Could not import PDF: {e}')
    with Session() as db:
        v=db.get(ManualVersion, vid); count=len(db.scalars(select(Node).where(Node.version_id==vid)).all())
        return {'version':v.label,'version_id':vid,'node_count':count}
@app.get('/versions')
def versions():
    with Session() as db:
        return [{'label':v.label,'id':v.id,'filename':v.filename,'created_at':v.created_at} for v in db.scalars(select(ManualVersion).order_by(ManualVersion.id)).all()]
@app.get('/sections')
def sections(version: Optional[str]=None, top_level: bool=True):
    with Session() as db:
        if version is None: v=db.scalar(select(ManualVersion).order_by(ManualVersion.id.desc()))
        else: v=version_by_label(db,version)
        if not v: return {'version':None,'sections':[]}
        query=select(Node).where(Node.version_id==v.id)
        nodes=db.scalars(query.order_by(Node.id)).all()
        if top_level: nodes=[n for n in nodes if not n.section_number or '.' not in n.section_number]
        return {'version':v.label,'sections':[node_dict(n) for n in nodes]}
@app.get('/nodes/{node_id}')
def get_node(node_id: int):
    with Session() as db:
        n=db.get(Node,node_id)
        if not n: raise HTTPException(404,'Node not found')
        children=db.scalars(select(Node).where(Node.version_id==n.version_id, Node.parent_key==n.section_number).order_by(Node.id)).all()
        result=node_dict(n); result['children']=[node_dict(c) for c in children]
        return result
@app.get('/search')
def search(q: str=Query(min_length=1), version: Optional[str]=None):
    with Session() as db:
        v=version_by_label(db,version) if version else db.scalar(select(ManualVersion).order_by(ManualVersion.id.desc()))
        if not v: return {'results':[]}
        needle=q.lower(); nodes=db.scalars(select(Node).where(Node.version_id==v.id)).all()
        matches=[node_dict(n) for n in nodes if needle in n.heading.lower() or needle in n.body.lower()]
        return {'version':v.label,'query':q,'results':matches[:100]}
@app.get('/compare')
def compare(from_version: str='v1', to_version: str='v2'):
    with Session() as db:
        a,b=version_by_label(db,from_version),version_by_label(db,to_version)
        left={n.logical_key:n for n in db.scalars(select(Node).where(Node.version_id==a.id)).all()}
        right={n.logical_key:n for n in db.scalars(select(Node).where(Node.version_id==b.id)).all()}
        changes=[]
        for key in sorted(set(left)|set(right)):
            x,y=left.get(key),right.get(key)
            if x is None: status='added'
            elif y is None: status='removed'
            elif x.content_hash != y.content_hash: status='changed'
            else: status='unchanged'
            if status!='unchanged':
                changes.append({'logical_key':key,'status':status,'heading':(y or x).heading,'from_text':x.body if x else None,'to_text':y.body if y else None})
        return {'from_version':a.label,'to_version':b.label,'change_count':len(changes),'changes':changes,'matching_note':'Exact section number + normalized heading key; renumbered/renamed sections may be reported as remove/add.'}
@app.get('/compare/node/{logical_key:path}')
def compare_node(logical_key: str, from_version: str='v1', to_version: str='v2'):
    with Session() as db:
        a,b=version_by_label(db,from_version),version_by_label(db,to_version)
        x=db.scalar(select(Node).where(Node.version_id==a.id,Node.logical_key==logical_key)); y=db.scalar(select(Node).where(Node.version_id==b.id,Node.logical_key==logical_key))
        if not x and not y: raise HTTPException(404,'Logical node not found in either version')
        return {'logical_key':logical_key,'from_version':a.label,'to_version':b.label,'status':'added' if not x else 'removed' if not y else 'unchanged' if x.content_hash==y.content_hash else 'changed','from_text':x.body if x else None,'to_text':y.body if y else None}
@app.post('/selections')
def create_selection(req: SelectionRequest):
    with Session() as db:
        v=version_by_label(db,req.version)
        nodes=[]
        for nid in req.node_ids:
            n=db.get(Node,nid)
            if not n or n.version_id != v.id: raise HTTPException(400,f'Node {nid} does not belong to version {v.label}')
            nodes.append(n)
        snapshot='\n\n'.join(f'{n.heading}\n{n.body}' for n in nodes)
        sel=Selection(name=req.name,version_id=v.id,node_ids_json=json.dumps(req.node_ids),source_snapshot=snapshot,source_hash=digest(snapshot)); db.add(sel); db.commit(); db.refresh(sel)
        return {'selection_id':sel.id,'name':sel.name,'version':v.label,'node_ids':req.node_ids,'source_hash':sel.source_hash,'source_snapshot':sel.source_snapshot}
@app.get('/selections/{selection_id}')
def get_selection(selection_id: int):
    with Session() as db:
        s=db.get(Selection,selection_id)
        if not s: raise HTTPException(404,'Selection not found')
        v=db.get(ManualVersion,s.version_id)
        return {'selection_id':s.id,'name':s.name,'version':v.label,'node_ids':json.loads(s.node_ids_json),'source_hash':s.source_hash,'source_snapshot':s.source_snapshot}

def current_source_hash(db, s):
    v=db.scalar(select(ManualVersion).order_by(ManualVersion.id.desc()))
    if not v: return s.source_hash, True, None
    node_keys=json.loads(s.node_ids_json); original=db.get(ManualVersion,s.version_id)
    old_nodes=[db.get(Node,nid) for nid in node_keys]
    current=[]
    for n in old_nodes:
        if n:
            match=db.scalar(select(Node).where(Node.version_id==v.id,Node.logical_key==n.logical_key))
            current.append(match)
    if any(n is None for n in current): return None, True, v.label
    current_text='\n\n'.join(f'{n.heading}\n{n.body}' for n in current)
    return digest(current_text), digest(current_text)!=s.source_hash, v.label
@app.post('/selections/{selection_id}/generate')
def generate(selection_id: int, req: GenerateRequest=GenerateRequest()):
    with Session() as db:
        s=db.get(Selection,selection_id)
        if not s: raise HTTPException(404,'Selection not found')
        if not req.force:
            prior=db.scalar(select(GeneratedTests).where(GeneratedTests.selection_id==s.id,GeneratedTests.source_hash==s.source_hash))
            if prior: return {'generated_id':prior.id,'selection_id':s.id,'tests':json.loads(prior.output_json),'duplicate_policy':'Returned existing result for same selection/source hash.'}
        tests=None; model=os.getenv('OPENAI_MODEL','gpt-4o-mini')
        if os.getenv('OPENAI_API_KEY'):
            try:
                from openai import OpenAI
                client=OpenAI()
                response=client.chat.completions.create(model=model,temperature=0.2,response_format={'type':'json_object'},messages=[{'role':'system','content':'Create 3 to 5 software QA test case ideas based only on the provided medical device manual text. Do not provide medical advice. Return JSON with key "test_cases" containing objects with title, preconditions, steps (array), expected_result, source_excerpt. If details are missing, state assumptions.'},{'role':'user','content':s.source_snapshot}])
                parsed=json.loads(response.choices[0].message.content or '{}'); raw=parsed.get('test_cases')
                if isinstance(raw,list) and 3<=len(raw)<=5 and all(isinstance(x,dict) and all(k in x for k in ('title','steps','expected_result')) for x in raw): tests=raw
            except Exception:
                tests=None
        if tests is None:
            # Explicit fallback so the endpoint is demonstrable without an API key; not represented as LLM output.
            tests=[{'title':'Check documented limits','preconditions':'Device is powered on and configured for the selected manual section.','steps':['Exercise the relevant limit or boundary described in the selected text.'],'expected_result':'Behavior matches the selected source text.','source_excerpt':s.source_snapshot[:240],'generation_mode':'template_fallback'} ,{'title':'Check error handling','preconditions':'A safe test environment is available.','steps':['Simulate the applicable documented error condition.'],'expected_result':'The documented error response occurs and the device reaches the specified safe state.','source_excerpt':s.source_snapshot[:240],'generation_mode':'template_fallback'}, {'title':'Check persistence or recovery','preconditions':'The device and any required companion app are available.','steps':['Repeat the documented operation and inspect its result after recovery.'],'expected_result':'The result and recovery behavior match the selected manual text.','source_excerpt':s.source_snapshot[:240],'generation_mode':'template_fallback'}]
        record=GeneratedTests(selection_id=s.id,source_hash=s.source_hash,output_json=json.dumps(tests)); db.add(record); db.commit(); db.refresh(record)
        return {'generated_id':record.id,'selection_id':s.id,'version_pinned':db.get(ManualVersion,s.version_id).label,'tests':tests,'generation_mode':'llm' if os.getenv('OPENAI_API_KEY') and all(t.get('generation_mode')!='template_fallback' for t in tests) else 'template_fallback','note':'Template fallback is not an LLM response; configure OPENAI_API_KEY for LLM generation.'}
@app.get('/generated/{generated_id}')
def get_generated(generated_id: int):
    with Session() as db:
        g=db.get(GeneratedTests,generated_id)
        if not g: raise HTTPException(404,'Generated result not found')
        s=db.get(Selection,g.selection_id); current_hash,stale,current_version=current_source_hash(db,s)
        return {'generated_id':g.id,'selection_id':s.id,'tests':json.loads(g.output_json),'source_hash_at_generation':g.source_hash,'stale':stale,'current_version':current_version,'staleness_note':'Hash comparison is conservative and cannot determine whether a change is clinically meaningful.'}
