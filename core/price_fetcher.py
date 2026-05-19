"""현재가 자동 조회 모듈

지원 소스:
- pykrx: 한국주식·ETF (무료, 무인증)
- yfinance: 해외주식·ETF (무료, 무인증)

종목코드 매핑:
- 한국주식: 6자리 코드 그대로 사용 (예: 005930)
- 해외주식: ISIN → Yahoo 티커 변환 필요 (사용자 매핑 또는 자동 추정)
"""
import re
from datetime import datetime, timedelta


# ISIN → Yahoo 티커 매핑 (자주 거래되는 종목들 사전 등록)
# 키는 ISIN, 값은 Yahoo 티커
ISIN_TO_TICKER = {
    # 빅테크 (확실)
    'US67066G1040': 'NVDA',         # 엔비디아
    'US88160R1014': 'TSLA',         # 테슬라
    'US0378331005': 'AAPL',         # 애플
    'US5949181045': 'MSFT',         # 마이크로소프트
    'US02079K3059': 'GOOGL',        # 알파벳 A
    'US02079K1079': 'GOOG',         # 알파벳 C
    'US0231351067': 'AMZN',         # 아마존
    'US30303M1027': 'META',         # 메타
    'US64110L1061': 'NFLX',         # 넷플릭스
    
    # ETF (확실)
    'US9229083632': 'VOO',          # 뱅가드 S&P500
    'US78462F1030': 'SPY',          # SPDR S&P500
    'US46090E1038': 'QQQ',          # Invesco QQQ
    'US8085247976': 'SCHD',         # 슈왑 배당
    'US46434V6312': 'IWM',          # iShares Russell 2000
    'US9220428588': 'VTI',          # 뱅가드 토탈
    
    # 기타 미국 (확실)
    'US19260Q1076': 'COIN',         # 코인베이스
    'US3024913036': 'FCX',          # 프리포트
    'US98138H1014': 'WMT',          # 월마트
    
    # 사장님 PDF 종목들 (✅ = yfinance 확실, ⚠️ = 티커 추정)
    'US97785W1062': 'WOLF',         # ✅ 울프스피드
    'US23804L1035': 'DDOG',         # ✅ 데이터독
    'US7731211089': 'RKLB',         # ✅ 로켓 랩
    'US76029N1063': 'REPL',         # ✅ 레플리뮨 그룹
    'US72703X1063': 'PL',           # ✅ 플래닛 랩스
    'NL0009805522': 'NBIS',         # ✅ 네비우스 그룹 (네덜란드)
    'US34631F1021': 'FPTC',         # ⚠️ 포전트 파워 솔루션즈 (확인 필요)
    'IL0012384504': 'HUB',          # ⚠️ 허브 사이버 시큐리티
    
    # 레버리지 ETF (⚠️ 티커가 자주 변경되므로 사용자 확인 필요)
    'US38747R3637': 'CONI',         # ⚠️ 그래닛셰어즈 코인베이스 인버스 ETF
    'US46152A4528': 'NUKZ',         # ⚠️ Tradr 뉴스케일 2배 ETF
    'US46152A4940': 'IRNX',         # ⚠️ TRADR 아이렌 2배 ETF
    'US26923Q5642': 'MSTU',         # ⚠️ T-REX 비트마인
    'US46092D3843': 'TSDD',         # ⚠️ TRADR 테슬라 2배 인버스
    'US46092D6739': 'NBSX',         # ⚠️ TRADR 네비우스 그룹 2배 ETF
    'US25461H7961': 'ORCX',         # ⚠️ 디렉시온 데일리 오라클 불 2배 ETF
    'US88636J2612': 'LLYX',         # ⚠️ 디파이언스 일라이 릴리 2배 ETF
    'US88636R2224': 'RKLX',         # ⚠️ 디파이언스 로켓 랩 2배 ETF
}


# 종목명 키워드 → Yahoo 티커 (ISIN 매핑이 없을 때 fallback)
# 종목명에 키워드가 포함되면 해당 티커로 시도
NAME_TO_TICKER = {
    # 빅테크
    '엔비디아': 'NVDA',
    '테슬라': 'TSLA',
    '애플': 'AAPL',
    '마이크로소프트': 'MSFT',
    '알파벳': 'GOOGL',
    '구글': 'GOOGL',
    '아마존': 'AMZN',
    '메타': 'META',
    '넷플릭스': 'NFLX',
    '브로드컴': 'AVGO',
    'AMD': 'AMD',
    '인텔': 'INTC',
    '퀄컴': 'QCOM',
    
    # 사장님 종목 (종목명 매칭)
    '울프스피드': 'WOLF',
    '데이터독': 'DDOG',
    '로켓 랩': 'RKLB',
    '로켓랩': 'RKLB',
    '레플리뮨': 'REPL',
    '플래닛 랩스': 'PL',
    '플래닛랩스': 'PL',
    '네비우스 그룹': 'NBIS',
    '네비우스그룹': 'NBIS',
    '포전트 파워': 'FPTC',
    '포전트파워': 'FPTC',
    '허브 사이버': 'HUB',
    
    # 한국 ETF (해외 상장)
    '뱅가드': 'VOO',
    '슈왑': 'SCHD',
}


