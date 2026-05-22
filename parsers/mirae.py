"""미래에셋증권 거래내역 CSV 파서

양식:
- CSV 파일 (cp949 인코딩 일반)
- 행 0: 헤더 (26 컬럼)
- 컬럼: 거래일자, 거래번호, 원번호, 거래종류, 종목명, 수량, 단가, (빈),
        거래금액, 입출금액, 예수금, 유가잔고, 수수료, 제세금합,
        외화거래금액, 외화입출금액, 외화예수금, 외화유가증권,
        미수발생금액, 미수변제금액, 통화코드, ...

거래종류 키워드:
- 주식매수입고 → 매수
- 주식매도출고 → 매도
- 주식매수출금, 주식매도입금 → 결제 행 (스킵 - 중복)
- 배당금입금 → 배당
- 예탁금이용료입금 → 이자
- 무상주입고, 무상단수주대금입금 → 정보 (스킵)
- 은행이체대체송금, 이체출고 → 입출금 (스킵)
"""
import pandas as pd
import warnings
warnings.filterwarnings('ignore')


# 거래종류 → (거래구분, 통화 기본값, 시장, 카테고리)
TYPE_MAP = {
    # 매수/매도 (체결)
    '주식매수입고': ('매수', 'KRW', 'KOSPI', 'trade'),
    '주식매도출고': ('매도', 'KRW', 'KOSPI', 'trade'),
    '코스닥매수입고': ('매수', 'KRW', 'KOSDAQ', 'trade'),
    '코스닥매도출고': ('매도', 'KRW', 'KOSDAQ', 'trade'),
    
    # 해외주식 (추정)
    '해외주식매수': ('매수', None, '해외', 'trade'),
    '해외주식매도': ('매도', None, '해외', 'trade'),
    '외화매수': ('환전매수', None, '-', 'fx'),
    '외화매도': ('환전매도', None, '-', 'fx'),
    
    # 배당/이자/분배금
    '배당금입금': ('배당', 'KRW', '국내', 'income'),
    '해외배당금입금': ('배당', None, '해외', 'income'),
    '예탁금이용료입금': ('이자', 'KRW', '국내', 'income'),
    'ETF분배금입금': ('분배금', 'KRW', '국내', 'income'),
    '분배금입금': ('분배금', 'KRW', '국내', 'income'),
}

# 스킵할 거래종류 (결제·이체·무상주 등 — 손익 계산에 불필요)
SKIP_TYPES = {
    '주식매수출금',     # 매수 결제 (매수입고와 중복)
    '주식매도입금',     # 매도 결제 (매도출고와 중복)
    '은행이체대체송금',  # 단순 이체
    '이체출고',         # 단순 이체
    '이체입고',
    '무상주입고',       # 무상주
    '무상단수주대금입금', # 무상주 단수 정산
}


def _to_num(v):
    if pd.isna(v):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(',', '').strip()
    if not s or s == 'nan' or s == '-':
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _format_date(d):
    if pd.isna(d):
        return ''
    if isinstance(d, str):
        return d.replace('/', '-').replace('.', '-').strip()
    if hasattr(d, 'strftime'):
        return d.strftime('%Y-%m-%d')
    return str(d)


def _read_csv_auto(file_obj):
    """인코딩 자동 감지 (cp949/utf-8/euc-kr 순서)"""
    if hasattr(file_obj, 'seek'):
        # Streamlit uploaded_file
        encodings = ['cp949', 'euc-kr', 'utf-8-sig', 'utf-8']
        last_err = None
        for enc in encodings:
            try:
                file_obj.seek(0)
                return pd.read_csv(file_obj, encoding=enc)
            except (UnicodeDecodeError, UnicodeError) as e:
                last_err = e
                continue
        raise ValueError(f"인코딩 인식 실패: {last_err}")
    else:
        # 파일 경로
        for enc in ['cp949', 'euc-kr', 'utf-8-sig', 'utf-8']:
            try:
                return pd.read_csv(file_obj, encoding=enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        raise ValueError("인코딩 인식 실패")


def parse_mirae_csv(file_obj):
    """
    미래에셋증권 거래내역 CSV → 통합 양식 거래 리스트
    
    Args:
        file_obj: Streamlit uploaded_file 또는 파일 경로
    
    Returns:
        list of dict: 통합 양식 거래 데이터
    """
    df = _read_csv_auto(file_obj)
    
    # 필요 컬럼 검증
    required = ['거래일자', '거래종류', '종목명', '수량', '단가', '거래금액', '수수료', '제세금합']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"미래에셋 양식이 아닙니다. 누락 컬럼: {missing}")
    
    parsed = []
    
    for _, row in df.iterrows():
        date_val = row['거래일자']
        if pd.isna(date_val):
            continue
        
        tx_type_raw = str(row['거래종류']).strip()
        if not tx_type_raw or tx_type_raw == 'nan':
            continue
        
        # 스킵할 거래
        if tx_type_raw in SKIP_TYPES:
            continue
        
        # 거래종류 매핑
        tx_info = TYPE_MAP.get(tx_type_raw)
        if tx_info is None:
            # 키워드 부분 매칭 (예: "코스닥매수입고", "해외주식매수출금" 등)
            for key, val in TYPE_MAP.items():
                if key in tx_type_raw or tx_type_raw in key:
                    tx_info = val
                    break
        if tx_info is None:
            # 알 수 없는 거래는 스킵 (조용히)
            continue
        
        action, default_currency, market, category = tx_info
        
        # 통화 결정
        currency_code = ''
        if '통화코드' in df.columns:
            cc = row.get('통화코드')
            if pd.notna(cc) and str(cc).strip() not in ('nan', '0', ''):
                currency_code = str(cc).strip()
        
        currency = currency_code if currency_code else (default_currency or 'KRW')
        
        stock_name = str(row['종목명']).strip() if pd.notna(row['종목명']) else ''
        if stock_name == 'nan':
            stock_name = ''
        
        qty = _to_num(row['수량'])
        price = _to_num(row['단가'])
        deal_amount = _to_num(row['거래금액'])  # 원화 거래금액
        fee = _to_num(row.get('수수료', 0))
        tax = _to_num(row.get('제세금합', 0))
        
        # 외화 거래인 경우
        fx_amount = _to_num(row.get('외화거래금액', 0)) if '외화거래금액' in df.columns else 0
        
        # 환율 (외화금액이 있으면 추정)
        if fx_amount > 0 and currency != 'KRW':
            exchange_rate = deal_amount / fx_amount if fx_amount > 0 else 1.0
            external_amount = fx_amount
        else:
            exchange_rate = 1.0
            external_amount = deal_amount
        
        parsed.append({
            '거래일자': _format_date(date_val),
            '증권사': '미래에셋',
            '통화': currency,
            '시장': market,
            '거래구분': action,
            '종목명': stock_name,
            '종목코드': '',  # 미래에셋은 종목코드 컬럼 없음
            '수량': qty,
            '단가': price,
            '거래금액': external_amount,
            '환율': exchange_rate,
            '원화환산금액': round(deal_amount, 2),
            '수수료(원)': round(fee, 2),
            '세금(원)': round(tax, 2),
            '비고': tx_type_raw,
        })
    
    return parsed
