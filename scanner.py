from flask import Flask, render_template, request, jsonify
from pykrx import stock
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import re

app = Flask(__name__, template_folder='templates')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def find_prev_trading_dates():
    """전일 및 전전일 영업일 반환 - ohlcv_by_date 방식으로 안정적으로 탐색"""
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_date(start, end, "005930")
        if df is not None and not df.empty:
            df = df[df['거래량'] > 0]
            if len(df) >= 2:
                dates = [df.index[-1].strftime("%Y%m%d"), df.index[-2].strftime("%Y%m%d")]
                print(f"[날짜] 최근영업일={dates[0]} 전전일={dates[1]}")
                return dates[0], dates[1]
            elif len(df) == 1:
                return df.index[-1].strftime("%Y%m%d"), None
    except Exception as e:
        print(f"[날짜 탐색 오류] {e}")
    return None, None

def get_naver_market_data(market_code):
    """네이버 금융 상승종목 페이지 스크래핑"""
    market_name = "KOSPI" if market_code == 0 else "KOSDAQ"
    results = []
    try:
        for page in range(1, 6):
            r = requests.get(
                f"https://finance.naver.com/sise/sise_rise.naver?sosok={market_code}&page={page}",
                headers=HEADERS, timeout=15
            )
            r.encoding = 'euc-kr'
            soup = BeautifulSoup(r.text, 'html.parser')
            found = 0
            for row in soup.select('table.type_2 tr'):
                name_tag = row.select_one('a.tltle')
                if not name_tag:
                    continue
                try:
                    name = name_tag.text.strip()
                    code = name_tag['href'].split('code=')[-1][:6]
                    tds = row.select('td')
                    if len(tds) < 5:
                        continue

                    def clean(s):
                        return s.text.strip().replace(',','').replace('+','').replace('%','').replace(' ','')

                    # td[2]=종가, td[4]=등락률, td[5]=거래량
                    close_s = clean(tds[2])
                    chg_pct_s = clean(tds[4])
                    vol_s = clean(tds[5]) if len(tds) > 5 else '0'

                    close = int(close_s) if close_s.lstrip('-').isdigit() else 0
                    try:
                        chg_pct = float(chg_pct_s)
                    except:
                        chg_pct = 0.0
                    volume = int(vol_s) if vol_s.isdigit() else 0

                    if close <= 0 or chg_pct <= 0:
                        continue

                    results.append({
                        'code': code, 'name': name, 'market': market_name,
                        'close': close, 'change_pct': round(chg_pct, 2), 'volume': volume,
                    })
                    found += 1
                except:
                    continue

            print(f"[네이버] {market_name} {page}페이지: {found}개")
            if found == 0:
                break
    except Exception as e:
        print(f"[네이버 오류] {market_name}: {e}")
        import traceback; traceback.print_exc()
    return results

