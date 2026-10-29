"""doni-be 임시 프론트 (React Flow 캔버스판).
설치: pip install "streamlit>=1.37" requests streamlit-flow-component
실행: streamlit run app_ui_flow.py   (백엔드 localhost:8000 + celery worker 필요)
"""
import time

import pandas as pd
import requests
import streamlit as st
from streamlit_flow import streamlit_flow
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
from streamlit_flow.state import StreamlitFlowState

API = "http://localhost:8000"
KO = {"standardize_data": "데이터 표준화", "clean_text": "문자 정리", "filter": "필터"}
EXT_ICON = {"pdf": "📕", "xlsx": "📗", "xls": "📗", "csv": "📊", "pptx": "📙", "hwp": "📘",
            "jpg": "🖼️", "jpeg": "🖼️", "png": "🖼️"}
OPS = ["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "starts_with", "ends_with",
       "is_null", "is_not_null"]
NULL_OPS = {"is_null", "is_not_null"}

st.set_page_config(page_title="파이프라인 빌더", layout="wide")
st.markdown("""
<style>
.block-container {padding: 0 1rem 1rem 1rem; max-width: 100%;}
.hd {font-size: 20px; font-weight: 700; padding: 14px 4px; border-bottom: 1px solid #e5e5e5; margin-bottom: 8px;}
section[data-testid="stSidebar"] {background: #fff; border-right: 1px solid #e5e5e5;}
section[data-testid="stSidebar"] .stButton > button {
  border: none; background: transparent; justify-content: flex-start; font-size: 13px;
  padding: 4px 8px; min-height: 0; color: #333; box-shadow: none;}
section[data-testid="stSidebar"] .stButton > button:hover {background: #f1f1f1;}
section[data-testid="stSidebar"] input {background: #f3f4f6; border-radius: 6px;}
</style>
""", unsafe_allow_html=True)


def call(method, path, **kw):
    r = requests.request(method, API + path, timeout=30, **kw)
    if r.status_code >= 400:
        try:
            msg = r.json().get("detail", r.text)
        except Exception:
            msg = r.text
        raise RuntimeError(f"{r.status_code}: {msg}")
    return r.json() if r.content else None


@st.cache_data(show_spinner=False)  # asset은 불변이라 캐시해도 안전
def asset_info(aid):
    return call("GET", f"/assets/{aid}")


@st.cache_data(show_spinner=False)
def asset_rows(aid):
    return call("GET", f"/assets/{aid}/rows")


def num(s):
    for f in (int, float):
        try:
            return f(s)
        except ValueError:
            pass
    return s


def out_asset(node, runs):
    """이 노드가 내놓는 asset id (source=업로드 원본, 그 외=성공한 실행의 output_ref)."""
    if node["kind"] == "source":
        return node["source_asset_id"]
    run = runs.get(str(node["id"]))
    return run["output_ref"] if run and run["status"] == "succeeded" else None


