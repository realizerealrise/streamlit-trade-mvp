"""한국투자증권(KIS) 거래내역 xls 파서

한투 양식 특징:
- BIFF8 진짜 xls 형식 (xlrd 필요) 또는 xlsx 변환본
- 거래 1건이 여러 행: 거래일 있는 메인 행 + 부속 행 (수수료/세금/환율 등)
- 거래항목 컬럼에 "수량 * 단가 = 금액" 패턴
- 다국적 외화: USD, JPY, HKD, CNY 모두 지원
"""
import pandas as pd
import re
import warnings
warnings.filterwarnings('ignore')


# 적요 → (거래구분, 통화, 시장, 카테고리)
ADVICE_MAP = {
    # 해외 매수/매도
    '해외증권매수 USD': ('매수', 'USD', '해외', 'trade'),
    '해외증권매도 USD': ('매도', 'USD', '해외', 'trade'),
    '해외증권매수 JPY': ('매수', 'JPY', '해외', 'trade'),
    '해외증권매도 JPY': ('매도', 'JPY', '해외', 'trade'),
    '해외증권매수 HKD': ('매수', 'HKD', '해외', 'trade'),
    '해외증권매도 HKD': ('매도', 'HKD', '해외', 'trade'),
    '해외증권매수 CNY': ('매수', 'CNY', '해외', 'trade'),
    '해외증권매도 CNY': ('매도', 'CNY', '해외', 'trade'),
    # 국내 매수/매도
    'Smart+거래소주식매수': ('매수', 'KRW', 'KOSPI', 'trade'),
    'Smart+거래소주식매도': ('매도', 'KRW', 'KOSPI', 'trade'),
    'Smart+코스닥주식매수': ('매수', 'KRW', 'KOSDAQ', 'trade'),
    'Smart+코스닥주식매도': ('매도', 'KRW', 'KOSDAQ', 'trade'),
    'Smart+외화실시간직접매도환전 HKD': ('환전', 'HKD', '-', 'fx'),
    # 배당/분배금/이자
    'ETF분배금입금': ('분배금', 'KRW', '국내', 'income'),
    '해외증권배당금입금 USD': ('배당', 'USD', '해외', 'income'),
    '해외증권배당금입금 JPY': ('배당', 'JPY', '해외', 'income'),
    '해외증권배당금입금 HKD': ('배당', 'HKD', '해외', 'income'),
    '예탁금이용료': ('이자', 'KRW', '국내', 'income'),
    '외화예탁금이용료입금 USD': ('이자', 'USD', '해외', 'income'),
    '외화예탁금이용료원화세금': ('세금', 'KRW', '-', 'tax'),
    # 환전 (현금 흐름)
    '자동환전(외화매수) USD': ('환전매수', 'USD', '-', 'fx'),
    '자동환전(외화매도) USD': ('환전매도', 'USD', '-', 'fx'),
    '자동환전(외화매수) JPY': ('환전매수', 'JPY', '-', 'fx'),
    '자동환전(외화매도) JPY': ('환전매도', 'JPY', '-', 'fx'),
    '자동환전(외화매수) HKD': ('환전매수', 'HKD', '-', 'fx'),
    '자동환전(외화매도) HKD': ('환전매도', 'HKD', '-', 'fx'),
    '자동이종환전(외화매수) USD': ('환전매수', 'USD', '-', 'fx'),
    '자동이종환전(외화매도) USD': ('환전매도', 'USD', '-', 'fx'),
    '자동이종환전(외화매수) JPY': ('환전매수', 'JPY', '-', 'fx'),
    '자동이종환전(외화매도) JPY': ('환전매도', 'JPY', '-', 'fx'),
    '자동이종환전(외화매수) HKD': ('환전매수', 'HKD', '-', 'fx'),
    '자동이종환전(외화매도) HKD': ('환전매도', 'HKD', '-', 'fx'),
    '자동이종환전(외화매수) CNY': ('환전매수', 'CNY', '-', 'fx'),
    '자동이종환전(외화매도) CNY': ('환전매도', 'CNY', '-', 'fx'),
    # 기타
    'DR FEE 출금 USD': ('수수료', 'USD', '-', 'fee'),
    'Smart+타사이체출금': ('출금', 'KRW', '-', 'cash'),
}

