"""IBK(산업)증권 거래내역 xls/xlsx 파서

양식:
- xls 또는 xlsx 파일
- 시트: '편집' 또는 'Sheet1' (둘 다 동일 데이터)
- 행 0: 헤더 (16 컬럼)
- 컬럼: 결제일자, 거래종류, 거래수량, 거래금액, 거래수수료, 연체료,
        주식대출상환, 유가잔고, 거래번호, 종목명, 거래단가, 정산금액,
        제세금합, 이자/이용료, 매도대출상환, 예수금잔고

거래종류 키워드:
- 보통매수, KOSDAQ보통매수 → 매수
- 보통매도, KOSDAQ보통매도 → 매도
- 결산분배금입금 → 분배금
- 예탁금이용료입금 → 이자
- 무상주입고, 무상단주대금입금 → 정보 (스킵)
- 은행연계입금/출금 → 입출금 (스킵)
"""
import pandas as pd
import warnings
warnings.filterwarnings('ignore')


# 거래종류 → (거래구분, 통화, 시장, 카테고리)
TYPE_MAP = {
    # 국내 매수/매도
    '보통매수': ('매수', 'KRW', 'KOSPI', 'trade'),
    '보통매도': ('매도', 'KRW', 'KOSPI', 'trade'),
    'KOSDAQ보통매수': ('매수', 'KRW', 'KOSDAQ', 'trade'),
    'KOSDAQ보통매도': ('매도', 'KRW', 'KOSDAQ', 'trade'),
    '코스닥보통매수': ('매수', 'KRW', 'KOSDAQ', 'trade'),
    '코스닥보통매도': ('매도', 'KRW', 'KOSDAQ', 'trade'),
    
    # 해외 (추정 — 양식 받으면 보완)
    '해외매수': ('매수', None, '해외', 'trade'),
    '해외매도': ('매도', None, '해외', 'trade'),
    '외화매수': ('환전매수', None, '-', 'fx'),
    '외화매도': ('환전매도', None, '-', 'fx'),
    
    # 배당/이자/분배금
    '배당금입금': ('배당', 'KRW', '국내', 'income'),
    '결산분배금입금': ('분배금', 'KRW', '국내', 'income'),
    '예탁금이용료입금': ('이자', 'KRW', '국내', 'income'),
}

# 스킵 (이체/무상주 등)
SKIP_TYPES = {
    '은행연계출금',
    '은행연계입금',
    '무상주입고',
    '무상단주대금입금',
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
        # "2024-01-15 00:00:00" → "2024-01-15"
        return d.split(' ')[0].replace('/', '-').replace('.', '-').strip()
    if hasattr(d, 'strftime'):
        return d.strftime('%Y-%m-%d')
    return str(d)


def _read_excel_auto(file_obj):
    """xls/xlsx 자동 인식. xls는 xlrd → 실패 시 openpyxl(이미 xlsx로 변환된 경우)"""
    # openpyxl 우선 시도 (xlsx)
    try:
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        return pd.read_excel(file_obj, engine='openpyxl', sheet_name=None, header=None)
    except Exception:
        pass
    
    # xlrd로 fallback (xls)
    try:
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        return pd.read_excel(file_obj, engine='xlrd', sheet_name=None, header=None)
    except Exception as e:
        raise ValueError(f"엑셀 파일 읽기 실패: {e}")


def parse_ibk_xls(file_obj):
    """
    IBK(산업)증권 거래내역 xls/xlsx → 통합 양식 거래 리스트
    
    Args:
        file_obj: Streamlit uploaded_file 또는 파일 경로
    
    Returns:
        list of dict: 통합 양식 거래 데이터
    """
    sheets = _read_excel_auto(file_obj)
    
    # 시트 우선순위: '편집' > 'Sheet1' > 첫 시트
    df = None
    if '편집' in sheets:
        df = sheets['편집']
    elif 'Sheet1' in sheets:
        df = sheets['Sheet1']
    else:
        df = list(sheets.values())[0]
    
    # 헤더 행 찾기 (보통 행 0)
    header_row_idx = None
    for i in range(min(5, len(df))):
        row_vals = [str(v) for v in df.iloc[i].tolist() if pd.notna(v)]
        if '결제일자' in row_vals and '거래종류' in row_vals:
            header_row_idx = i
            break
    
    if header_row_idx is None:
        raise ValueError("IBK증권 양식이 아닙니다. '결제일자' '거래종류' 컬럼이 필요합니다.")
    
    # 컬럼 인덱스 매핑
    headers = df.iloc[header_row_idx].tolist()
    col_map = {}
    for i, h in enumerate(headers):
        h_str = str(h).strip()
        if h_str == '결제일자': col_map['date'] = i
        elif h_str == '거래종류': col_map['type'] = i
        elif h_str == '거래수량': col_map['qty'] = i
        elif h_str == '거래금액': col_map['amount'] = i
        elif h_str == '거래수수료': col_map['fee'] = i
        elif h_str == '종목명': col_map['stock'] = i
        elif h_str == '거래단가': col_map['price'] = i
        elif h_str == '정산금액': col_map['settle'] = i
        elif h_str == '제세금합': col_map['tax'] = i
    
    parsed = []
    
    for i in range(header_row_idx + 1, len(df)):
        row = df.iloc[i]
        
        date_val = row.iloc[col_map.get('date', 0)]
        if pd.isna(date_val):
            continue
        
        tx_type_raw = str(row.iloc[col_map.get('type', 1)]).strip() if pd.notna(row.iloc[col_map.get('type', 1)]) else ''
        if not tx_type_raw or tx_type_raw == 'nan':
            continue
        
        # 스킵
        if tx_type_raw in SKIP_TYPES:
            continue
        
        # 매핑 (정확 일치 우선, 그 다음 키워드 포함)
        tx_info = TYPE_MAP.get(tx_type_raw)
        if tx_info is None:
            for key, val in TYPE_MAP.items():
                if key in tx_type_raw:
                    tx_info = val
                    break
        if tx_info is None:
            continue
        
        action, default_currency, market, category = tx_info
        currency = default_currency or 'KRW'
        
        stock_name = str(row.iloc[col_map.get('stock', 9)]).strip() if pd.notna(row.iloc[col_map.get('stock', 9)]) else ''
        if stock_name == 'nan':
            stock_name = ''
        
        qty = _to_num(row.iloc[col_map.get('qty', 2)])
        deal_amount = _to_num(row.iloc[col_map.get('amount', 3)])
        price = _to_num(row.iloc[col_map.get('price', 10)])
        fee = _to_num(row.iloc[col_map.get('fee', 4)])
        tax = _to_num(row.iloc[col_map.get('tax', 12)])
        
        parsed.append({
            '거래일자': _format_date(date_val),
            '증권사': 'IBK',
            '통화': currency,
            '시장': market,
            '거래구분': action,
            '종목명': stock_name,
            '종목코드': '',
            '수량': qty,
            '단가': price,
            '거래금액': deal_amount,
            '환율': 1.0,
            '원화환산금액': round(deal_amount, 2),
            '수수료(원)': round(fee, 2),
            '세금(원)': round(tax, 2),
            '비고': tx_type_raw,
        })
    
    return parsed
