"""종목별 손익 및 양도세 계산"""
import pandas as pd
from collections import defaultdict


def calculate_stock_pnl(trades, opening_balance=None):
    """
    종목별 손익 계산 (평균단가법)
    
    Args:
        trades: list of dict (통합 양식)
        opening_balance: list of dict (기초잔고, optional)
            [{'종목코드': ..., '통화': ..., '수량': ..., '평균단가': ..., '원화금액': ...}, ...]
    
    Returns:
        DataFrame: 종목별 손익 현황
    """
    opening_map = {}
    if opening_balance:
        for ob in opening_balance:
            key = (ob['통화'], ob['종목코드'])
            opening_map[key] = ob
    
    # 종목별 집계
    stocks = defaultdict(lambda: {
        '종목명': '', '종목코드': '', '통화': '', '증권사': '',
        '기초수량': 0, '기초단가': 0, '기초금액': 0,
        '매수횟수': 0, '매수수량': 0, '매수금액_원통화': 0, '매수금액_원화': 0, '매수수수료': 0,
        '매도횟수': 0, '매도수량': 0, '매도금액_원통화': 0, '매도금액_원화': 0, '매도부대비용': 0,
    })
    
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
            # 기초잔고 매칭
            if key in opening_map:
                ob = opening_map[key]
                s['기초수량'] = ob.get('수량', 0)
                s['기초단가'] = ob.get('평균단가', 0)
                s['기초금액'] = ob.get('원화금액', 0)
        
        if t['거래구분'] == '매수':
            s['매수횟수'] += 1
            s['매수수량'] += t['수량']
            s['매수금액_원통화'] += t['거래금액']
            s['매수금액_원화'] += t['원화환산금액']
            s['매수수수료'] += t['수수료(원)']
        else:  # 매도
            s['매도횟수'] += 1
            s['매도수량'] += t['수량']
            s['매도금액_원통화'] += t['거래금액']
            s['매도금액_원화'] += t['원화환산금액']
            s['매도부대비용'] += t['수수료(원)'] + t['세금(원)']
    
    rows = []
    for key, s in stocks.items():
        # 평균매수단가 (기초 + 매수)
        total_qty = s['기초수량'] + s['매수수량']
        if total_qty > 0:
            avg_price_local = (s['기초수량'] * s['기초단가'] + s['매수금액_원통화']) / total_qty
            avg_price_krw = (s['기초금액'] + s['매수금액_원화']) / total_qty
        else:
            avg_price_local = 0
            avg_price_krw = 0
        
        # 매도원가 (KRW)
        cost_of_sale = s['매도수량'] * avg_price_krw
        # 처분손익 = 매도금액(원화) - 매도원가 - 부대비용
        realized_pnl = s['매도금액_원화'] - cost_of_sale - s['매도부대비용']
        
        # 잔고
        remain_qty = s['기초수량'] + s['매수수량'] - s['매도수량']
        remain_cost = remain_qty * avg_price_krw
        
        rows.append({
            '종목명': s['종목명'],
            '종목코드': s['종목코드'],
            '통화': s['통화'],
            '증권사': s['증권사'],
            '기초수량': s['기초수량'],
            '매수횟수': s['매수횟수'],
            '매수수량': s['매수수량'],
            '총매수(원통화)': s['매수금액_원통화'],
            '총매수(원)': s['매수금액_원화'],
            '평균매수단가(원통화)': avg_price_local,
            '평균매수단가(원)': avg_price_krw,
            '매도횟수': s['매도횟수'],
            '매도수량': s['매도수량'],
            '총매도(원통화)': s['매도금액_원통화'],
            '총매도(원)': s['매도금액_원화'],
            '매도원가(원)': cost_of_sale,
            '매도부대비용(원)': s['매도부대비용'],
            '처분손익(원)': realized_pnl,
            '처분이익(+)': realized_pnl if realized_pnl > 0 else 0,
            '처분손실(-)': realized_pnl if realized_pnl < 0 else 0,
            '잔고수량': remain_qty,
            '잔고원가(원)': remain_cost,
        })
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('처분손익(원)', ascending=False).reset_index(drop=True)
    return df