# 거래항목 컬럼 패턴: "수량 * 단가 = 금액"
QTY_PRICE_PATTERN = re.compile(r'^([\d,.]+)\s*\*\s*([\d,.]+)\s*=\s*([\d,.]+)')


def _to_num(v):
    """다양한 형식의 숫자 문자열을 float로"""
    if pd.isna(v):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(',', '').strip().rstrip('.')
    if not s or s == 'nan':
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _load_kis_dataframe(file_obj):
    """한투 xls 파일을 DataFrame으로 (xlrd, openpyxl, libreoffice 변환 fallback)"""
    # 시도 1: xlrd (진짜 xls)
    try:
        return pd.read_excel(file_obj, engine='xlrd', header=0)
    except Exception:
        pass
    
    # 시도 2: openpyxl (xlsx면)
    try:
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        return pd.read_excel(file_obj, engine='openpyxl', header=0)
    except Exception:
        pass
    
    # 시도 3: HTML 형식인 경우 (일부 한투 양식)
    try:
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
        dfs = pd.read_html(file_obj, encoding='euc-kr')
        return dfs[0]
    except Exception as e:
        raise ValueError(
            f"한투 파일을 읽을 수 없습니다. xls를 Excel에서 한 번 열고 xlsx로 다시 저장 후 시도해주세요. ({e})"
        )


def _format_date(d):
    """다양한 날짜 형식을 'YYYY-MM-DD'로"""
    if pd.isna(d):
        return ''
    if isinstance(d, str):
        return d.replace('/', '-').replace('.', '-').strip()
    if hasattr(d, 'strftime'):
        return d.strftime('%Y-%m-%d')
    return str(d)


