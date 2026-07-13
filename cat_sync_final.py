import re
import time
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# 1단계: 마트별 가격 추출 및 정밀 품절 판별 함수
# ==========================================

def scrape_homeplus(driver, url):
    """
    홈플러스 상품 가격 크롤링 및 품절 판별
    반환값: (original_price, buying_price, status)
    status: 'AVAILABLE' (판매중), 'SOLD_OUT' (품절), 'ERROR' (네트워크/파싱 에러)
    """
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.priceType'))
            )
        except:
            return None, None, "ERROR"

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 가격 태그 조회
        price_elem = soup.select_one('.priceType')
        if not price_elem:
            return None, None, "ERROR"

        buying_price = int(re.sub(r'[^0-9]', '', price_elem.text))
        
        # [홈플러스 정밀 검증] 
        # 1. 가격 자체가 0원이면 일시 품절/판매 종료로 간주
        is_sold_out = False
        if buying_price == 0:
            is_sold_out = True
        else:
            # 2. 전체 텍스트가 아닌, 구매 관련 버튼/하단 액션 영역만 한정 지어 '판매종료' 텍스트 검색
            action_elements = soup.find_all(['button', 'a', 'span'], class_=re.compile(r'btn|buy|action|footer'))
            for elem in action_elements:
                elem_text = elem.get_text()
                if "판매종료" in elem_text or "일시품절" in elem_text:
                    is_sold_out = True
                    break

        if is_sold_out:
            return None, None, "SOLD_OUT"

        # 원래 정가 추출 (할인 전 가격 태그가 없으면 매입가와 동일하게 설정)
        original_price_elem = soup.select_one('.priceItem.dc')
        if original_price_elem:
            original_price = int(re.sub(r'[^0-9]', '', original_price_elem.text))
        else:
            original_price = buying_price

        return original_price, buying_price, "AVAILABLE"
    except Exception as e:
        print(f"      [홈플러스 크롤링 에러] {e}")
        return None, None, "ERROR"


def scrape_emart(driver, url):
    """
    이마트몰 상품 가격 크롤링 및 품절 판별
    반환값: (original_price, buying_price, status)
    status: 'AVAILABLE' (판매중), 'SOLD_OUT' (품절), 'ERROR' (네트워크/파싱 에러)
    """
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.ssg_price'))
            )
        except:
            return None, None, "ERROR"

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 가격 정보 수집
        price_elem = soup.select_one('.ssg_price')
        if not price_elem:
            return None, None, "ERROR"

        buying_price = int(re.sub(r'[^0-9]', '', price_elem.text))
        if buying_price == 0:
            return None, None, "SOLD_OUT"

        # [이마트몰 초정밀 검증]
        is_sold_out = False
        btn_wrap = soup.select_one('.cdtl_btn_wrap')
        if btn_wrap:
            btn_text = btn_wrap.get_text()
            if "품절" in btn_text or "일시품절" in btn_text or "판매가 중지" in btn_text:
                is_sold_out = True
        else:
            action_buttons = soup.find_all(['button', 'a'], class_=re.compile(r'btn|buy|cart|action'))
            for btn in action_buttons:
                btn_txt = btn.get_text()
                if "품절" in btn_txt or "일시품절" in btn_txt or "판매종료" in btn_txt:
                    is_sold_out = True
                    break

        if is_sold_out:
            return None, None, "SOLD_OUT"

        # 이마트몰 정가 처리
        original_price = buying_price

        return original_price, buying_price, "AVAILABLE"
    except Exception as e:
        print(f"      [이마트 크롤링 에러] {e}")
        return None, None, "ERROR"


# ==========================================
# 2단계: 실버로그 어드민 API 연동
# ==========================================

def login_silverlog():
    """실버로그 어드민 로그인"""
    print("⏳ [어드민] 로그인 시도 중...")
    login_url = "https://silverlog-admin.vercel.app/api/auth/login"
    payload = {"username": "admin", "password": "changeme123"}
    headers = {"Content-Type": "application/json"}

    session = requests.Session()
    response = session.post(login_url, json=payload, headers=headers)

    if response.status_code == 200:
        print("✅ [어드민] 로그인 성공!")
        return session
    else:
        print(f"❌ [어드민] 로그인 실패: {response.status_code}")
        return None


