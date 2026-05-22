"""삼성증권 거래내역 xlsx 파서

양식 특징:
- xlsx 파일 (openpyxl로 읽기)
- 행 0: 계좌 정보 (메타)
- 행 1: 헤더
- 행 2부터: 데이터 (1행 = 1거래)

컬럼 (21개):
  거래일자, 거래명, 거래수량, 거래금액, 제세금/대출이자,
  현금잔액, 상대계좌명, 변제금액, 통화코드, 외화정산금액,
  거래번호, 종목명, 거래단가, 정산금액, 수수료/Fee,
  잔고수량/펀드평가금액, 상대계좌번호, 신용/대출금,
  외화거래금액, 외화예수금액, 처리점
"""
import pandas as pd
import warnings
warnings.filterwarnings('ignore')


# 거래명 → (거래구분, 통화 기본값, 시장, 카테고리)
NAME_MAP = {
    # 국내 매수/매도
    '매수': ('매수', 'KRW', 'KOSPI', 'trade'),
    '매도': ('매도', 'KRW', 'KOSPI', 'trade'),
    '매수_NXT': ('매수', 'KRW', 'KOSPI', 'trade'),
    '매도_NXT': ('매도', 'KRW', 'KOSPI', 'trade'),
    '코스닥매수': ('매수', 'KRW', 'KOSDAQ', 'trade'),
    '코스닥매도': ('매도', 'KRW', 'KOSDAQ', 'trade'),
    '거래소매수': ('매수', 'KRW', 'KOSPI', 'trade'),
    '거래소매도': ('매도', 'KRW', 'KOSPI', 'trade'),
    
    # 해외 매수/매도 (통화코드로 결정)
    '해외매수': ('매수', None, '해외', 'trade'),
    '해외매도': ('매도', None, '해외', 'trade'),
    '외화매수': ('환전매수', None, '-', 'fx'),
    '외화매도': ('환전매도', None, '-', 'fx'),
    
    # 배당/이자/분배금
    '배당금': ('배당', 'KRW', '국내', 'income'),
    'ETF분배금': ('분배금', 'KRW', '국내', 'income'),
    '예탁금이용료': ('이자', 'KRW', '국내', 'income'),
    '해외배당금': ('배당', None, '해외', 'income'),
    
    # 이체
    '이체입금': ('입금', 'KRW', '-', 'cash'),
    '이체출금': ('출금', 'KRW', '-', 'cash'),
}


def _to_num(v):
    """문자열·숫자 → float (콤마 처리)"""
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
    """다양한 날짜 → 'YYYY-MM-DD'"""
    if pd.isna(d):
        return ''
    if isinstance(d, str):
        return d.replace('/', '-').replace('.', '-').strip()
    if hasattr(d, 'strftime'):
        return d.strftime('%Y-%m-%d')
    return str(d)


