"""보유 종목 (잔량 > 0) 추출 모듈"""
import pandas as pd
from collections import defaultdict


def get_current_holdings(trades, opening_balance=None):
    """
    거래 내역에서 현재 보유 중인 종목 추출
    
    Args:
        trades: list of dict (통합 거래 내역)
        opening_balance: list of dict (기초잔고, optional)
    
    Returns:
        DataFrame: 보유 종목 정보
    """
    # opening_balance 매칭용 인덱스
    opening_by_code = {}
    opening_by_name = {}
    if opening_balance:
        for ob in opening_balance:
            currency = ob.get('통화', 'KRW')
            code = ob.get('종목코드', '')
            name = ob.get('종목명', '')
            if code:
                opening_by_code[(currency, code)] = ob
            if name:
                opening_by_name[(currency, name)] = ob
    
    stocks = defaultdict(lambda: {
        '종목명': '', '종목코드': '', '통화': '', '증권사': '',
        '매수수량': 0.0,
        '매수금액_원통화': 0.0,
        '매수금액_원': 0.0,
        '매도수량': 0.0,
        '기초수량': 0.0,
        '기초금액': 0.0,
    })
    
    # 기초잔고를 stocks에 먼저 채우기
    if opening_balance:
        for ob in opening_balance:
            currency = ob.get('통화', 'KRW')
            code = ob.get('종목코드', '')
            name = ob.get('종목명', '')
            key = (currency, code or name)
            s = stocks[key]
            s['종목명'] = name
            s['종목코드'] = code
            s['통화'] = currency
            s['기초수량'] = ob.get('수량', 0)
            s['기초금액'] = ob.get('원화금액', 0) or (ob.get('수량', 0) * ob.get('평균단가', 0))
    
    for t in trades:
        if t['거래구분'] not in ('매수', '매도'):
            continue
        
        key = (t['통화'], t['종목코드'] or t['종목명'])
        s = stocks[key]
        
        if not s['종목명']:
            s['종목명'] = t['종목명']
            s['종목코드'] = t['종목코드']
            s['통화'] = t['통화']
            s['증권사'] = t['증권사']
            # 기초잔고 매칭 (종목코드 우선, 그 다음 종목명)
            ob = None
            if t['종목코드']:
                ob = opening_by_code.get((t['통화'], t['종목코드']))
            if ob is None and t['종목명']:
                ob = opening_by_name.get((t['통화'], t['종목명']))
            if ob:
                s['기초수량'] = ob.get('수량', 0)
                s['기초금액'] = ob.get('원화금액', 0) or (ob.get('수량', 0) * ob.get('평균단가', 0))
        elif not s['증권사']:
            s['증권사'] = t['증권사']
        
        if t['거래구분'] == '매수':
            s['매수수량'] += t['수량']
            s['매수금액_원통화'] += t['거래금액']
            s['매수금액_원'] += t['원화환산금액']
        else:  # 매도
            s['매도수량'] += t['수량']
    
    rows = []
    for key, s in stocks.items():
        # 보유수량 = 기초수량 + 매수수량 - 매도수량
        total_owned = s['기초수량'] + s['매수수량']
        remain_qty = total_owned - s['매도수량']
        # 작은 잔량 오차 (소수점 8자리 미만) 무시
        if abs(remain_qty) < 1e-8:
            continue
        if remain_qty <= 0:
            continue
        
        # 평균매수가 — 기초잔고 포함
        if total_owned > 0:
            total_cost_local = s['매수금액_원통화']  # 기초는 원화 기준만 추적
            total_cost_krw = s['매수금액_원'] + s['기초금액']
            avg_price_local = total_cost_local / s['매수수량'] if s['매수수량'] > 0 else 0
            avg_price_krw = total_cost_krw / total_owned
        else:
            avg_price_local = 0
            avg_price_krw = 0
        
        # 보유 원가 (남은 수량 × 평균단가)
        remain_cost_krw = remain_qty * avg_price_krw
        
        rows.append({
            '종목명': s['종목명'],
            '종목코드': s['종목코드'],
            '통화': s['통화'],
            '증권사': s['증권사'],
            '보유수량': remain_qty,
            '평균매수가(원통화)': avg_price_local,
            '평균매수가(원)': avg_price_krw,
            '매수원가(원)': remain_cost_krw,
        })
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('매수원가(원)', ascending=False).reset_index(drop=True)
    return df


def apply_current_prices(holdings_df, current_prices_dict, fx_rates=None):
    """
    보유 종목 + 사용자 입력 현재가 → 평가손익 계산
    
    Args:
        holdings_df: get_current_holdings 결과
        current_prices_dict: {(통화, 종목코드): 현재가(원통화)}
        fx_rates: {통화: 환율(원)} — USD→KRW 등
    
    Returns:
        DataFrame: 평가손익 포함
            - 현재가(원통화), 현재가(원), 평가금액(원), 평가손익(원), 수익률
    """
    if fx_rates is None:
        fx_rates = {'KRW': 1.0, 'USD': 1450.0, 'JPY': 9.5, 'HKD': 186.0, 'CNY': 200.0}
    
    if holdings_df.empty:
        return holdings_df
    
    df = holdings_df.copy()
    df['현재가(원통화)'] = 0.0
    df['평가금액(원)'] = 0.0
    df['평가손익(원)'] = 0.0
    df['수익률'] = 0.0
    df['입력여부'] = False
    
    for idx, row in df.iterrows():
        key = (row['통화'], row['종목코드'] or row['종목명'])
        if key in current_prices_dict and current_prices_dict[key] > 0:
            current_price = current_prices_dict[key]
            # JPY는 100엔당 환율
            if row['통화'] == 'JPY':
                current_krw = current_price * fx_rates.get('JPY', 9.5)
            else:
                current_krw = current_price * fx_rates.get(row['통화'], 1.0)
            
            eval_amount = row['보유수량'] * current_krw
            eval_pnl = eval_amount - row['매수원가(원)']
            return_rate = eval_pnl / row['매수원가(원)'] if row['매수원가(원)'] > 0 else 0
            
            df.at[idx, '현재가(원통화)'] = current_price
            df.at[idx, '평가금액(원)'] = eval_amount
            df.at[idx, '평가손익(원)'] = eval_pnl
            df.at[idx, '수익률'] = return_rate
            df.at[idx, '입력여부'] = True
    
    return df