def get_top_movers(limit=50):
    """전일 KOSPI+KOSDAQ 상승종목 스캔 - 네이버 상승종목 페이지"""
    prev_date, prev2_date = find_prev_trading_dates()
    if not prev_date:
        return [], prev_date

    print(f"[스캔] 기준일: {prev_date}")
    results = []

    for market_code in [0, 1]:  # 0=KOSPI, 1=KOSDAQ
        market_results = get_naver_market_data(market_code)
        results.extend(market_results)
        print(f"[스캔] {'KOSPI' if market_code==0 else 'KOSDAQ'} {len(market_results)}개 수집")

    # 중복 제거 (종목코드 기준)
    seen = set()
    unique = []
    for r in results:
        if r['code'] not in seen:
            seen.add(r['code'])
            unique.append(r)

    # ── 필터링 ──────────────────────────────────────────
    filtered = []
    for r in unique:
        code = r['code']
        name = r['name']

        # 1. 우선주 제거 (종목코드 끝자리 5 = 우선주)
        if code.endswith('5'):
            print(f"[필터] 우선주 제거: {name}({code})")
            continue

        # 2. 종목명에 '우' '우B' 포함된 우선주 제거
        if name.endswith('우') or name.endswith('우B') or name.endswith('우C'):
            print(f"[필터] 우선주 제거: {name}({code})")
            continue

        # 3. 시가총액 확인 (네이버 API)
        try:
            res = requests.get(
                f'https://m.stock.naver.com/api/stock/{code}/integration',
                headers=HEADERS, timeout=8
            )
            if res.status_code == 200:
                infos = res.json().get('totalInfos', [])
                cap_str = ''
                for item in infos:
                    if item.get('code') == 'marketValue':
                        cap_str = item.get('value', '')
                        break

                # 시가총액 파싱 (예: "44조 2,545억", "523억")
                cap_억 = 0
                if '조' in cap_str:
                    parts = cap_str.replace(',','').split('조')
                    cap_억 = int(parts[0].strip()) * 10000
                    if '억' in parts[1]:
                        cap_억 += int(parts[1].replace('억','').strip())
                elif '억' in cap_str:
                    cap_억 = int(cap_str.replace(',','').replace('억','').strip())

                r['market_cap_억'] = cap_억
                r['market_cap_str'] = cap_str

                # 시가총액 500억 미만 제거
                if cap_억 > 0 and cap_억 < 500:
                    print(f"[필터] 소형주 제거: {name}({code}) 시총={cap_str}")
                    continue

                # 4. 거래 상태 확인 - 정상 거래 중인 종목만
                rjson = res.json()
                trade_stop = rjson.get('tradeStopType', {}).get('name', '')
                market_status = rjson.get('marketStatus', '')
                # TRADING 이 아닌 경우 (정지, 관리, 경고 등) 제거
                if trade_stop not in ['TRADING', '']:
                    print(f"[필터] 거래제한 종목 제거: {name}({code}) 상태={trade_stop}")
                    continue

                # 5. 거래정지 이력 확인 - 최근 60일 거래일수 체크
                try:
                    end_d = base_date if 'base_date' in dir() else prev_date
                    start_d = (datetime.strptime(prev_date, "%Y%m%d") - timedelta(days=90)).strftime("%Y%m%d")
                    df_check = stock.get_market_ohlcv_by_date(start_d, prev_date, code)
                    if df_check is not None and not df_check.empty:
                        df_check = df_check[df_check['거래량'] > 0]
                        trading_days = len(df_check)
                        # 90일 중 거래일이 40일 미만이면 거래정지 이력 있음
                        if trading_days < 40:
                            print(f"[필터] 거래정지 이력 제거: {name}({code}) 거래일={trading_days}일/90일")
                            continue
                        r['trading_days'] = trading_days
                except:
                    pass

        except Exception as e:
            r['market_cap_억'] = 0
            r['market_cap_str'] = 'N/A'

        filtered.append(r)

    filtered.sort(key=lambda x: x['change_pct'], reverse=True)
    print(f"[스캔 완료] 필터 후 {len(filtered)}개 (전체 상승: {len(unique)}개)")
    return filtered[:limit], prev_date