def parse_samsung_xlsx(file_obj):
    """
    삼성증권 거래내역 xlsx → 통합 양식 거래 리스트
    
    Args:
        file_obj: Streamlit uploaded_file 또는 파일 경로
    
    Returns:
        list of dict: 통합 양식 거래 데이터
    """
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    
    df = pd.read_excel(file_obj, engine='openpyxl', header=None)
    
    # 헤더 행 찾기 (보통 행 1)
    header_row_idx = None
    for i in range(min(5, len(df))):
        row_vals = [str(v) for v in df.iloc[i].tolist() if pd.notna(v)]
        if '거래일자' in row_vals and '거래명' in row_vals:
            header_row_idx = i
            break
    
    if header_row_idx is None:
        raise ValueError("삼성증권 양식이 아닙니다. '거래일자' '거래명' 컬럼이 필요합니다.")
    
    # 컬럼 인덱스 매핑
    headers = df.iloc[header_row_idx].tolist()
    col_map = {}
    for i, h in enumerate(headers):
        h_str = str(h).strip()
        if h_str == '거래일자': col_map['date'] = i
        elif h_str == '거래명': col_map['name'] = i
        elif h_str == '거래수량': col_map['qty'] = i
        elif h_str == '거래금액': col_map['amount'] = i
        elif h_str == '제세금/대출이자': col_map['tax'] = i
        elif h_str == '통화코드': col_map['currency'] = i
        elif h_str == '외화정산금액': col_map['fx_settle'] = i
        elif h_str == '종목명': col_map['stock'] = i
        elif h_str == '거래단가': col_map['price'] = i
        elif h_str == '정산금액': col_map['settle'] = i
        elif h_str == '수수료/Fee': col_map['fee'] = i
        elif h_str == '외화거래금액': col_map['fx_amount'] = i
    
    parsed = []
    
    for i in range(header_row_idx + 1, len(df)):
        row = df.iloc[i]
        date_val = row.iloc[col_map.get('date', 0)]
        if pd.isna(date_val):
            continue
        
        name = str(row.iloc[col_map.get('name', 1)]).strip() if pd.notna(row.iloc[col_map.get('name', 1)]) else ''
        if not name or name == 'nan':
            continue
        
        # 거래명 매핑 (정확 일치 또는 키워드 포함)
        tx_info = NAME_MAP.get(name)
        if tx_info is None:
            # 키워드 포함 매칭
            for key, val in NAME_MAP.items():
                if key in name:
                    tx_info = val
                    break
        if tx_info is None:
            # 알 수 없는 거래는 스킵
            continue
        
        tx_type, default_currency, market, category = tx_info
        
        # 통화 결정: 통화코드 컬럼 > 종목명(USD/JPY/HKD) > 기본값
        currency_code = ''
        if 'currency' in col_map:
            cc = row.iloc[col_map['currency']]
            if pd.notna(cc) and str(cc).strip() not in ('nan', '0', ''):
                currency_code = str(cc).strip()
        
        stock_name = str(row.iloc[col_map.get('stock', 11)]).strip() if pd.notna(row.iloc[col_map.get('stock', 11)]) else ''
        if stock_name == 'nan': stock_name = ''
        
        if currency_code:
            currency = currency_code
        elif default_currency:
            currency = default_currency
        else:
            # 종목명에서 통화 추정
            if stock_name in ('USD', 'JPY', 'HKD', 'CNY', 'EUR'):
                currency = stock_name
            else:
                currency = 'KRW'
        
        # 수량/단가/금액
        qty = _to_num(row.iloc[col_map.get('qty', 2)])
        deal_amount = _to_num(row.iloc[col_map.get('amount', 3)])  # 원화
        price = _to_num(row.iloc[col_map.get('price', 12)])
        fee = _to_num(row.iloc[col_map.get('fee', 14)])
        tax = _to_num(row.iloc[col_map.get('tax', 4)])
        
        # 외화 거래는 외화 단위 정보
        fx_amount = _to_num(row.iloc[col_map.get('fx_amount', 18)]) if 'fx_amount' in col_map else 0
        
        # 환율 (외화매수/매도의 경우 단가가 환율)
        if category == 'fx':
            exchange_rate = price  # 외화매수의 단가는 환율
            # 외화매수 시 stock_name이 'USD' 등이면 종목명에서 제거
            if stock_name == currency:
                stock_name = ''
        else:
            exchange_rate = 1.0 if currency == 'KRW' else (price / fx_amount if fx_amount > 0 else 1.0)
        
        parsed.append({
            '거래일자': _format_date(date_val),
            '증권사': '삼성',
            '통화': currency,
            '시장': market,
            '거래구분': tx_type,
            '종목명': stock_name,
            '종목코드': '',  # 삼성증권은 종목코드 컬럼 없음
            '수량': qty,
            '단가': price,
            '거래금액': fx_amount if (category in ('trade', 'income') and currency != 'KRW') else deal_amount,
            '환율': exchange_rate,
            '원화환산금액': round(deal_amount, 2),
            '수수료(원)': round(fee, 2),
            '세금(원)': round(tax, 2),
            '비고': name,
        })
    
    return parsed