def parse_kis_xls(file_obj):
    """
    한투 거래내역 xls → 통합 양식 거래 리스트
    
    Args:
        file_obj: Streamlit uploaded_file 또는 파일 경로
    
    Returns:
        list of dict: 통합 양식 거래 데이터
    """
    df = _load_kis_dataframe(file_obj)
    
    # 컬럼명 정규화 (한투는 거래일, 순번, 적요, 종목(잔고)번호, 거래항목, 입출금고, ...)
    cols = list(df.columns)
    # 필요한 컬럼 인덱스 찾기
    col_map = {}
    for i, c in enumerate(cols):
        c_str = str(c).strip()
        if '거래일' in c_str: col_map['date'] = i
        elif '적요' in c_str: col_map['advice'] = i
        elif '종목' in c_str and '번호' in c_str: col_map['code'] = i
        elif '거래항목' in c_str: col_map['item'] = i
        elif '입출금고' in c_str: col_map['amount'] = i
    
    if 'date' not in col_map or 'advice' not in col_map:
        raise ValueError("한투 양식이 아닙니다. '거래일', '적요' 컬럼이 필요합니다.")
    
    # 거래 단위로 그룹핑 (거래일 있는 행 = 새 거래 시작)
    parsed = []
    i = 0
    n = len(df)
    
    while i < n:
        row = df.iloc[i]
        date_val = row.iloc[col_map['date']]
        
        # 거래 시작 행 찾기 (날짜 있음 + 적요 있음)
        if pd.isna(date_val):
            i += 1
            continue
        
        advice = str(row.iloc[col_map['advice']]).strip() if pd.notna(row.iloc[col_map['advice']]) else ''
        if not advice or advice == 'nan':
            i += 1
            continue
        
        # 거래 종류 분류
        if advice not in ADVICE_MAP:
            # 알 수 없는 적요는 스킵 (필요시 로깅)
            i += 1
            continue
        
        tx_type, currency, market, category = ADVICE_MAP[advice]
        
        # 메인 행 정보
        code = str(row.iloc[col_map['code']]).strip() if pd.notna(row.iloc[col_map['code']]) else ''
        if code == 'nan': code = ''
        item = str(row.iloc[col_map['item']]).strip() if pd.notna(row.iloc[col_map['item']]) else ''
        if item == 'nan': item = ''
        amount = _to_num(row.iloc[col_map['amount']])
        
        # 거래항목에서 수량/단가/금액 파싱
        qty, price, deal_amount = 0.0, 0.0, 0.0
        stock_name = item
        
        if category == 'trade':
            # "수량 * 단가 = 금액" 패턴
            m = QTY_PRICE_PATTERN.match(item)
            if m:
                qty = _to_num(m.group(1))
                price = _to_num(m.group(2))
                deal_amount = _to_num(m.group(3))
                stock_name = ''  # 다음에 부속 행에서 종목명 찾을 수도 있음
            else:
                # 입출금고 컬럼에서 "수량 * 단가 = 금액"이 있을 수도
                amount_str = str(row.iloc[col_map['amount']])
                m = QTY_PRICE_PATTERN.match(amount_str)
                if m:
                    qty = _to_num(m.group(1))
                    price = _to_num(m.group(2))
                    deal_amount = _to_num(m.group(3))
                    stock_name = item
                else:
                    # 종목명은 거래항목, 금액은 그냥 amount
                    stock_name = item
                    deal_amount = amount
        elif category in ('income', 'fee', 'tax', 'fx', 'cash'):
            # 배당/이자/환전 등: 입출금고 컬럼이 금액
            deal_amount = amount
            stock_name = item if item and item != '외화금액' and item != '외화거래금액' else ''
        
        # 종목명 정리 (해외 종목은 거래항목에 "[코드]종목명" 형태)
        if stock_name.startswith('[') and ']' in stock_name:
            stock_name = stock_name.split(']', 1)[1].strip()
        
        # 부속 행 수집 (다음 거래일 행 전까지)
        sub_data = {}
        j = i + 1
        while j < n:
            sub_row = df.iloc[j]
            if pd.notna(sub_row.iloc[col_map['date']]):
                break
            sub_item = str(sub_row.iloc[col_map['item']]).strip() if pd.notna(sub_row.iloc[col_map['item']]) else ''
            sub_amount = _to_num(sub_row.iloc[col_map['amount']])
            if sub_item and sub_item != 'nan':
                sub_data[sub_item] = sub_amount
            j += 1
        
        # 부속 행에서 환율, 수수료, 세금 추출
        exchange_rate = sub_data.get('환율', 1.0 if currency == 'KRW' else 0.0)
        fee_local = sub_data.get('수수료', 0)
        
        # 세금 항목들 합산
        tax_keys = ['거래세', '거래농특세', '현지세금', '법인세', '지방소득세']
        tax_total = sum(sub_data.get(k, 0) for k in tax_keys)
        
        # 환율이 0이면 원화 환산 불가 → 1로 (KRW 거래)
        if exchange_rate == 0:
            exchange_rate = 1.0
        
        # 원화 환산 금액
        if currency == 'KRW':
            krw_amount = deal_amount
            fee_krw = fee_local
            tax_krw = tax_total
        elif currency == 'JPY':
            # JPY는 한투에서 100엔당 환율로 표시됨
            krw_amount = deal_amount * exchange_rate / 100
            fee_krw = fee_local * exchange_rate / 100
            tax_krw = tax_total * exchange_rate / 100
        else:
            krw_amount = deal_amount * exchange_rate
            fee_krw = fee_local * exchange_rate
            tax_krw = tax_total * exchange_rate
        
        # 환전 거래의 경우 원화거래금액 직접 사용
        if category == 'fx':
            if '원화거래금액' in sub_data:
                krw_amount = sub_data['원화거래금액']
        
        parsed.append({
            '거래일자': _format_date(date_val),
            '증권사': '한투',
            '통화': currency,
            '시장': market,
            '거래구분': tx_type,
            '종목명': stock_name,
            '종목코드': code,
            '수량': qty,
            '단가': price,
            '거래금액': deal_amount,
            '환율': exchange_rate,
            '원화환산금액': round(krw_amount, 2),
            '수수료(원)': round(fee_krw, 2),
            '세금(원)': round(tax_krw, 2),
            '비고': advice,
        })
        
        i = j  # 다음 거래로
    
    return parsed
