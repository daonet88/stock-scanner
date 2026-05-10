from flask import Flask, render_template, request, jsonify
from pykrx import stock
from datetime import datetime, timedelta

app = Flask(__name__)

STOCK_DICT = {
    '삼성전자': '005930', 'SK하이닉스': '000660', 'LG에너지솔루션': '373220',
    '삼성바이오로직스': '207940', '현대차': '005380', '기아': '000270',
    'NAVER': '035420', '네이버': '035420', '카카오': '035720',
    '셀트리온': '068270', 'KB금융': '105560', '신한지주': '055550',
    '하나금융지주': '086790', '삼성물산': '028260', 'LG화학': '051910',
    'SK이노베이션': '096770', '포스코홀딩스': '005490', '현대모비스': '012330',
    'SK텔레콤': '017670', 'KT': '030200', 'LG전자': '066570',
    '삼성SDI': '006400', '한국전력': '015760', '크래프톤': '259960',
    '엔씨소프트': '036570', '에코프로비엠': '247540', '에코프로': '086520',
    '고려아연': '010130', 'HD현대중공업': '329180', '삼성중공업': '010140',
    '한화에어로스페이스': '012450', '대한항공': '003490', 'HMM': '011200',
    '카카오뱅크': '323410', '카카오페이': '377300', '넷마블': '251270',
}

def get_stock_code(query):
    query = query.strip()
    if query.isdigit() and len(query) == 6:
        return query
    if query in STOCK_DICT:
        return STOCK_DICT[query]
    try:
        tickers = stock.get_market_ticker_list(market="ALL")
        for ticker in tickers:
            try:
                if stock.get_market_ticker_name(ticker) == query:
                    return ticker
            except:
                continue
    except:
        pass
    return None

def find_latest_trading_date():
    """최근 영업일 탐색 - ohlcv만 사용 (안정적)"""
    for days_back in range(0, 10):
        d = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
        try:
            df = stock.get_market_ohlcv(d, d, "005930")
            if df is not None and not df.empty and int(df.iloc[0].get('거래량', 0)) > 0:
                return d
        except:
            continue
    return (datetime.now() - timedelta(days=3)).strftime("%Y%m%d")

def get_ohlcv_range(code, days=60):
    """안전한 OHLCV 범위 조회 - _by_date 사용하지만 ohlcv는 안정적"""
    end   = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    try:
        df = stock.get_market_ohlcv_by_date(start, end, code)
        if df is not None and not df.empty and '거래량' in df.columns:
            return df[df['거래량'] > 0]
    except:
        pass
    return None

def get_naver_data(code):
    """네이버 모바일 integration API로 실시간 데이터 가져오기"""
    import requests as req
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    per = pbr = div_yield = 0.0
    foreign_net = inst_net = 0
    market_cap_str = "N/A"
    foreign_pct = 0.0

    try:
        # integration API - PER/PBR/시가총액/외인/배당 모두 포함
        r = req.get(f'https://m.stock.naver.com/api/stock/{code}/integration', headers=headers, timeout=10)
        if r.status_code == 200:
            d = r.json()
            infos = d.get('totalInfos', [])
            for item in infos:
                c = item.get('code', '')
                v = str(item.get('value', '')).strip()
                # 숫자만 추출하는 헬퍼
                def to_float(s):
                    import re
                    m = re.search(r"[\d.]+", s.replace(',',''))
                    return float(m.group()) if m else 0.0
                if c == 'marketValue':
                    market_cap_str = v
                elif c == 'per':
                    per = round(to_float(v), 2)
                elif c == 'pbr':
                    pbr = round(to_float(v), 2)
                elif c == 'dividendYieldRatio':
                    div_yield = round(to_float(v), 2)
                elif c == 'foreignRate':
                    foreign_pct = v
            print(f"[네이버 OK] 시총={market_cap_str} PER={per} PBR={pbr} 배당={div_yield}%")
    except Exception as e:
        print(f"[네이버 integration 오류] {e}")

    return per, pbr, div_yield, market_cap_str, foreign_net, inst_net

def get_fundamental_safe(code, latest_date):
    return (0.0, 0.0, 0.0)  # 사용 안 함 - get_naver_data로 대체

def get_cap_safe(code):
    return "N/A"  # 사용 안 함 - get_naver_data로 대체

def get_supply_safe(code):
    return 0, 0  # 사용 안 함 - get_naver_data로 대체

