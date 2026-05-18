"""나무증권(NH투자증권) xls (HTML 형식) 파서"""
import pandas as pd
import re

# 상세내용 → 통합 거래구분 매핑
DETAIL_MAP = {
    '코스피매수': ('매수', 'KRW', 'KOSPI'),
    '코스피매도': ('매도', 'KRW', 'KOSPI'),
    'KOSDAQ매수': ('매수', 'KRW', 'KOSDAQ'),
    'KOSDAQ매도': ('매도', 'KRW', 'KOSDAQ'),
    '배당금': ('배당', 'KRW', '국내'),
    'ETF분배금입금': ('분배금', 'KRW', '국내'),
    '예탁금이용료': ('이자', 'KRW', '국내'),
    '이체입금': ('입금', 'KRW', '-'),
    '이체출금': ('출금', 'KRW', '-'),
    '대체입금': ('입금', 'KRW', '-'),
    '공모주입고': ('입고', 'KRW', 'KOSPI'),
    '공모주청약수수료출금': ('출금', 'KRW', '-'),
    '공모주환불금': ('입금', 'KRW', '-'),
    '공모청약출금': ('출금', 'KRW', '-'),
}


def parse_nh_xls(file_obj):
    """
    나무증권 거래내역서 xls (HTML 형식) → 통합 양식 거래 리스트
    
    Args:
        file_obj: Streamlit uploaded_file 또는 파일 경로
    
    Returns:
        list of dict: 통합 양식 거래 데이터
    """
    dfs = pd.read_html(file_obj, encoding='euc-kr')
    df = dfs[0]
    df.columns = ['c0', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7', 'c8', 'c9', 'c10', 'c11', 'c12']
    df = df.iloc[2:].reset_index(drop=True)
    
    # 2행씩 묶기 (한 거래)
    parsed = []
    for i in range(0, len(df), 2):
        if i + 1 >= len(df):
            break
        r1, r2 = df.iloc[i], df.iloc[i + 1]
        
        # 종목명 / 종목코드 분리
        full_name = str(r1['c3']) if pd.notna(r1['c3']) else ''
        m = re.match(r'(.+?)\s+([A-Z0-9]{6})\s*$', full_name)
        if m:
            stock_name = m.group(1).strip()
            stock_code = m.group(2).strip()
        else:
            stock_name = full_name.strip() if full_name != 'nan' else ''
            stock_code = ''
        
        def to_num(v):
            try:
                return float(v) if pd.notna(v) and str(v).strip() != '' else 0
            except (ValueError, TypeError):
                return 0
        
        detail = str(r1['c2']) if pd.notna(r1['c2']) else ''
        if detail in DETAIL_MAP:
            tx_type, currency, market = DETAIL_MAP[detail]
        else:
            tx_type, currency, market = '기타', 'KRW', '-'
        
        is_income = tx_type in ('배당', '분배금', '이자')
        
        parsed.append({
            '거래일자': str(r1['c0']).replace('.', '-') if pd.notna(r1['c0']) else '',
            '증권사': '나무',
            '통화': currency,
            '시장': market,
            '거래구분': tx_type,
            '종목명': stock_name,
            '종목코드': stock_code,
            '수량': to_num(r1['c4']) if not is_income else 0,
            '단가': to_num(r2['c4']) if not is_income else 0,
            '거래금액': to_num(r1['c5']),
            '환율': 1,
            '원화환산금액': to_num(r1['c5']),
            '수수료(원)': to_num(r1['c8']),
            '세금(원)': to_num(r2['c8']),
            '비고': detail,
        })
    
    return parsed