def form(kind, node_id, aid):
    cols = asset_rows(aid)["columns"]
    if not cols:
        st.error("표 형태 데이터가 아니라 변환할 수 없어요 (PDF/이미지 등).")
        return
    if kind == "standardize_data":
        c = st.selectbox("컬럼", cols)
        old = st.text_input("원래값")
        new = st.text_input("새 값")
        trim = st.checkbox("앞뒤 공백 무시")
        ic = st.checkbox("대소문자 무시")
        params = {"mappings": {c: {old: new}}, "trim": trim, "ignore_case": ic}
    elif kind == "clean_text":
        c = st.multiselect("컬럼", cols)
        pat = st.text_input("지울/바꿀 패턴 (정규식, RE2)")
        rep = st.text_input("바꿀 문자 (비우면 삭제)")
        params = {"columns": c, "pattern": pat, "replacement": rep}
    else:
        mode = st.radio("조건에 맞는 행을", ["keep", "drop"], horizontal=True,
                        format_func=lambda x: {"keep": "남기기", "drop": "제거"}[x])
        c = st.selectbox("컬럼", cols)
        op = st.selectbox("연산", OPS)
        sample = next((r[c] for r in asset_rows(aid)["rows"] if r.get(c) is not None), None)
        is_num = isinstance(sample, (int, float)) and not isinstance(sample, bool)
        text_op = op in ("contains", "starts_with", "ends_with")
        vtype = st.radio("값 타입 (컬럼 값 기준으로 자동 선택)", ["문자", "숫자"], index=int(is_num), horizontal=True,
                         key=f"vt_{c}", disabled=op in NULL_OPS or text_op)
        val = st.text_input("값 (따옴표 없이 입력, in/not_in은 쉼표로 구분)", disabled=op in NULL_OPS)
        conv = (lambda x: num(x.strip())) if vtype == "숫자" and not text_op else (lambda x: x.strip())
        if op in NULL_OPS:
            v = None
        elif op in ("in", "not_in"):
            v = [conv(x) for x in val.split(",")]
        else:
            v = conv(val)
        params = {"mode": mode, "conditions": [{"column": c, "op": op, "value": v}]}

    if st.button("실행", type="primary"):
        try:
            res = call("POST", "/pipelines/nodes/transform",
                       json={"input_node_id": node_id, "kind": kind, "params": params})
            nid = res["node"]["id"]
            with st.spinner("실행 중..."):
                for _ in range(30):  # 최대 30초 폴링
                    if call("GET", f"/pipelines/nodes/{nid}/runs/latest")["status"] in ("succeeded", "failed"):
                        break
                    time.sleep(1)
            st.session_state.sel = nid
            st.rerun()
        except RuntimeError as e:
            st.error(str(e))


def node_view(n, run, selected):
    """(markdown 내용, 스타일). 그림처럼 아이콘+제목 / 아래 회색 부제."""
    if n["kind"] == "source":
        a = asset_info(n["source_asset_id"])
        ext = (a.get("ext") or "").lower()
        title, sub, icon = a["name"], ext.upper() or "FILE", EXT_ICON.get(ext, "📄")
    else:
        status = run["status"] if run else "pending"
        icon, title = "🔗", KO.get(n["kind"], n["kind"])
        if status == "succeeded":
            sub = f"{asset_info(run['output_ref']).get('row_count')}행"
        else:
            sub = {"failed": "❌ 실패"}.get(status, "⏳ 실행 중")
    style = {"width": 95, "padding": "4px 5px", "borderRadius": 4, "textAlign": "left", "fontSize": 8,
             "border": "2px solid #333" if selected else "1px solid #e0e0e0",
             "background": "#fff" if selected else "#fafafa",
             "color": "#111" if selected else "#777"}
    return f"{icon} **{title}**\n\n{sub}", style


def build_state(nodes, edges, runs, sel, last):
    """/graph 결과 -> 캔버스 상태. 사용자가 드래그해 둔 위치(last)는 유지, 새 노드는 열 단위로 배치."""
    oldpos = {}
    if last:
        for o in last.nodes:
            try:
                oldpos[o.id] = (o.position["x"], o.position["y"])
            except Exception:
                pass
    parents = {}
    for e in edges:
        parents.setdefault(e["dst_node_id"], []).append(e["src_node_id"])
    depth, rows, fn = {}, {}, []
    for n in sorted(nodes, key=lambda n: n["id"]):
        d = depth[n["id"]] = 1 + max((depth.get(p, 0) for p in parents.get(n["id"], [])), default=-1)
        r = rows[d] = rows.get(d, -1) + 1
        content, style = node_view(n, runs.get(str(n["id"])), n["id"] == sel)
        fn.append(StreamlitFlowNode(
            id=str(n["id"]), pos=oldpos.get(str(n["id"]), (d * 140, r * 55)), data={"content": content},
            node_type="input" if n["kind"] == "source" else "default",
            source_position="right", target_position="left", style=style))
    fe = [StreamlitFlowEdge(id=f"e{e['id']}", source=str(e["src_node_id"]), target=str(e["dst_node_id"]),
                            style={"stroke": "#999", "strokeWidth": 1.5}) for e in edges]
    state = StreamlitFlowState(fn, fe)
    state.selected_id = str(sel) if sel else None
    return state