def calculate_dividend(trades):
    """배당·이자·분배금 집계"""
    div_trades = [t for t in trades if t['거래구분'] in ('배당', '분배금', '이자')]
    
    by_type = defaultdict(float)
    for t in div_trades:
        by_type[t['거래구분']] += t['거래금액']
    
    return {
        '배당금': by_type.get('배당', 0),
        '분배금': by_type.get('분배금', 0),
        '이자': by_type.get('이자', 0),
        '합계': sum(by_type.values()),
        '상세': div_trades,
    }


def calculate_tax(pnl_df, user_type='개인', loss_carryforward=0):
    """
    양도소득세 정산
    
    Args:
        pnl_df: calculate_stock_pnl 결과 DataFrame
        user_type: '개인' 또는 '사업자'
        loss_carryforward: 이월결손금 (사업자만)
    
    Returns:
        dict: 양도세 정산 결과
    """
    if pnl_df.empty:
        return {
            '처분이익': 0, '처분손실': 0, '순처분손익': 0,
            '기본공제': 0, '이월결손금차감': 0, '과세표준': 0,
            '예상세액': 0, '세율_설명': '',
        }
    
    profit = pnl_df['처분이익(+)'].sum()
    loss = pnl_df['처분손실(-)'].sum()
    net = profit + loss
    
    if user_type == '개인':
        basic_deduction = min(2_500_000, max(net, 0))
        loss_offset = 0
        tax_rate = 0.22
        rate_desc = '22% (양도세 20% + 지방세 2%)'
    else:  # 사업자
        basic_deduction = 0
        loss_offset = min(loss_carryforward, max(net, 0) * 0.8) if net > 0 else 0
        tax_rate = None  # 법인세는 별도 산정
        rate_desc = '법인세율 (별도 산정)'
    
    taxable = max(net - basic_deduction - loss_offset, 0)
    estimated_tax = round(taxable * tax_rate) if tax_rate else None
    
    return {
        '처분이익': profit,
        '처분손실': loss,
        '순처분손익': net,
        '기본공제': basic_deduction,
        '이월결손금차감': loss_offset,
        '과세표준': taxable,
        '예상세액': estimated_tax,
        '세율_설명': rate_desc,
    }


def get_monthly_trends(trades):
    """월별 매수·매도·배당 추이"""
    monthly = defaultdict(lambda: {'매수': 0, '매도': 0, '배당이자': 0})
    for t in trades:
        try:
            month = t['거래일자'][:7]  # YYYY-MM
            if t['거래구분'] == '매수':
                monthly[month]['매수'] += t['원화환산금액']
            elif t['거래구분'] == '매도':
                monthly[month]['매도'] += t['원화환산금액']
            elif t['거래구분'] in ('배당', '분배금', '이자'):
                monthly[month]['배당이자'] += t['거래금액']
        except (KeyError, IndexError):
            continue
    
    return dict(sorted(monthly.items()))


def get_allocation(pnl_df):
    """자산 배분 (증권사별, 통화별, 시장별)"""
    if pnl_df.empty:
        return {'by_broker': {}, 'by_currency': {}}
    
    total_buy = pnl_df['총매수(원)'].sum()
    if total_buy == 0:
        return {'by_broker': {}, 'by_currency': {}}
    
    by_broker = pnl_df.groupby('증권사')['총매수(원)'].sum().to_dict()
    by_currency = pnl_df.groupby('통화')['총매수(원)'].sum().to_dict()
    
    return {
        'by_broker': {k: v / total_buy for k, v in by_broker.items()},
        'by_currency': {k: v / total_buy for k, v in by_currency.items()},
        'totals': {'broker': by_broker, 'currency': by_currency, 'total': total_buy},
    }