def calc_technical_score(code, base_date):
    """기술적 점수 계산 (RSI + MACD + 거래량)"""
    try:
        start = (datetime.strptime(base_date, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_date(start, base_date, code)
        if df is None or df.empty or len(df) < 20:
            return 50, {}

        df = df[df['거래량'] > 0]
        closes = list(df['종가'].astype(int))
        volumes = list(df['거래량'].astype(int))

        if len(closes) < 20:
            return 50, {}

        score = 50
        signals = {}

        # RSI
        n = 14
        if len(closes) > n:
            diffs = [closes[i+1]-closes[i] for i in range(len(closes)-1)]
            gains = [d for d in diffs[-n:] if d > 0]
            losses = [abs(d) for d in diffs[-n:] if d < 0]
            ag = sum(gains)/n if gains else 0
            al = sum(losses)/n if losses else 0.0001
            rsi = round(100 - 100/(1+ag/al), 1)
            signals['rsi'] = rsi
            if rsi < 30:
                score += 20
                signals['rsi_signal'] = '과매도(매수기회)'
            elif rsi < 50:
                score += 10
                signals['rsi_signal'] = '매수구간'
            elif rsi > 70:
                score -= 15
                signals['rsi_signal'] = '과매수(주의)'
            else:
                signals['rsi_signal'] = '중립'

        # MA 골든크로스
        if len(closes) >= 20:
            ma5 = sum(closes[-5:])/5
            ma20 = sum(closes[-20:])/20
            ma5_prev = sum(closes[-6:-1])/5
            ma20_prev = sum(closes[-21:-1])/20
            signals['ma5'] = round(ma5)
            signals['ma20'] = round(ma20)
            if ma5 > ma20 and ma5_prev <= ma20_prev:
                score += 25
                signals['ma_signal'] = '골든크로스 발생!'
            elif ma5 > ma20:
                score += 10
                signals['ma_signal'] = '단기 상승추세'
            elif ma5 < ma20 and ma5_prev >= ma20_prev:
                score -= 20
                signals['ma_signal'] = '데드크로스 발생'
            else:
                signals['ma_signal'] = '하락추세'

        # 거래량 급증
        if len(volumes) >= 20:
            avg_vol = sum(volumes[-20:-1]) / 19
            cur_vol = volumes[-1]
            vol_ratio = round(cur_vol / avg_vol, 1) if avg_vol > 0 else 1
            signals['vol_ratio'] = vol_ratio
            if vol_ratio >= 3:
                score += 20
                signals['vol_signal'] = f'거래량 급증 ({vol_ratio}배)'
            elif vol_ratio >= 2:
                score += 10
                signals['vol_signal'] = f'거래량 증가 ({vol_ratio}배)'
            else:
                signals['vol_signal'] = f'평균수준 ({vol_ratio}배)'

        return min(max(score, 0), 100), signals
    except Exception as e:
        return 50, {}

def get_ai_comment(stocks_data):
    """Claude API로 AI 종합 분석"""
    try:
        prompt = f"""당신은 한국 주식 단기매매 전문 애널리스트입니다.
아래는 전일 상승종목 TOP 데이터입니다. 각 종목의 신호를 분석해서 JSON으로만 응답하세요.

종목 데이터:
{str(stocks_data[:10])}

아래 JSON 형식으로만 응답 (백틱, 마크다운 없이):
{{
  "market_summary": "전체 시장 흐름 한줄 요약",
  "top_picks": [
    {{
      "code": "종목코드",
      "name": "종목명",
      "reason": "단기 매수 추천 이유 (2문장)",
      "risk": "주의사항"
    }}
  ],
  "caution": "오늘 단기매매 시 주의사항"
}}
top_picks는 최대 3개, 가장 매력적인 종목만 선별하세요."""

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        if response.status_code == 200:
            text = response.json()['content'][0]['text']
            text = re.sub(r'```json|```', '', text).strip()
            import json
            return json.loads(text)
    except Exception as e:
        print(f"[AI 오류] {e}")
    return None

# ── 라우트 ─────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('scanner.html')

@app.route('/api/scan')
def scan():
    try:
        print("\n[스캔 시작]")
        movers, base_date = get_top_movers(limit=100)
        if not movers:
            return jsonify({"error": "데이터를 불러올 수 없습니다."})

        # 기술적 점수 계산 (상위 30개만)
        scored = []
        for i, s in enumerate(movers[:30]):
            print(f"[점수계산] {i+1}/30 {s['name']}")
            tech_score, signals = calc_technical_score(s['code'], base_date)
            # 종합점수: 상승률(40%) + 기술점수(40%) + 거래량(20%)
            rise_score = min(s['change_pct'] * 5, 40)
            vol_score = min(signals.get('vol_ratio', 1) * 5, 20)
            total = round(rise_score + tech_score * 0.4 + vol_score)
            scored.append({
                **s,
                'tech_score': tech_score,
                'total_score': min(total, 100),
                'signals': signals,
            })

        # 종합점수 정렬
        scored.sort(key=lambda x: x['total_score'], reverse=True)

        # AI 분석
        ai_data = get_ai_comment(scored[:10])

        return jsonify({
            "success": True,
            "base_date": f"{base_date[:4]}-{base_date[4:6]}-{base_date[6:]}",
            "total_count": len(movers),
            "stocks": scored[:20],
            "ai": ai_data
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    print("=" * 50)
    print("  전일 상승종목 스캐너 시작!")
    print("  브라우저에서 http://localhost:5001 접속")
    print("  ※ 첫 스캔은 3~5분 소요됩니다")
    print("=" * 50)
    app.run(debug=True, port=5001)