def isin_to_ticker(isin, stock_name='', user_mapping=None):
    """
    ISIN → Yahoo 티커 변환
    
    Args:
        isin: ISIN 코드 (예: US67066G1040)
        stock_name: 종목명 (보조 정보)
        user_mapping: 사용자 정의 매핑 dict
    
    Returns:
        str: Yahoo 티커 (예: NVDA) 또는 None
    """
    # 1. 사용자 매핑 우선 (가장 정확)
    if user_mapping and isin in user_mapping:
        return user_mapping[isin]
    
    # 2. 내장 ISIN 매핑
    if isin in ISIN_TO_TICKER:
        return ISIN_TO_TICKER[isin]
    
    # 3. 종목명에서 키워드 매칭 (fallback)
    if stock_name:
        name_lower = stock_name.lower().strip()
        for keyword, ticker in NAME_TO_TICKER.items():
            if keyword.lower() in name_lower:
                return ticker
    
    return None


def fetch_kr_price(code):
    """
    한국주식·ETF 현재가 조회 (pykrx)
    
    Args:
        code: 6자리 종목코드 (예: '005930')
    
    Returns:
        float or None: 종가 (원)
    """
    try:
        from pykrx import stock
    except ImportError:
        return None
    
    # 종목코드 정리 (6자리 숫자만)
    code = str(code).strip().zfill(6)
    if not re.match(r'^\d{6}$', code):
        return None
    
    try:
        # 최근 영업일 종가 (오늘이 휴장일일 수 있으니 5일 범위 조회)
        today = datetime.now()
        start = (today - timedelta(days=7)).strftime('%Y%m%d')
        end = today.strftime('%Y%m%d')
        
        df = stock.get_market_ohlcv_by_date(start, end, code)
        if df.empty:
            return None
        # 가장 최근 영업일 종가
        return float(df['종가'].iloc[-1])
    except Exception:
        return None


def fetch_overseas_price(ticker, currency='USD'):
    """
    해외주식·ETF 현재가 조회 (yfinance)
    
    Args:
        ticker: Yahoo 티커 (미국: NVDA, 일본: 6758.T, 홍콩: 0700.HK, 중국: 600519.SS)
        currency: 통화 (티커 접미사 자동 결정용, USD/JPY/HKD/CNY)
    
    Returns:
        float or None: 현재가 (해당 통화)
    """
    try:
        import yfinance as yf
    except ImportError:
        return None
    
    if not ticker:
        return None
    
    # 통화별 티커 접미사
    suffix_map = {'JPY': '.T', 'HKD': '.HK', 'CNY': '.SS'}
    if currency in suffix_map and not ticker.endswith(suffix_map[currency]):
        # 이미 접미사가 있으면 그대로, 아니면 추가
        ticker_full = ticker + suffix_map[currency]
    else:
        ticker_full = ticker
    
    try:
        t = yf.Ticker(ticker_full)
        # 가장 안정적인 방법: 1일 history
        hist = t.history(period='5d')
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
        # 폴백: info
        info = t.info
        for key in ('regularMarketPrice', 'currentPrice', 'previousClose'):
            if info.get(key):
                return float(info[key])
        return None
    except Exception:
        return None


def fetch_all_prices(holdings_df, user_mapping=None, progress_callback=None):
    """
    보유 종목 전체의 현재가 일괄 조회
    
    Args:
        holdings_df: get_current_holdings 결과 DataFrame
        user_mapping: 사용자 정의 ISIN→티커 매핑 dict
        progress_callback: 진행률 콜백 (idx, total, stock_name)
    
    Returns:
        dict: {(통화, 종목코드): 현재가}
        list: 조회 실패 종목 리스트 [{종목명, 종목코드, 통화, 이유}]
    """
    prices = {}
    failed = []
    
    total = len(holdings_df)
    for idx, row in holdings_df.iterrows():
        if progress_callback:
            progress_callback(idx, total, row['종목명'])
        
        code = row['종목코드']
        name = row['종목명']
        currency = row['통화']
        key = (currency, code or name)
        
        price = None
        
        if currency == 'KRW':
            # 한국주식: pykrx
            price = fetch_kr_price(code)
            if price is None:
                failed.append({
                    '종목명': name, '종목코드': code, '통화': currency,
                    '이유': 'pykrx 조회 실패 (휴장 또는 비상장)'
                })
        else:
            # 해외주식: ISIN → 티커 변환 → yfinance
            ticker = isin_to_ticker(code, name, user_mapping)
            if ticker:
                price = fetch_overseas_price(ticker, currency)
                if price is None:
                    failed.append({
                        '종목명': name, '종목코드': code, '통화': currency,
                        '이유': f'yfinance 조회 실패 (티커: {ticker})'
                    })
            else:
                failed.append({
                    '종목명': name, '종목코드': code, '통화': currency,
                    '이유': f'ISIN→티커 매핑 없음 (수동 매핑 필요)'
                })
        
        if price is not None and price > 0:
            prices[key] = price
    
    return prices, failed