# ==========================================
# 전체 카탈로그 동적 가격 & 상태 동기화 배치 시스템 (Active ⇄ Inactive 양방향 제어)
# ==========================================

def run_status_and_price_sync():
    print("🚀 [배치 작업 시작] 홈플러스 및 이마트 상품 가격 동기화 및 품절 격리 작업을 시작합니다.")
    
    # 1. 어드민 로그인
    session = login_silverlog()
    if not session:
        print("❌ 어드민 로그인에 실패하여 동기화를 종료합니다.")
        return

    # 2. 전체 상품 목록 수신
    try:
        response = session.get("https://silverlog-admin.vercel.app/api/catalogue?all=true")
        all_items = response.json()
    except Exception as e:
        print(f"❌ 데이터베이스 목록 조회 실패: {e}")
        return

    if isinstance(all_items, dict):
        all_items = all_items.get("items", all_items.get("data", []))
    
    if not all_items:
        print("⚠️ 처리할 상품 데이터가 존재하지 않습니다.")
        return

    print(f"✅ 데이터베이스에서 총 {len(all_items)}개의 상품 목록을 수신했습니다.")
    
    # 🧪 [디버그 메트릭] API 반환 상품의 활성/비활성 개수 체크
    active_count = sum(1 for i in all_items if i.get("active", True))
    inactive_count = sum(1 for i in all_items if not i.get("active", True))
    print(f"   ℹ️ API 반환 데이터 구성 -> 활성(Active): {active_count}개 / 비활성(Inactive): {inactive_count}개")

    # 3. 크롬 브라우저 가동 (Headless 모드)
    print("⏳ 크롬 브라우저를 백그라운드에서 가동하고 있습니다...")
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    # 통계 및 리포트용 변수
    stats = {
        "total": len(all_items),
        "skipped": 0,            # 코스트코 등 대상이 아니거나 링크가 원래 없는 경우
        "updated_selling": 0,    # 판매 중이어서 가격 업데이트 + active: True
        "deactivated": 0,        # 품절/판매중지 확인되어 active: False 전환
        "api_failed": 0          # API 전송 실패
    }
    
    # 수작업 리스트 보관함
    manual_check_list = []

    try:
        for idx, item in enumerate(all_items, 1):
            item_id = item.get("_id")
            name = item.get("name")
            ref_url = item.get("reference") or ""
            source = item.get("purchaseSource") or ""

            # 링크가 유효하지 않은 상품 처리 (예: 코스트코 및 빈 링크)
            if not ref_url or ref_url.strip() in ["", "코스트코"]:
                print(f"[{idx}/{len(all_items)}] ⏩ {name} | 건너뜀 (링크 없음/코스트코 상품)")
                stats["skipped"] += 1
                manual_check_list.append(f"- [링크누락/코스트코] {name} (구매처: {source or '코스트코'})")
                continue

            # 홈플러스 & 이마트 상품 선별
            is_homeplus = "homeplus.co.kr" in ref_url or source == "홈플러스"
            is_emart = "ssg.com" in ref_url or "emart" in ref_url or source == "이마트"

            # 타사 상품 건너뜀 (쿠팡은 다음 개발 시 여기에 추가됩니다)
            if not (is_homeplus or is_emart):
                print(f"[{idx}/{len(all_items)}] ⏩ {name} | 건너뜀 (타 마트 상품 - 소스: '{source}')")
                stats["skipped"] += 1
                continue

            print(f"\n🔄 [{idx}/{len(all_items)}] 동기화 및 상태 체크: {name}")
            print(f"   🔗 마트 링크: {ref_url}")
            
            # 크롤링 및 품절 판별
            prices = None
            if is_homeplus:
                prices = scrape_homeplus(driver, ref_url)
            elif is_emart:
                prices = scrape_emart(driver, ref_url)

            original_price, buying_price, sync_status = prices

            if sync_status == "ERROR":
                print(f"   ⚠️ [크롤링 실패] 페이지를 로드하지 못했거나 사이트 차단이 감지되었습니다. 기존 상태를 유지(스킵)합니다.")
                stats["api_failed"] += 1
                continue

            # PATCH할 데이터를 담을 페이로드 생성
            price_payload = {}

            if sync_status == "SOLD_OUT":
                # 🔴 [품절/판매종료인 경우] -> active: False 로 전환 및 수동 리스트 추가
                print(f"   🚨 [알림] 해당 상품이 '실제 품절' 혹은 '판매종료' 상태입니다.")
                print(f"   ➡️  Active 탭에서 Inactive 탭으로 던져버립니다. (active: False)")
                price_payload = {
                    "active": False
                }
                manual_check_list.append(f"- [품절감지] {name} (구매처: {source} | 링크: {ref_url})")
            else:
                # 🟢 [판매 중인 경우] -> 가격 업데이트 및 active: True 보장 (재입고 부활 적용)
                margin_price = buying_price * 1.07
                calculated_sale_price = int(margin_price // 100) * 100 + 90

                print(f"   📊 [정상 판매] 매입가: {buying_price}원 ➡️ 원래 정가: {original_price}원 | 새 판매가: {calculated_sale_price}원")
                price_payload = {
                    "price": calculated_sale_price,
                    "originalPrice": original_price,
                    "buyingPrice": buying_price,
                    "active": True
                }

            # 백엔드 전송 및 업데이트 적용
            try:
                update_url = f"https://silverlog-admin.vercel.app/api/catalogue/{item_id}"
                headers = {"Content-Type": "application/json", "Accept": "*/*"}
                response = session.patch(update_url, json=price_payload, headers=headers)
                
                if response.status_code == 200:
                    if sync_status == "SOLD_OUT":
                        print(f"   🎉 [성공] 품절 상태 반영 및 비활성화(Inactive) 완료!")
                        stats["deactivated"] += 1
                    else:
                        print(f"   🎉 [성공] 가격 갱신 및 활성화(Active) 복귀 완료!")
                        stats["updated_selling"] += 1
                else:
                    print(f"   ❌ [실패] 실버로그 서버가 업데이트 요청을 수락하지 않았습니다. (코드: {response.status_code})")
                    stats["api_failed"] += 1
            except Exception as api_err:
                print(f"   ❌ [실패] API 요청 중 오류: {api_err}")
                stats["api_failed"] += 1

            # 파싱 사이트의 차단 방지를 위한 미세 딜레이
            time.sleep(1.5)

    finally:
        driver.quit()

    # 최종 요약 보고서 콘솔 출력
    print("\n" + "=" * 60)
    print("📊 [일괄 상태 & 가격 동기화 최종 보고서]")
    print(f"  - 총 데이터베이스 상품 수: {stats['total']}개")
    print(f"  - 🟢 정상 판매 가격 갱신 & ACTIVE 보장: {stats['updated_selling']}개")
    print(f"  - 🔴 품절/판매중지 확인되어 INACTIVE로 격리: {stats['deactivated']}개")
    print(f"  - ⏩ 링크 누락/코스트코 건너뜀: {stats['skipped']}개")
    print(f"  - ❌ 실버로그 API 업데이트 실패: {stats['api_failed']}개")
    print("=" * 60)
    
    # 수작업 확인 리스트 콘솔 출력
    if manual_check_list:
        print("\n📋 [수작업 확인 필요 상품 목록]")
        print("-" * 60)
        for idx, item in enumerate(manual_check_list, 1):
            print(f"{idx}. {item}")
        print("-" * 60)
        
        # 텍스트 파일 리포트로 저장 (utf-8 인코딩)
        try:
            with open("manual_check_report.txt", "w", encoding="utf-8") as f:
                f.write("=== 수작업 확인 필요 상품 목록 ===\n\n")
                f.write(f"작성일시: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"감지된 항목 수: {len(manual_check_list)}개\n")
                f.write("-" * 50 + "\n")
                for item in manual_check_list:
                    f.write(item + "\n")
                f.write("-" * 50 + "\n")
            print("📁 로컬 폴더에 'manual_check_report.txt' 파일이 정상 생성되었습니다.")
        except Exception as file_err:
            print(f"⚠️ 리포트 파일 생성 실패: {file_err}")
    else:
        print("\n🎉 모든 상품이 정상적으로 수집되었습니다. 수작업 검토할 항목이 없습니다!")

if __name__ == "__main__":
    run_status_and_price_sync()