def get_stock_info(code):
    name = stock.get_market_ticker_name(code)
    latest_date = find_latest_trading_date()
    print(f"[날짜] 최근 영업일: {latest_date}")

    # ── 현재가 ──
    df60 = get_ohlcv_range(code, 60)
    if df60 is None or df60.empty:
        return None
    row      = df60.iloc[-1]
    prev_row = df60.iloc[-2] if len(df60) >= 2 else row
    current_price = int(row['종가'])
    prev_price    = int(prev_row['종가'])
    change        = current_price - prev_price
    change_pct    = round(change / prev_price * 100, 2) if prev_price else 0

    # ── 52주 ──
    df400 = get_ohlcv_range(code, 400)
    if df400 is not None and not df400.empty:
        high_52 = int(df400['고가'].max())
        low_52  = int(df400['저가'].min())
        pos_52  = round((current_price - low_52) / (high_52 - low_52) * 100, 1) if high_52 != low_52 else 50
    else:
        high_52, low_52, pos_52 = current_price, current_price, 50

    # ── 펀더멘털 / 시가총액 / 수급 (네이버 모바일 API) ──
    per, pbr, div_yield, market_cap_str, foreign_net, inst_net = get_naver_data(code)

    return dict(
        name=name, code=code,
        current_price=current_price, change=change, change_pct=change_pct,
        volume=int(row['거래량']), high=int(row['고가']),
        low=int(row['저가']), open=int(row['시가']),
        high_52=high_52, low_52=low_52, pos_52=pos_52,
        per=per, pbr=pbr, div_yield=div_yield,
        foreign_net=foreign_net, inst_net=inst_net,
        market_cap=market_cap_str,
        latest_date=f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}",
    )

def get_chart_data(code, period=90):
    df = get_ohlcv_range(code, period + 60)
    if df is None or df.empty:
        return []
    df = df.reset_index()
    date_col = df.columns[0]
    result = []
    for _, r in df.iterrows():
        try:
            result.append({
                "date":   str(r[date_col])[:10],
                "open":   int(r['시가']),  "high": int(r['고가']),
                "low":    int(r['저가']),  "close": int(r['종가']),
                "volume": int(r['거래량']),
            })
        except:
            continue
    return result[-period:] if len(result) > period else result

def calc_indicators(data):
    if not data:
        return {}
    closes = [d['close'] for d in data]
    dates  = [d['date']  for d in data]
    def ma(n):
        return [None if i < n-1 else round(sum(closes[i-n+1:i+1])/n) for i in range(len(closes))]
    def rsi(n=14):
        if len(closes) <= n:
            return [None]*len(closes)
        out = [None]*n
        for i in range(n, len(closes)):
            diffs = [closes[j+1]-closes[j] for j in range(i-n, i)]
            g = sum(d for d in diffs if d > 0)/n
            l = sum(abs(d) for d in diffs if d < 0)/n or 0.0001
            out.append(round(100 - 100/(1+g/l), 1))
        return out
    def ema(n):
        k = 2/(n+1); e = [closes[0]]
        for c in closes[1:]: e.append(c*k + e[-1]*(1-k))
        return e
    e12, e26 = ema(12), ema(26)
    macd = [round(a-b) for a,b in zip(e12,e26)]
    k = 2/10; sig = [macd[0]]
    for v in macd[1:]: sig.append(round(v*k+sig[-1]*(1-k)))
    return dict(dates=dates, ma5=ma(5), ma20=ma(20), ma60=ma(60), ma120=ma(120),
                rsi=rsi(), macd=macd, signal=sig,
                histogram=[round(m-s) for m,s in zip(macd,sig)])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search')
def search():
    query = request.args.get('q','').strip()
    if not query:
        return jsonify({"error": "종목명을 입력하세요"})
    try:
        print(f"\n[검색] {query}")
        code = get_stock_code(query)
        if not code:
            return jsonify({"error": f"'{query}' 종목을 찾을 수 없습니다.\n정확한 종목명 또는 6자리 코드를 입력하세요."})
        print(f"[코드] {code}")
        info = get_stock_info(code)
        if not info:
            return jsonify({"error": "데이터를 불러올 수 없습니다."})
        print(f"[완료] {info['name']} {info['current_price']:,}원")
        return jsonify({"success": True, "info": info})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"오류: {str(e)}"})

@app.route('/api/chart')
def chart():
    code   = request.args.get('code','')
    period = int(request.args.get('period', 90))
    try:
        data = get_chart_data(code, period)
        if not data:
            return jsonify({"error": "차트 데이터가 없습니다."})
        return jsonify({"success": True, "data": data, "indicators": calc_indicators(data)})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    print("=" * 50)
    print("  키움증권 종목 평가 웹앱 시작!")
    print("  브라우저에서 http://localhost:5000 접속")
    print("=" * 50)
    app.run(debug=True, port=5000)
