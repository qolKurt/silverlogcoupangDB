from flask import Flask, render_template_string, request, jsonify
import requests
import os
from datetime import datetime, timedelta

app = Flask(__name__)

# GitHub 연동을 위한 환경 변수 (Vercel Dashboard용)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER")
GITHUB_REPO = os.environ.get("GITHUB_REPO")

# ==========================================
# 1단계: 실버로그 어드민 API 연동
# ==========================================
def login_silverlog():
    login_url = "https://silverlog-admin.vercel.app/api/auth/login"
    payload = {"username": "admin", "password": "changeme123"}
    headers = {"Content-Type": "application/json"}
    
    session = requests.Session()
    response = session.post(login_url, json=payload, headers=headers)
    
    if response.status_code == 200:
        return session
    return None

# ==========================================
# 2단계: 대시보드 화면 생성 (HTML 렌더링)
# ==========================================
@app.route('/')
def index():
    session = login_silverlog()
    if not session:
        return "❌ 어드민 로그인에 실패했습니다. 아이디/비밀번호를 확인하세요."
        
    res = session.get("https://silverlog-admin.vercel.app/api/catalogue?all=true")
    all_items = res.json()
    if isinstance(all_items, dict):
        all_items = all_items.get("items", all_items.get("data", []))
        
    manual_items = []
    for item in all_items:
        ref_url = item.get("reference") or ""
        source = item.get("purchaseSource") or ""
        
        is_coupang = "coupang.com" in ref_url or source == "쿠팡"
        is_costco = "costco" in ref_url.lower() or source == "코스트코" or ref_url == "코스트코"
        
        if is_coupang or is_costco:
            raw_date = item.get("updatedAt") or item.get("updated_at") or ""
            if raw_date:
                try:
                    clean_date = raw_date.replace("Z", "").split(".")[0]
                    dt = datetime.strptime(clean_date[:19], "%Y-%m-%dT%H:%M:%S")
                    kst_dt = dt + timedelta(hours=9)
                    item['formatted_date'] = kst_dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    item['formatted_date'] = raw_date[:10] + " " + raw_date[11:16]
            else:
                item['formatted_date'] = "기록 없음"
                
            item['is_costco'] = is_costco
            item['source_name'] = "코스트코" if is_costco else "쿠팡"
            
            # 유효한 링크 여부 판단
            if not ref_url or not ref_url.strip().startswith("http"):
                item['has_valid_link'] = False
            else:
                item['has_valid_link'] = True
                
            manual_items.append(item)
            
    html_template = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>실버로그 수동 관리 대시보드</title>
        <style>
            body { font-family: 'Malgun Gothic', sans-serif; background-color: #f4f7f6; padding: 20px; }
            h2 { color: #333; text-align: center; margin-bottom: 5px; }
            .subtitle { text-align: center; color: #666; margin-bottom: 20px; font-size: 14px; }
            
            /* 동기화 패널 스타일 */
            .sync-panel {
                background: linear-gradient(135deg, #2c3e50, #34495e);
                color: white;
                padding: 18px 24px;
                border-radius: 8px;
                margin-bottom: 25px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-wrap: wrap;
            }
            .sync-info { display: flex; flex-direction: column; gap: 6px; }
            .sync-title { font-size: 16px; font-weight: bold; color: #ff9f43; margin: 0; }
            .sync-status-box { display: flex; align-items: center; gap: 8px; font-size: 14px; }
            .status-value { padding: 3px 10px; border-radius: 20px; font-weight: bold; font-size: 12px; }
            .status-unknown { background-color: #7f8c8d; color: white; }
            .status-running { background-color: #3498db; color: white; animation: pulse 1.5s infinite; }
            .status-success { background-color: #2ecc71; color: white; }
            .status-failed { background-color: #e74c3c; color: white; }
            .sync-time { font-size: 12px; color: #bdc3c7; }
            .sync-actions { display: flex; gap: 10px; align-items: center; }
            .btn-primary { background-color: #ff9f43; color: white; border: none; padding: 10px 18px; border-radius: 4px; cursor: pointer; font-weight: bold; transition: 0.2s; }
            .btn-primary:hover { background-color: #e67e22; }
            .btn-primary:disabled { background-color: #7f8c8d; cursor: not-allowed; }
            .btn-link-sec { background-color: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: white; text-decoration: none; padding: 9px 16px; border-radius: 4px; font-weight: bold; transition: 0.2s; font-size: 14px; }
            .btn-link-sec:hover { background-color: rgba(255,255,255,0.2); }
            
            /* 탭 메뉴 스타일 */
            .tab-container {
                display: flex;
                gap: 8px;
                margin-bottom: 18px;
            }
            .tab-btn {
                padding: 10px 20px;
                background-color: #e2e8f0;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-weight: bold;
                color: #4a5568;
                transition: 0.2s;
                font-size: 14px;
            }
            .tab-btn:hover { background-color: #cbd5e1; }
            .tab-btn.active { background-color: #2c3e50; color: white; }
            
            /* 배지 스타일 */
            .badge {
                padding: 4px 10px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: bold;
                display: inline-block;
            }
            .badge-coupang { background-color: #ffe8d6; color: #d35400; }
            .badge-costco { background-color: #fadbd8; color: #c0392b; }
            .badge-nolink { background-color: #e2e8f0; color: #718096; font-size: 11px; }

            table { width: 100%; border-collapse: collapse; background-color: #fff; box-shadow: 0 2px 10px rgba(0,0,0,0.05); table-layout: fixed; }
            th, td { padding: 10px; border: 1px solid #ddd; text-align: center; vertical-align: middle; }
            td:not(:nth-child(2)) { white-space: nowrap; }
            td:nth-child(2) { word-break: break-all; }
            th { background-color: #ff9f43; color: white; font-size: 15px; }
            tr:hover { background-color: #fff5eb; }
            input[type="number"] { width: 90px; padding: 6px; text-align: right; border: 1px solid #ccc; border-radius: 4px; font-size: 15px; font-weight: bold; background-color: #e8f8f5; color: #117864; }
            select { padding: 4px 6px; border-radius: 4px; border: 1px solid #ccc; width: 100%; max-width: 150px; box-sizing: border-box; }
            .btn { padding: 6px 12px; background-color: #2ecc71; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; transition: 0.2s; white-space: nowrap; font-size: 14px; }
            .btn:hover { background-color: #27ae60; }
            .btn-link { background-color: #3498db; text-decoration: none; padding: 6px 12px; border-radius: 4px; color: white; display: inline-block; font-weight: bold; white-space: nowrap; font-size: 14px; }
            .btn-link:hover { background-color: #2980b9; }
            .price-display { font-weight: bold; color: #e74c3c; font-size: 16px; }
            .date-display { font-size: 13px; color: #7f8c8d; }
            
            @keyframes pulse {
                0% { opacity: 0.6; }
                50% { opacity: 1; }
                100% { opacity: 0.6; }
            }
            @media (max-width: 768px) {
                table { table-layout: auto; }
                colgroup { display: none; }
                .sync-panel { flex-direction: column; align-items: flex-start; gap: 15px; }
                .tab-container { flex-direction: column; width: 100%; }
                .tab-btn { width: 100%; text-align: center; }
                table, thead, tbody, th, td, tr { display: block; }
                th { display: none; }
                td { text-align: right; position: relative; padding-left: 50%; width: auto !important; white-space: normal !important; }
                td::before { content: attr(data-label); position: absolute; left: 10px; width: 45%; text-align: left; font-weight: bold; color: #ff9f43; }
            }
        </style>
    </head>
    <body>
        <h2>📦 실버로그 가격 및 재고 대시보드</h2>
        <div class="subtitle">쿠팡과 코스트코 상품은 수동으로 매입가를 업데이트하고, 홈플러스/이마트 상품은 원격 동기화 버튼을 통해 일괄 자동 갱신합니다.</div>
        
        <!-- 대형마트 동기화 제어판 -->
        <div class="sync-panel">
            <div class="sync-info">
                <p class="sync-title">🛒 대형마트(홈플러스, 이마트) 실시간 가격/상태 동기화</p>
                <div class="sync-status-box">
                    <span>최근 상태:</span>
                    <span id="syncStatus" class="status-value status-unknown">로딩 중...</span>
                    <span id="syncTime" class="sync-time"></span>
                </div>
            </div>
            <div class="sync-actions">
                <button id="btnTriggerSync" class="btn-primary" onclick="triggerSync()">⚡ 동기화 실행</button>
                <a id="lnkWorkflow" href="#" target="_blank" class="btn-link-sec" style="display:none;">📋 실행로그 보기</a>
            </div>
        </div>

        <!-- 구매처 필터링 탭 단추 -->
        <div class="tab-container">
            <button class="tab-btn active" onclick="filterTab('all', event)">전체 보기 ({% if items %}{{ items|length }}{% else %}0{% endif %})</button>
            <button class="tab-btn" onclick="filterTab('쿠팡', event)">쿠팡 상품</button>
            <button class="tab-btn" onclick="filterTab('코스트코', event)">코스트코 상품</button>
        </div>

        <table>
            <colgroup>
                <col style="width: 120px;"> <!-- 구매처 -->
                <col style="width: auto;">  <!-- 상품명 -->
                <col style="width: 170px;"> <!-- 상태 설정 -->
                <col style="width: 120px;"> <!-- 새 매입가 입력(원) -->
                <col style="width: 130px;"> <!-- 자동 계산 판매가(원) -->
                <col style="width: 130px;"> <!-- 최근 수정일 -->
                <col style="width: 100px;"> <!-- DB 반영 -->
                <col style="width: 130px;"> <!-- 참조 확인 -->
            </colgroup>
            <thead>
                <tr>
                    <th>구매처</th>
                    <th>상품명</th>
                    <th>상태 설정</th>
                    <th>새 매입가 입력(원)</th>
                    <th>자동 계산 판매가(원)</th>
                    <th>최근 수정일</th>
                    <th>DB 반영</th>
                    <th>참조 확인</th>
                </tr>
            </thead>
            <tbody>
                {% for item in items %}
                <tr class="item-row" data-source="{{ item.source_name }}">
                    <td data-label="구매처">
                        {% if item.is_costco %}
                        <span class="badge badge-costco">코스트코 🔴</span>
                        {% else %}
                        <span class="badge badge-coupang">쿠팡 🍊</span>
                        {% endif %}
                    </td>
                    <td data-label="상품명" style="text-align: left;"><strong>{{ item.name }}</strong></td>
                    <td data-label="상태 설정">
                        <select id="status_{{ item._id }}">
                            <option value="true" {% if item.active %}selected{% endif %}>🟢 판매중 (Active)</option>
                            <option value="false" {% if not item.active %}selected{% endif %}>🔴 비활성 (Inactive)</option>
                        </select>
                    </td>
                    <td data-label="새 매입가">
                        <input type="number" id="buyingPrice_{{ item._id }}" value="{{ item.buyingPrice }}" oninput="calculateSalePrice('{{ item._id }}')">
                    </td>
                    <td data-label="계산된 판매가">
                        <span id="displayPrice_{{ item._id }}" class="price-display">{{ item.price }}</span>원
                    </td>
                    <td data-label="최근 수정일">
                        <span id="date_{{ item._id }}" class="date-display">{{ item.formatted_date }}</span>
                    </td>
                    <td data-label="DB 반영">
                        <button class="btn" onclick="updateItem('{{ item._id }}', {{ item.originalPrice }})">적용하기</button>
                    </td>
                    <td data-label="참조 확인">
                        {% if item.has_valid_link %}
                        <a href="{{ item.reference }}" target="_blank" class="btn-link">🛒 링크 열기</a>
                        {% else %}
                        <span class="badge badge-nolink">🔗 링크 없음</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <script>
            let pollInterval = null;

            // 탭 필터링 자바스크립트 로직
            function filterTab(source, event) {
                const tabs = document.querySelectorAll('.tab-btn');
                tabs.forEach(tab => tab.classList.remove('active'));
                event.target.classList.add('active');

                const rows = document.querySelectorAll('.item-row');
                rows.forEach(row => {
                    if (source === 'all') {
                        row.style.display = '';
                    } else {
                        const rowSource = row.getAttribute('data-source');
                        if (rowSource === source) {
                            row.style.display = '';
                        } else {
                            row.style.display = 'none';
                        }
                    }
                });
            }

            function checkSyncStatus() {
                fetch('/sync-status')
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        const statusVal = document.getElementById('syncStatus');
                        const timeVal = document.getElementById('syncTime');
                        const btn = document.getElementById('btnTriggerSync');
                        const lnk = document.getElementById('lnkWorkflow');
                        
                        if (data.status === 'none') {
                            statusVal.innerText = '기록 없음';
                            statusVal.className = 'status-value status-unknown';
                            btn.disabled = false;
                            return;
                        }
                        
                        if (data.run_url) {
                            lnk.href = data.run_url;
                            lnk.style.display = 'inline-block';
                        }
                        
                        let dateStr = '';
                        if (data.updated_at) {
                            const date = new Date(data.updated_at);
                            // Convert UTC to Local time format KST
                            date.setHours(date.getHours() + 9);
                            dateStr = `(${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')} ${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')})`;
                        }
                        
                        if (data.status === 'queued' || data.status === 'in_progress') {
                            statusVal.innerText = '동기화 진행 중 🔄';
                            statusVal.className = 'status-value status-running';
                            timeVal.innerText = dateStr;
                            btn.disabled = true;
                            btn.innerText = '⏳ 동기화 진행 중...';
                            
                            if (!pollInterval) {
                                pollInterval = setInterval(checkSyncStatus, 5000);
                            }
                        } else if (data.status === 'completed') {
                            if (pollInterval) {
                                clearInterval(pollInterval);
                                pollInterval = null;
                            }
                            
                            btn.disabled = false;
                            btn.innerText = '⚡ 동기화 실행';
                            
                            if (data.conclusion === 'success') {
                                statusVal.innerText = '성공 ✅';
                                statusVal.className = 'status-value status-success';
                            } else {
                                statusVal.innerText = '실패 ❌';
                                statusVal.className = 'status-value status-failed';
                            }
                            timeVal.innerText = dateStr;
                        }
                    }
                })
                .catch(err => console.error('동기화 상태 체크 실패:', err));
            }

            function triggerSync() {
                if (!confirm('홈플러스/이마트 대형마트 상품 가격 동기화를 시작하시겠습니까?\\n상품 수가 많아 완료까지 약 5~10분이 소요됩니다.')) {
                    return;
                }
                
                const btn = document.getElementById('btnTriggerSync');
                btn.disabled = true;
                btn.innerText = '⏳ 요청 중...';
                
                fetch('/trigger-sync', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        alert('원격 동기화 명령이 정상 전달되었습니다. 잠시 기다려주세요.');
                        setTimeout(checkSyncStatus, 2000);
                    } else {
                        alert('동기화 실패: ' + data.message);
                        btn.disabled = false;
                        btn.innerText = '⚡ 동기화 실행';
                    }
                })
                .catch(err => {
                    alert('네트워크 오류가 발생했습니다.');
                    btn.disabled = false;
                    btn.innerText = '⚡ 동기화 실행';
                });
            }

            function calculateSalePrice(itemId) {
                const buyPrice = parseInt(document.getElementById('buyingPrice_' + itemId).value);
                if (!isNaN(buyPrice) && buyPrice > 0) {
                    const marginPrice = buyPrice * 1.07;
                    const salePrice = Math.floor(marginPrice / 100) * 100 + 90;
                    document.getElementById('displayPrice_' + itemId).innerText = salePrice.toLocaleString('ko-KR');
                } else {
                    document.getElementById('displayPrice_' + itemId).innerText = '0';
                }
            }

            function updateItem(itemId, origPrice) {
                const newBuyPrice = parseInt(document.getElementById('buyingPrice_' + itemId).value);
                const newStatus = document.getElementById('status_' + itemId).value === 'true';
                
                if (isNaN(newBuyPrice) || newBuyPrice <= 0) {
                    alert('매입가를 올바르게 입력해주세요.');
                    return;
                }

                const marginPrice = newBuyPrice * 1.07;
                const newSalePrice = Math.floor(marginPrice / 100) * 100 + 90;
                
                fetch('/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        item_id: itemId,
                        price: newSalePrice,
                        originalPrice: origPrice,
                        buyingPrice: newBuyPrice,
                        active: newStatus
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if(data.success) {
                        alert('✅ 성공적으로 업데이트 되었습니다!');
                        const now = new Date();
                        const timeString = now.getFullYear() + '-' +
                                           String(now.getMonth() + 1).padStart(2, '0') + '-' +
                                           String(now.getDate()).padStart(2, '0') + ' ' +
                                           String(now.getHours()).padStart(2, '0') + ':' +
                                           String(now.getMinutes()).padStart(2, '0');
                        const dateSpan = document.getElementById('date_' + itemId);
                        dateSpan.innerText = timeString;
                        dateSpan.style.color = '#e74c3c';
                        dateSpan.style.fontWeight = 'bold';
                    } else {
                        alert('❌ 업데이트 실패: ' + data.message);
                    }
                })
                .catch(error => {
                    alert('네트워크 오류가 발생했습니다: ' + error);
                });
            }

            window.addEventListener('DOMContentLoaded', () => {
                checkSyncStatus();
                setInterval(checkSyncStatus, 15000);
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, items=manual_items)


# ==========================================
# 3단계: 파이썬이 데이터를 받아 실버로그로 쏴주는 API
# ==========================================
@app.route('/update', methods=['POST'])
def update():
    data = request.json
    session = login_silverlog()
    if not session:
        return jsonify({"success": False, "message": "어드민 로그인 세션 만료"})
        
    update_url = f"https://silverlog-admin.vercel.app/api/catalogue/{data['item_id']}"
    payload = {
        "price": data['price'],
        "originalPrice": data['originalPrice'],
        "buyingPrice": data['buyingPrice'],
        "active": data['active']
    }
    
    res = session.patch(update_url, json=payload)
    if res.status_code == 200:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": f"서버 에러 (코드: {res.status_code})"})

# ==========================================
# 4단계: GitHub Actions 트리거 및 상태 조회 API
# ==========================================
@app.route('/trigger-sync', methods=['POST'])
def trigger_sync():
    if not GITHUB_TOKEN or not GITHUB_OWNER or not GITHUB_REPO:
        return jsonify({"success": False, "message": "GitHub 연동 환경 변수(TOKEN/OWNER/REPO)가 설정되지 않았습니다."}), 400
    
    dispatch_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    payload = {
        "event_type": "trigger-sync",
        "client_payload": {
            "triggered_by": "vercel-dashboard"
        }
    }
    
    try:
        res = requests.post(dispatch_url, json=payload, headers=headers)
        if res.status_code == 204:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": f"GitHub Actions API 호출 실패 (코드: {res.status_code})"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"서버 오류: {str(e)}"}), 500

@app.route('/sync-status', methods=['GET'])
def sync_status():
    if not GITHUB_TOKEN or not GITHUB_OWNER or not GITHUB_REPO:
        return jsonify({"success": False, "message": "GitHub 연동 환경 변수(TOKEN/OWNER/REPO)가 설정되지 않았습니다."}), 400
    
    runs_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/catalog_sync.yml/runs?per_page=1"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    try:
        res = requests.get(runs_url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            runs = data.get("workflow_runs", [])
            if runs:
                latest_run = runs[0]
                return jsonify({
                    "success": True,
                    "status": latest_run.get("status"),       # queued, in_progress, completed
                    "conclusion": latest_run.get("conclusion"), # success, failure, cancelled
                    "updated_at": latest_run.get("updated_at"), # ISO format UTC
                    "run_url": latest_run.get("html_url")
                })
            return jsonify({"success": True, "status": "none"})
        else:
            return jsonify({"success": False, "message": f"GitHub Actions 상태 조회 실패 (코드: {res.status_code})"}), 500
    except Exception as e:
        return jsonify({"success": False, "message": f"서버 오류: {str(e)}"}), 500