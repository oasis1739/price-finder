#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
네이버 쇼핑 최저가 검색기 — 웹서버 배포 버전
Render.com / Railway 등 무료 호스팅 서비스에 배포 가능
"""

from flask import Flask, request, jsonify, render_template_string
import requests as req
from bs4 import BeautifulSoup
import re, time, json
from urllib.parse import quote, quote_plus
from datetime import datetime

app = Flask(__name__)

# ──────────────────────────────────────────────
#  검색 엔진 로직
# ──────────────────────────────────────────────

REQUEST_TIMEOUT = 15
MAX_RESULTS     = 15
MATCH_THRESHOLD = 0.3
REQUEST_DELAY   = 1.2

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

ACCESSORY_KEYWORDS = [
    '케이스','커버','필름','보호필름','강화유리','액정보호','스크린',
    '충전기','케이블','배터리','보조배터리','파우치','스트랩','홀더',
    '그립','링','스탠드','이어폰','이어버드','헤드폰','이어셋',
    '펜촉','스타일러스','터치펜','S펜','s펜','EJ-P','ej-p',
    '교환용','수리용','부품','악세사리','액세서리','다이어리',
    '지갑형','카드','젤리','클리어','투명','범퍼',
]

def search_danawa(query, max_results=MAX_RESULTS):
    encoded = quote(query)
    url = f"https://search.danawa.com/dsearch.php?query={encoded}&sort=1&limit={max(max_results*3,30)}"
    try:
        resp = req.get(url, headers={**HEADERS,'Referer':'https://www.danawa.com/'}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        results = []
        for item in soup.select('li.prod_item'):
            try:
                name_el = item.select_one('p.prod_name a')
                if not name_el: continue
                name = re.sub(r'\s+',' ', name_el.get_text(strip=True))
                price_el = item.select_one('.price_sect a')
                if not price_el: continue
                price_text = price_el.get_text(strip=True)
                price_num = re.sub(r'[^\d]','', price_text)
                if not price_num: continue
                price = int(price_num)
                if price <= 0: continue
                href = name_el.get('href','')
                pcode_m = re.search(r'pcode=(\d+)', href)
                pcode = pcode_m.group(1) if pcode_m else ''
                danawa_link = f"https://prod.danawa.com/info/?pcode={pcode}" if pcode else href
                naver_link = f"https://search.shopping.naver.com/search/all?query={quote_plus(name)}&sort=price_asc"
                results.append({'name':name,'price':price,'price_text':price_text,
                                 'danawa_link':danawa_link,'naver_link':naver_link,'pcode':pcode,'source':'danawa'})
            except: continue
        return results
    except req.exceptions.Timeout:
        return [{'error':'요청 시간 초과'}]
    except Exception as e:
        return [{'error': str(e)}]

def search_naver_api(query, client_id, client_secret, max_results=MAX_RESULTS):
    url = "https://openapi.naver.com/v1/search/shop.json"
    params = {'query':query,'display':min(max_results,100),'start':1,'sort':'asc'}
    headers = {**HEADERS,'X-Naver-Client-Id':client_id,'X-Naver-Client-Secret':client_secret,'Accept':'application/json'}
    try:
        resp = req.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 401: return [{'error':'API 키 인증 실패'}]
        resp.raise_for_status()
        results = []
        for item in resp.json().get('items',[]):
            lprice = int(item.get('lprice',0))
            if lprice <= 0: continue
            title = re.sub(r'<[^>]+>','', item.get('title','')).strip()
            pid = item.get('productId','')
            nlink = f"https://search.shopping.naver.com/catalog/{pid}" if pid else item.get('link','')
            results.append({'name':title,'price':lprice,'price_text':f"{lprice:,}원",
                            'danawa_link':'','naver_link':nlink,'source':'naver_api'})
        return results
    except Exception as e:
        return [{'error': str(e)}]

def calc_similarity(a, b):
    wa = set(re.findall(r'[a-zA-Z0-9가-힣]+', a.lower()))
    wb = set(re.findall(r'[a-zA-Z0-9가-힣]+', b.lower()))
    if not wa or not wb: return 0.0
    return len(wa & wb) / len(wa | wb)

def filter_results(results, query, min_sim=0.25):
    if not query or not results: return results
    def has_acc(name): return any(k in name.lower() for k in ACCESSORY_KEYWORDS)
    non_acc = [r for r in results if not has_acc(r.get('name',''))]
    working = non_acc if non_acc else results
    tokens = set(re.findall(r'[a-zA-Z0-9가-힣]+', query.lower()))
    if tokens:
        def cov(n): return sum(1 for t in tokens if t in n.lower()) / len(tokens)
        f2 = [r for r in working if cov(r.get('name','')) >= min_sim]
        if f2: working = f2
    prices = sorted([r['price'] for r in working if 'price' in r])
    if len(prices) >= 3:
        med = prices[len(prices)//2]
        f3 = [r for r in working if r.get('price',0) >= med*0.05]
        if f3: working = f3
    return working if working else results

def find_cross(a_list, b_list):
    matched, seen = [], set()
    for a in a_list:
        for b in b_list:
            if a.get('pcode') and a.get('pcode') == b.get('pcode'):
                if a['pcode'] not in seen:
                    seen.add(a['pcode']); matched.append(a)
                continue
            if calc_similarity(a.get('name',''), b.get('name','')) >= MATCH_THRESHOLD:
                key = a.get('pcode') or b.get('pcode') or id(a)
                if key not in seen:
                    seen.add(key)
                    matched.append(a if a['price'] <= b['price'] else b)
    return matched

def cross_reference_search(product_number=None, product_name=None, api_key=None):
    if not product_number and not product_name:
        return {'error':'제품번호 또는 상품명을 입력해주세요.'}

    client_id = client_secret = None
    if api_key and ':' in api_key:
        client_id, client_secret = api_key.split(':',1)

    def do_search(query):
        if client_id and client_secret:
            return search_naver_api(query, client_id, client_secret)
        return search_danawa(query)

    r_num = r_name = []
    if product_number:
        r_num = do_search(product_number)
        if r_num and 'error' in r_num[0]: r_num = []
        if product_name: time.sleep(REQUEST_DELAY)
    if product_name:
        r_name = do_search(product_name)
        if r_name and 'error' in r_name[0]: r_name = []

    if r_num and r_name:
        matched = find_cross(r_num, r_name)
        if matched:
            best = dict(min(matched, key=lambda x: x['price']))
            best['match_method'] = '교차검색 일치'; pool = matched
        else:
            valid = [r for r in r_name if 'price' in r]
            if valid:
                filtered = filter_results(valid, product_name)
                pool = filtered if filtered else valid
                best = dict(min(pool, key=lambda x: x['price']))
                best['match_method'] = '상품명 검색 최저가'
            else:
                valid = [r for r in r_num if 'price' in r]
                best = dict(min(valid, key=lambda x: x['price']))
                best['match_method'] = '제품번호 검색 최저가'; pool = valid
    elif r_name:
        valid = [r for r in r_name if 'price' in r]
        if not valid: return {'product_number':product_number or '','product_name':product_name or '','error':'가격 정보 없음'}
        filtered = filter_results(valid, product_name)
        pool = filtered if filtered else valid
        best = dict(min(pool, key=lambda x: x['price']))
        best['match_method'] = '상품명 검색 최저가'
    elif r_num:
        valid = [r for r in r_num if 'price' in r]
        if not valid: return {'product_number':product_number or '','product_name':product_name or '','error':'가격 정보 없음'}
        best = dict(min(valid, key=lambda x: x['price']))
        best['match_method'] = '제품번호 검색 최저가'; pool = valid
    else:
        return {'product_number':product_number or '','product_name':product_name or '','error':'검색 결과 없음'}

    top5 = sorted([r for r in pool if 'price' in r], key=lambda x: x['price'])[:5]
    return {
        'product_number': product_number or '',
        'product_name':   product_name or '',
        'found_name':     best.get('name',''),
        'lowest_price':   best.get('price',0),
        'price_text':     best.get('price_text',''),
        'link':           best.get('naver_link',''),
        'danawa_link':    best.get('danawa_link',''),
        'mall_name':      best.get('mall_name',''),
        'brand':          best.get('brand',''),
        'match_method':   best.get('match_method',''),
        'source':         best.get('source',''),
        'timestamp':      datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'top_results':    top5,
    }


# ──────────────────────────────────────────────
#  Flask 라우트
# ──────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.get_json(force=True)
    result = cross_reference_search(
        product_number=data.get('product_number'),
        product_name=data.get('product_name'),
        api_key=data.get('api_key'),
    )
    return jsonify(result)

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


# ──────────────────────────────────────────────
#  HTML 페이지
# ──────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🛒 최저가 검색기</title>
<style>
  :root {
    --green:#03C75A;--green-d:#02a14b;--blue:#1a73e8;--orange:#e85d04;
    --bg:#f0f2f5;--card:#fff;--text:#212529;--sub:#6c757d;
    --border:#dee2e6;--success:#28a745;--error:#dc3545;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Malgun Gothic','맑은 고딕','Apple SD Gothic Neo',sans-serif;background:var(--bg);color:var(--text)}
  .header{background:#343a40;color:#fff;padding:14px 24px;display:flex;align-items:center;gap:12px}
  .header h1{font-size:18px}.header small{color:#aaa;font-size:12px}
  .tabs{display:flex;background:#fff;border-bottom:2px solid var(--border);padding:0 20px}
  .tab-btn{padding:12px 22px;cursor:pointer;border:none;background:none;font-size:14px;color:var(--sub);border-bottom:3px solid transparent;margin-bottom:-2px;transition:.2s}
  .tab-btn.active{color:var(--green);border-bottom-color:var(--green);font-weight:700}
  .tab-content{display:none}.tab-content.active{display:block}
  .container{max-width:960px;margin:0 auto;padding:20px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}
  .card-title{background:var(--green);color:#fff;padding:6px 14px;font-size:12px;font-weight:700}
  .card-body{padding:18px}
  .form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .form-group label{display:block;font-size:13px;color:var(--sub);margin-bottom:5px;font-weight:600}
  .form-group input{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:6px;font-size:14px;outline:none;transition:.2s}
  .form-group input:focus{border-color:var(--green)}
  .btn-row{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap}
  .btn{padding:10px 22px;border:none;border-radius:6px;cursor:pointer;font-size:14px;font-weight:700;transition:.15s}
  .btn-primary{background:var(--green);color:#fff}.btn-primary:hover{background:var(--green-d)}
  .btn-primary:disabled{background:#ccc;cursor:not-allowed}
  .btn-secondary{background:var(--border);color:var(--text)}.btn-secondary:hover{background:#ccc}
  .btn-blue{background:var(--blue);color:#fff}.btn-blue:hover{background:#1558b0}
  .btn-orange{background:var(--orange);color:#fff}.btn-orange:hover{background:#c04d02}
  .btn-sm{padding:7px 14px;font-size:12px}
  .result-summary{display:flex;align-items:baseline;gap:12px;margin-bottom:12px}
  .price-big{font-size:28px;font-weight:900;color:var(--success)}
  .found-name{font-size:13px;color:var(--sub)}
  .link-row{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap}
  .table-wrap{overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:13px}
  thead th{background:#343a40;color:#fff;padding:9px 12px;text-align:left;white-space:nowrap}
  tbody tr:nth-child(even){background:#f8f9fa}
  tbody tr:hover{background:#e8f4ff}
  tbody td{padding:9px 12px;border-bottom:1px solid #f0f0f0}
  .link-cell a{color:var(--blue);text-decoration:none;font-size:12px}
  .link-cell a:hover{text-decoration:underline}
  .rank-1 td{font-weight:700;color:var(--success)}
  .badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700}
  .badge-ok{background:#d4edda;color:#155724}.badge-err{background:#f8d7da;color:#721c24}
  .progress-bar-wrap{background:var(--border);border-radius:20px;height:12px;overflow:hidden;margin:10px 0}
  .progress-bar{height:100%;background:var(--green);transition:width .3s;border-radius:20px}
  .log-box{background:#1e1e1e;color:#ccc;font-family:Consolas,monospace;font-size:12px;padding:10px;border-radius:6px;height:120px;overflow-y:auto;white-space:pre-wrap}
  @keyframes spin{to{transform:rotate(360deg)}}
  .spinner{display:inline-block;width:16px;height:16px;border:2px solid #ccc;border-top-color:var(--green);border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:6px}
  .alert{padding:12px 16px;border-radius:6px;font-size:13px;margin-bottom:12px}
  .alert-err{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb}
  .alert-ok{background:#d4edda;color:#155724;border:1px solid #c3e6cb}
  .file-area{border:2px dashed var(--border);border-radius:8px;padding:20px;text-align:center;cursor:pointer;transition:.2s}
  .file-area:hover,.file-area.dragover{border-color:var(--green);background:#f0fff4}
  .file-area input[type=file]{display:none}
  .excel-preview{max-height:200px;overflow-y:auto;font-size:12px}
  .hint{font-size:12px;color:var(--sub)}
  @media(max-width:600px){.form-grid{grid-template-columns:1fr}}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>🛒 최저가 검색기</h1>
    <small>네이버 쇼핑 · 다나와 기반 — 제품번호 + 상품명 교차 검색</small>
  </div>
</div>

<div class="tabs">
  <button class="tab-btn active" onclick="switchTab(this,'single')">🔍 단일 검색</button>
  <button class="tab-btn" onclick="switchTab(this,'batch')">📂 일괄 검색 (엑셀/CSV)</button>
  <button class="tab-btn" onclick="switchTab(this,'help')">❓ 도움말</button>
</div>

<!-- 단일 검색 -->
<div id="tab-single" class="tab-content active">
<div class="container">
  <div class="card">
    <div class="card-title">검색 입력</div>
    <div class="card-body">
      <div class="form-grid">
        <div class="form-group">
          <label>제품번호 (모델번호)</label>
          <input id="inp-num" type="text" placeholder="예: SM-S928B, MX000750" onkeydown="if(event.key==='Enter')doSearch()">
        </div>
        <div class="form-group">
          <label>상품명</label>
          <input id="inp-name" type="text" placeholder="예: 갤럭시 S24 울트라" onkeydown="if(event.key==='Enter')doSearch()">
        </div>
      </div>
      <div class="form-grid" style="margin-top:10px">
        <div class="form-group">
          <label>네이버 API 키 <span class="hint">(선택)</span></label>
          <input id="inp-api" type="text" placeholder="ClientID:ClientSecret">
        </div>
      </div>
      <div class="btn-row">
        <button class="btn btn-primary" id="search-btn" onclick="doSearch()">🔍 검색</button>
        <button class="btn btn-secondary" onclick="clearSingle()">🗑️ 초기화</button>
        <span class="hint">※ 제품번호 또는 상품명 중 하나만 입력해도 검색 가능 · Enter 키 가능</span>
      </div>
    </div>
  </div>
  <div id="single-loading" style="display:none">
    <div class="card"><div class="card-body" style="text-align:center;padding:30px">
      <span class="spinner"></span> 검색 중... 잠시 기다려주세요
    </div></div>
  </div>
  <div id="single-error" class="alert alert-err" style="display:none"></div>
  <div id="single-result" style="display:none">
    <div class="card">
      <div class="card-title">검색 결과</div>
      <div class="card-body">
        <div class="result-summary">
          <span class="price-big" id="res-price"></span>
          <span class="found-name" id="res-name"></span>
        </div>
        <div class="link-row" id="res-links"></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>순위</th><th>상품명</th><th>가격</th><th>네이버 링크</th><th>다나와 링크</th></tr></thead>
            <tbody id="single-tbody"></tbody>
          </table>
        </div>
        <div style="margin-top:12px">
          <button class="btn btn-secondary btn-sm" onclick="saveSingleCSV()">💾 CSV로 저장</button>
        </div>
      </div>
    </div>
  </div>
</div>
</div>

<!-- 일괄 검색 -->
<div id="tab-batch" class="tab-content">
<div class="container">
  <div class="card">
    <div class="card-title">엑셀 / CSV 파일 업로드</div>
    <div class="card-body">
      <div class="file-area" id="drop-zone"
           onclick="document.getElementById('file-input').click()"
           ondragover="event.preventDefault();this.classList.add('dragover')"
           ondragleave="this.classList.remove('dragover')"
           ondrop="handleDrop(event)">
        <input type="file" id="file-input" accept=".csv,.xlsx,.xls" onchange="handleFile(this.files[0])">
        <div style="font-size:36px">📂</div>
        <div style="font-size:15px;font-weight:700;margin:6px 0">엑셀(.xlsx) 또는 CSV 파일을 여기에 끌어다 놓거나 클릭해서 선택</div>
        <div class="hint">첫 번째 행: 헤더(제품번호, 상품명) · 나머지: 상품 목록</div>
      </div>
      <div id="file-preview" style="display:none;margin-top:14px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <strong id="file-name-lbl"></strong>
          <span id="file-row-count" class="badge badge-ok"></span>
          <button class="btn btn-secondary btn-sm" onclick="clearBatch()">✕ 제거</button>
        </div>
        <div class="excel-preview table-wrap"><table id="preview-table"></table></div>
      </div>
      <div class="form-grid" style="margin-top:14px">
        <div class="form-group">
          <label>네이버 API 키 <span class="hint">(선택)</span></label>
          <input id="batch-api" type="text" placeholder="ClientID:ClientSecret">
        </div>
      </div>
      <div class="btn-row" style="margin-top:12px">
        <button class="btn btn-primary" id="batch-btn" onclick="doBatch()" disabled>▶ 일괄 검색 시작</button>
        <button class="btn btn-secondary btn-sm" onclick="downloadSample()">📄 샘플 CSV 다운로드</button>
      </div>
    </div>
  </div>
  <div id="batch-progress" style="display:none">
    <div class="card">
      <div class="card-title">진행 상황</div>
      <div class="card-body">
        <div class="progress-bar-wrap"><div class="progress-bar" id="prog-bar" style="width:0%"></div></div>
        <div id="prog-label" style="text-align:center;font-size:13px;color:var(--sub)">0%</div>
        <div class="log-box" id="batch-log"></div>
      </div>
    </div>
  </div>
  <div id="batch-result" style="display:none">
    <div class="card">
      <div class="card-title">일괄 검색 결과</div>
      <div class="card-body">
        <div id="batch-summary" class="alert alert-ok" style="margin-bottom:12px"></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>제품번호</th><th>상품명</th><th>검색된 상품</th><th>최저가</th><th>링크</th><th>상태</th></tr></thead>
            <tbody id="batch-tbody"></tbody>
          </table>
        </div>
        <div style="margin-top:12px">
          <button class="btn btn-primary btn-sm" onclick="saveBatchCSV()">💾 결과 저장 (CSV)</button>
        </div>
      </div>
    </div>
  </div>
</div>
</div>

<!-- 도움말 -->
<div id="tab-help" class="tab-content">
<div class="container">
<div class="card"><div class="card-title">사용법 안내</div>
<div class="card-body" style="line-height:1.9;font-size:14px">
<h3 style="color:var(--green);margin-bottom:8px">🔍 단일 검색</h3>
<p>· 제품번호 또는 상품명 입력 후 [검색] 클릭 (Enter 키도 가능)</p>
<p>· 둘 다 입력하면 교차검색으로 더 정확한 결과</p>
<p>· 예: 제품번호 <code>SM-S928B</code> + 상품명 <code>갤럭시 S24 울트라</code></p>
<hr style="margin:16px 0;border-color:var(--border)">
<h3 style="color:var(--green);margin-bottom:8px">📂 일괄 검색 (엑셀/CSV)</h3>
<p>· 엑셀(.xlsx) 또는 CSV 파일 업로드 → 한 번에 여러 상품 검색</p>
<p>· 첫 번째 행: <code>제품번호</code>, <code>상품명</code> 헤더</p>
<p>· [샘플 CSV 다운로드] 버튼으로 양식 확인</p>
<hr style="margin:16px 0;border-color:var(--border)">
<h3 style="color:var(--green);margin-bottom:8px">⚙️ 기술 정보</h3>
<p>· 데이터: 다나와 (네이버 쇼핑과 동일한 최저가)</p>
<p>· 액세서리·케이스 자동 제외 + 가격 이상값 제거</p>
</div>
</div>
</div>
</div>

<script>
let singleResult=null,batchResults=[],batchRows=[];
function switchTab(btn,name){
  document.querySelectorAll('.tab-content').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(e=>e.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  btn.classList.add('active');
}
async function doSearch(){
  const num=document.getElementById('inp-num').value.trim();
  const name=document.getElementById('inp-name').value.trim();
  const api=document.getElementById('inp-api').value.trim();
  if(!num&&!name){alert('제품번호 또는 상품명을 입력해주세요.');return;}
  const btn=document.getElementById('search-btn');
  btn.disabled=true;btn.innerHTML='<span class="spinner"></span>검색 중…';
  document.getElementById('single-result').style.display='none';
  document.getElementById('single-error').style.display='none';
  document.getElementById('single-loading').style.display='block';
  try{
    const resp=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({product_number:num||null,product_name:name||null,api_key:api||null})});
    const data=await resp.json();
    document.getElementById('single-loading').style.display='none';
    if(data.error){
      document.getElementById('single-error').textContent='❌ '+data.error;
      document.getElementById('single-error').style.display='block';
    }else{renderSingleResult(data);}
  }catch(e){
    document.getElementById('single-loading').style.display='none';
    document.getElementById('single-error').textContent='❌ 오류: '+e;
    document.getElementById('single-error').style.display='block';
  }
  btn.disabled=false;btn.innerHTML='🔍 검색';
}
function renderSingleResult(data){
  singleResult=data;
  document.getElementById('res-price').textContent=data.price_text||'-';
  document.getElementById('res-name').textContent=(data.found_name||'-')+' ('+( data.match_method||'')+')';
  const ld=document.getElementById('res-links');ld.innerHTML='';
  if(data.link){const b=document.createElement('button');b.className='btn btn-blue btn-sm';b.textContent='🛍️ 네이버 쇼핑에서 보기';b.onclick=()=>window.open(data.link,'_blank');ld.appendChild(b);}
  if(data.danawa_link){const b=document.createElement('button');b.className='btn btn-orange btn-sm';b.textContent='📊 다나와에서 보기';b.onclick=()=>window.open(data.danawa_link,'_blank');ld.appendChild(b);}
  const tbody=document.getElementById('single-tbody');tbody.innerHTML='';
  (data.top_results||[]).forEach((item,i)=>{
    const tr=document.createElement('tr');if(i===0)tr.className='rank-1';
    tr.innerHTML=`<td>${i===0?'⭐':''}${i+1}</td><td>${esc(item.name||'').substring(0,50)}</td><td><strong>${esc(item.price_text||'N/A')}</strong></td><td class="link-cell">${item.naver_link?`<a href="${esc(item.naver_link)}" target="_blank">네이버 ↗</a>`:'-'}</td><td class="link-cell">${item.danawa_link?`<a href="${esc(item.danawa_link)}" target="_blank">다나와 ↗</a>`:'-'}</td>`;
    tbody.appendChild(tr);
  });
  document.getElementById('single-result').style.display='block';
}
function clearSingle(){
  document.getElementById('inp-num').value='';document.getElementById('inp-name').value='';
  document.getElementById('single-result').style.display='none';document.getElementById('single-error').style.display='none';singleResult=null;
}
function handleDrop(e){e.preventDefault();document.getElementById('drop-zone').classList.remove('dragover');const f=e.dataTransfer.files[0];if(f)handleFile(f);}
function handleFile(file){
  if(!file)return;const name=file.name.toLowerCase();
  if(name.endsWith('.csv')){const r=new FileReader();r.onload=e=>parseCSVText(e.target.result,file.name);r.readAsText(file,'utf-8');}
  else if(name.endsWith('.xlsx')||name.endsWith('.xls')){parseExcel(file);}
  else{alert('CSV 또는 엑셀 파일만 지원합니다.');}
}
function parseCSVText(text,filename){
  if(text.charCodeAt(0)===0xFEFF)text=text.slice(1);
  const lines=text.split('\n').map(l=>l.trim()).filter(Boolean);
  if(lines.length<2){alert('데이터가 없습니다.');return;}
  const headers=lines[0].split(',').map(h=>h.replace(/"/g,'').trim());
  const rows=[];
  for(let i=1;i<lines.length;i++){
    const cols=lines[i].split(',').map(c=>c.replace(/"/g,'').trim());
    const row={};headers.forEach((h,j)=>row[h]=cols[j]||'');rows.push(row);
  }
  showFilePreview(filename,rows,headers);
}
function parseExcel(file){
  if(typeof XLSX==='undefined'){
    const s=document.createElement('script');s.src='https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js';
    s.onload=()=>parseExcel(file);s.onerror=()=>alert('엑셀 라이브러리 로드 실패. CSV로 변환 후 업로드해주세요.');
    document.head.appendChild(s);return;
  }
  const r=new FileReader();
  r.onload=e=>{
    try{
      const wb=XLSX.read(e.target.result,{type:'array'});
      const ws=wb.Sheets[wb.SheetNames[0]];
      const data=XLSX.utils.sheet_to_json(ws,{header:1,defval:''});
      if(data.length<2){alert('데이터가 없습니다.');return;}
      const headers=data[0].map(h=>String(h).trim());
      const rows=data.slice(1).map(cols=>{const row={};headers.forEach((h,j)=>row[h]=String(cols[j]||'').trim());return row;}).filter(r=>Object.values(r).some(v=>v));
      showFilePreview(file.name,rows,headers);
    }catch(err){alert('엑셀 읽기 오류: '+err.message);}
  };
  r.readAsArrayBuffer(file);
}
function showFilePreview(filename,rows,headers){
  batchRows=rows;
  document.getElementById('file-name-lbl').textContent='📄 '+filename;
  document.getElementById('file-row-count').textContent=rows.length+'개 상품';
  const t=document.getElementById('preview-table');
  const preview=rows.slice(0,5);
  t.innerHTML=`<thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${preview.map(r=>`<tr>${headers.map(h=>`<td>${esc(r[h]||'')}</td>`).join('')}</tr>`).join('')}${rows.length>5?`<tr><td colspan="${headers.length}" style="text-align:center;color:var(--sub)">... 외 ${rows.length-5}개</td></tr>`:''}</tbody>`;
  document.getElementById('file-preview').style.display='block';
  document.getElementById('batch-btn').disabled=false;
}
function clearBatch(){
  batchRows=[];batchResults=[];
  document.getElementById('file-input').value='';
  document.getElementById('file-preview').style.display='none';
  document.getElementById('batch-btn').disabled=true;
  document.getElementById('batch-progress').style.display='none';
  document.getElementById('batch-result').style.display='none';
}
async function doBatch(){
  if(!batchRows.length)return;
  const api=document.getElementById('batch-api').value.trim();
  document.getElementById('batch-btn').disabled=true;
  document.getElementById('batch-progress').style.display='block';
  document.getElementById('batch-result').style.display='none';
  document.getElementById('batch-tbody').innerHTML='';
  document.getElementById('batch-log').textContent='';
  batchResults=[];
  const total=batchRows.length;let done=0;
  for(const row of batchRows){
    const num=row['제품번호']||row['제품 번호']||row['product_number']||row['모델번호']||'';
    const name=row['상품명']||row['상품 명']||row['product_name']||row['제품명']||'';
    if(!num&&!name){done++;continue;}
    batchLog(`[${done+1}/${total}] 검색 중: ${num||name}`);
    updateProgress(done,total,num||name);
    try{
      const resp=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({product_number:num||null,product_name:name||null,api_key:api||null})});
      const data=await resp.json();
      batchResults.push(data);addBatchRow(data,done);
      batchLog(data.error?`  ❌ ${data.error}`:`  ✅ ${data.price_text||'-'}`);
    }catch(e){
      const err={product_number:num,product_name:name,error:'오류'};
      batchResults.push(err);addBatchRow(err,done);batchLog(`  ❌ ${e}`);
    }
    done++;updateProgress(done,total,'');
    await new Promise(r=>setTimeout(r,200));
  }
  const ok=batchResults.filter(r=>!r.error).length;
  document.getElementById('batch-summary').textContent=`✅ 완료: ${ok}/${total}개 성공`;
  document.getElementById('batch-result').style.display='block';
  document.getElementById('batch-btn').disabled=false;
  batchLog(`\n=== 완료: ${ok}/${total}개 성공 ===`);
}
function updateProgress(done,total,label){
  const pct=Math.round((done/total)*100);
  document.getElementById('prog-bar').style.width=pct+'%';
  document.getElementById('prog-label').textContent=`${pct}% (${done}/${total})${label?' — '+label:''}`;
}
function batchLog(msg){const b=document.getElementById('batch-log');b.textContent+=msg+'\n';b.scrollTop=b.scrollHeight;}
function addBatchRow(data,idx){
  const tbody=document.getElementById('batch-tbody');
  const tr=document.createElement('tr');
  const isErr=!!data.error;
  tr.innerHTML=`<td>${esc(data.product_number||'')}</td><td>${esc((data.product_name||'').substring(0,18))}</td><td>${esc((data.found_name||data.error||'-').substring(0,28))}</td><td><strong>${esc(data.price_text||'-')}</strong></td><td class="link-cell">${data.link?`<a href="${esc(data.link)}" target="_blank">네이버 ↗</a>`:'-'}</td><td><span class="badge ${isErr?'badge-err':'badge-ok'}">${isErr?'실패':'완료'}</span></td>`;
  if(idx%2===1)tr.style.background='#f8f9fa';
  tbody.appendChild(tr);tr.scrollIntoView({behavior:'smooth',block:'nearest'});
}
function downloadSample(){
  const csv='\uFEFF제품번호,상품명\nSM-S928B,갤럭시 S24 울트라\nSM-S921B,갤럭시 S24\nSM-A556N,갤럭시 A55\n,아이폰 15 Pro\nMX000750,로지텍 MX 마스터 3S\n';
  trigger(csv,'products_sample.csv','text/csv;charset=utf-8');
}
function saveSingleCSV(){if(!singleResult)return;downloadCSV([singleResult],'result.csv');}
function saveBatchCSV(){if(!batchResults.length)return;downloadCSV(batchResults,'results.csv');}
function downloadCSV(results,filename){
  const h='제품번호,입력_상품명,검색된_상품명,최저가,링크,검색방법,검색시각\n';
  const rows=results.map(r=>[r.product_number||'',r.product_name||'',r.found_name||r.error||'실패',r.price_text||'실패',r.link||'',r.match_method||r.error||'',r.timestamp||''].map(v=>`"${String(v).replace(/"/g,'""')}"`).join(',')).join('\n');
  trigger('\uFEFF'+h+rows,filename,'text/csv;charset=utf-8');
}
function trigger(content,filename,mime){
  const blob=new Blob([content],{type:mime});const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download=filename;a.click();URL.revokeObjectURL(url);
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
</script>
</body>
</html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(__import__('os').environ.get('PORT', 5000)), debug=False)