# ---- 파이프라인 (새로고침해도 URL ?pid= 로 유지) ----
pid = st.query_params.get("pid")
if not pid:
    pid = call("POST", "/pipelines", json={"name": "임시 파이프라인"})["id"]
    st.query_params["pid"] = str(pid)
pid = int(pid)

g = call("GET", f"/pipelines/{pid}/graph")
nodes, edges, runs = g["nodes"], g["edges"], g["runs"]
sel = st.session_state.get("sel")
sel_node = next((n for n in nodes if n["id"] == sel), None)

# ---- 왼쪽 '노드 추가' 패널 ----
with st.sidebar:
    st.markdown("### 노드 추가")
    q = st.text_input("검색", placeholder="🔍 기능을 검색하세요.", label_visibility="collapsed")
    with st.expander("📁 파일 업로드", expanded=not nodes):
        up = st.file_uploader("파일", key=f"up{st.session_state.get('n', 0)}", label_visibility="collapsed")
        if up and st.button("캔버스에 올리기"):
            try:
                res = call("POST", "/uploads", files={"file": (up.name, up.getvalue(), up.type)})
                call("POST", f"/pipelines/{pid}/nodes", json={"kind": "source", "source_asset_id": res["asset_id"]})
                st.session_state.n = st.session_state.get("n", 0) + 1
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))
    st.markdown(":blue[🔗] **데이터 변환**")
    for k, label in KO.items():
        if q and q not in label:
            continue
        if st.button(label, key=f"menu_{k}", use_container_width=True):
            aid = out_asset(sel_node, runs) if sel_node else None
            if not sel_node:
                st.warning("먼저 오른쪽 네모를 선택하세요.")
            elif not aid:
                st.warning("이 노드는 아직 결과가 없어요.")
            else:
                st.dialog(label)(form)(k, sel_node["id"], aid)
    st.caption(f"pipeline id: {pid}")

# ---- 오른쪽 캔버스 ----
st.markdown('<div class="hd">파이프라인 빌더</div>', unsafe_allow_html=True)
if st.button("🔄 새로고침"):
    st.rerun()

if not nodes:
    st.info("왼쪽에서 파일을 올리면 여기에 네모가 생겨요.")
else:
    sig = (tuple((n["id"], (runs.get(str(n["id"])) or {}).get("status")) for n in nodes), len(edges), sel)
    if st.session_state.get("sig") != sig:  # 노드/상태/선택이 바뀐 때만 다시 만든다 (드래그 위치는 유지)
        st.session_state.flow_in = build_state(nodes, edges, runs, sel, st.session_state.get("last"))
        st.session_state.sig = sig
    last = streamlit_flow("canvas", st.session_state.flow_in, height=347, fit_view=True,
                          show_controls=True, show_minimap=False, get_node_on_click=True,
                          style={"backgroundColor": "#f3f3f3"})
    st.session_state.last = last
    if last.selected_id and str(sel) != str(last.selected_id):
        st.session_state.sel = int(last.selected_id)
        st.rerun()

# ---- 선택한 네모의 내용 ----
st.divider()
if sel_node:
    run = runs.get(str(sel))
    aid = out_asset(sel_node, runs)
    if run and run["status"] == "failed":
        st.error(f"실행 실패: {run['error']}")
    elif aid:
        d = asset_rows(aid)
        if d["columns"]:
            st.caption(f"{asset_info(aid)['name']} — {d['total']}행")
            st.dataframe(pd.DataFrame(d["rows"], columns=d["columns"]), use_container_width=True)
        else:
            st.info("미리보기를 지원하지 않는 파일이에요 (PDF/이미지 등).")
    else:
        st.info("실행 중이에요. 🔄 새로고침을 눌러 확인하세요.")
else:
    st.caption("네모를 누르면 내용이 여기 보여요.")
