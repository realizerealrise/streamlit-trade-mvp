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
    # opening_balance 매칭용 인덱스 만들기 (종목코드 키 + 종목명 키 둘 다)
    opening_by_code = {}  # (통화, 종목코드) → ob
    opening_by_name = {}  # (통화, 종목명) → ob
    if opening_balance:
        for ob in opening_balance:
            currency = ob.get('통화', 'KRW')
            code = ob.get('종목코드', '')
            name = ob.get('종목명', '')
            if code:
                opening_by_code[(currency, code)] = ob
            if name:
                opening_by_name[(currency, name)] = ob
    
    # 종목별 집계
    stocks = defaultdict(lambda: {
        '종목명': '', '종목코드': '', '통화': '', '증권사': '',
        '기초수량': 0, '기초단가': 0, '기초금액': 0,
        '매수횟수': 0, '매수수량': 0, '매수금액_원통화': 0, '매수금액_원화': 0, '매수수수료': 0, '매수세금': 0,
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
            # 기초잔고 매칭 (종목코드 우선, 그 다음 종목명)
            ob = None
            if t['종목코드']:
                ob = opening_by_code.get((t['통화'], t['종목코드']))
            if ob is None and t['종목명']:
                ob = opening_by_name.get((t['통화'], t['종목명']))
            if ob:
                s['기초수량'] = ob.get('수량', 0)
                s['기초단가'] = ob.get('평균단가', 0)
                s['기초금액'] = ob.get('원화금액', 0) or (ob.get('수량', 0) * ob.get('평균단가', 0))
        
        if t['거래구분'] == '매수':
            s['매수횟수'] += 1
            s['매수수량'] += t['수량']
            s['매수금액_원통화'] += t['거래금액']
            s['매수금액_원화'] += t['원화환산금액']
            s['매수수수료'] += t['수수료(원)']
            s['매수세금'] += t['세금(원)']
        else:  # 매도
            s['매도횟수'] += 1
            s['매도수량'] += t['수량']
            s['매도금액_원통화'] += t['거래금액']
            s['매도금액_원화'] += t['원화환산금액']
            s['매도부대비용'] += t['수수료(원)'] + t['세금(원)']
    
    rows = []
    for key, s in stocks.items():
        # 평균매수단가 (기초 + 매수)
        # 세무상 매수원가 = 매수금액 + 매수부대비용 (수수료+세금)
        total_qty = s['기초수량'] + s['매수수량']
        매수부대비용 = s['매수수수료'] + s['매수세금']
        if total_qty > 0:
            avg_price_local = (s['기초수량'] * s['기초단가'] + s['매수금액_원통화']) / total_qty
            # 매수 부대비용을 매수원가에 포함 (세무상 정확한 계산)
            avg_price_krw = (s['기초금액'] + s['매수금액_원화'] + 매수부대비용) / total_qty
        else:
            avg_price_local = 0
            avg_price_krw = 0
        
        # 매도원가 (KRW) — 부대비용이 평균단가에 이미 포함됨
        cost_of_sale = s['매도수량'] * avg_price_krw
        # 처분손익 = 매도금액(원화) - 매도원가 - 매도부대비용
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


def calculate_stock_pnl_moving_avg(trades, opening_balance=None):
    """
    종목별 손익 계산 (이동평균법)
    
    매수가 발생할 때마다 평균단가를 재계산하는 방식.
    매도 시점의 평균단가를 사용하여 처분손익을 산정.
    
    국세청 양도세 신고 시 선택 가능한 방법 중 하나.
    
    Args:
        trades: list of dict (통합 양식)
        opening_balance: list of dict (기초잔고, optional)
    
    Returns:
        DataFrame: 종목별 손익 현황 (총평균법과 동일 컬럼 구조)
    """
    # opening_balance 매칭용 인덱스 (종목코드 + 종목명)
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
    
    # 종목별로 시간순 처리 — 매수 시 평균단가 갱신, 매도 시 평균단가로 손익 산정
    # 1단계: 거래를 시간순 정렬
    sorted_trades = sorted(
        [t for t in trades if t['거래구분'] in ('매수', '매도')],
        key=lambda t: t.get('거래일자', '')
    )
    
    # 2단계: 종목별 상태 추적 (실시간 갱신)
    stocks = defaultdict(lambda: {
        '종목명': '', '종목코드': '', '통화': '', '증권사': '',
        '보유수량': 0,
        '평균단가_원화': 0,
        '매수횟수': 0,
        '매수수량': 0, '매수금액_원화': 0, '매수부대비용': 0,
        '매도횟수': 0,
        '매도수량': 0, '매도금액_원화': 0, '매도부대비용': 0,
        '처분이익': 0, '처분손실': 0, '처분손익': 0,
    })
    
    for t in sorted_trades:
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
                s['보유수량'] = ob.get('수량', 0)
                s['평균단가_원화'] = ob.get('평균단가', 0) if ob.get('수량', 0) > 0 else 0
        
        fee = float(t.get('수수료(원)', 0) or 0)
        tax = float(t.get('세금(원)', 0) or 0)
        부대비용 = fee + tax
        
        if t['거래구분'] == '매수':
            # 이동평균 갱신: 신규 평균 = (기존 보유원가 + 신규 매수원가 + 매수부대비용) / 총수량
            old_qty = s['보유수량']
            old_value = old_qty * s['평균단가_원화']
            new_qty = t['수량']
            new_value = t['원화환산금액'] + 부대비용  # 매수 부대비용 포함
            
            total_qty = old_qty + new_qty
            if total_qty > 0:
                s['평균단가_원화'] = (old_value + new_value) / total_qty
            s['보유수량'] = total_qty
            
            s['매수횟수'] += 1
            s['매수수량'] += new_qty
            s['매수금액_원화'] += t['원화환산금액']
            s['매수부대비용'] += 부대비용
        
        else:  # 매도
            # 매도 시점의 평균단가 사용하여 처분손익 산정
            sell_qty = t['수량']
            sell_amount = t['원화환산금액']
            cost_of_sale = sell_qty * s['평균단가_원화']
            pnl = sell_amount - cost_of_sale - 부대비용
            
            s['보유수량'] -= sell_qty
            # 보유수량이 0 이하가 되면 평균단가 리셋
            if s['보유수량'] <= 0:
                s['평균단가_원화'] = 0
                s['보유수량'] = 0
            
            s['매도횟수'] += 1
            s['매도수량'] += sell_qty
            s['매도금액_원화'] += sell_amount
            s['매도부대비용'] += 부대비용
            s['처분손익'] += pnl
            if pnl > 0:
                s['처분이익'] += pnl
            else:
                s['처분손실'] += pnl
    
    # DataFrame으로 변환 (총평균법 결과와 동일 컬럼 구조)
    rows = []
    for key, s in stocks.items():
        rows.append({
            '종목명': s['종목명'],
            '종목코드': s['종목코드'],
            '통화': s['통화'],
            '증권사': s['증권사'],
            '기초수량': 0,
            '매수횟수': s['매수횟수'],
            '매수수량': s['매수수량'],
            '총매수(원통화)': 0,
            '총매수(원)': s['매수금액_원화'],
            '평균매수단가(원통화)': 0,
            '평균매수단가(원)': s['평균단가_원화'] if s['보유수량'] > 0 else 0,
            '매도횟수': s['매도횟수'],
            '매도수량': s['매도수량'],
            '총매도(원통화)': 0,
            '총매도(원)': s['매도금액_원화'],
            '매도원가(원)': s['매도금액_원화'] - s['매도부대비용'] - s['처분손익'],
            '매도부대비용(원)': s['매도부대비용'],
            '처분손익(원)': s['처분손익'],
            '처분이익(+)': s['처분이익'],
            '처분손실(-)': s['처분손실'],
            '잔고수량': s['보유수량'],
            '잔고원가(원)': s['보유수량'] * s['평균단가_원화'],
        })
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('처분손익(원)', ascending=False).reset_index(drop=True)
    return df


def calculate_stock_pnl_fifo(trades, opening_balance=None):
    """
    종목별 손익 계산 (선입선출법 FIFO)
    
    먼저 매수한 주식을 먼저 매도하는 방식.
    소득세법 시행령 제162조 제5항에 따른 원칙적 계산 방법.
    국세청은 원칙적으로 FIFO를 적용하되, 증권사가 이동평균법을 제공하는 경우 그 방법도 허용.
    
    Args:
        trades: list of dict (통합 양식)
        opening_balance: list of dict (기초잔고, optional)
    
    Returns:
        DataFrame: 종목별 손익 현황
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
    
    # 시간순 정렬
    sorted_trades = sorted(
        [t for t in trades if t['거래구분'] in ('매수', '매도')],
        key=lambda t: t.get('거래일자', '')
    )
    
    # 종목별 인벤토리 (FIFO 큐)
    # inventory[(통화, 키)] = [(수량, 1주당원화원가), ...]
    inventories = defaultdict(list)
    
    # 종목별 집계
    stocks = defaultdict(lambda: {
        '종목명': '', '종목코드': '', '통화': '', '증권사': '',
        '기초수량': 0, '기초금액': 0,
        '매수횟수': 0, '매수수량': 0, '매수금액_원화': 0, '매수부대비용': 0,
        '매도횟수': 0, '매도수량': 0, '매도금액_원화': 0, '매도부대비용': 0,
        '처분이익': 0, '처분손실': 0, '처분손익': 0,
        '매도원가_합': 0,
    })
    
    for t in sorted_trades:
        key = (t['통화'], t['종목코드'] or t['종목명'])
        s = stocks[key]
        if not s['종목명']:
            s['종목명'] = t['종목명']
            s['종목코드'] = t['종목코드']
            s['통화'] = t['통화']
            s['증권사'] = t['증권사']
            # 기초잔고 매칭 → 인벤토리에 추가
            ob = None
            if t['종목코드']:
                ob = opening_by_code.get((t['통화'], t['종목코드']))
            if ob is None and t['종목명']:
                ob = opening_by_name.get((t['통화'], t['종목명']))
            if ob and ob.get('수량', 0) > 0:
                avg_price = ob.get('평균단가', 0)
                if avg_price > 0:
                    inventories[key].append([ob['수량'], avg_price])
                    s['기초수량'] = ob['수량']
                    s['기초금액'] = ob['수량'] * avg_price
        
        fee = float(t.get('수수료(원)', 0) or 0)
        tax = float(t.get('세금(원)', 0) or 0)
        부대비용 = fee + tax
        qty = t['수량']
        amount_krw = t['원화환산금액']
        
        if t['거래구분'] == '매수':
            # 1주당 원가 = (거래금액 + 부대비용) / 수량
            unit_cost = (amount_krw + 부대비용) / qty if qty > 0 else 0
            inventories[key].append([qty, unit_cost])
            s['매수횟수'] += 1
            s['매수수량'] += qty
            s['매수금액_원화'] += amount_krw
            s['매수부대비용'] += 부대비용
        else:  # 매도
            # FIFO로 매도 수량만큼 인벤토리에서 꺼내기
            cost_of_sale = 0
            remaining = qty
            inv = inventories[key]
            while remaining > 0 and inv:
                avail_qty, avail_cost = inv[0]
                if avail_qty <= remaining:
                    cost_of_sale += avail_qty * avail_cost
                    remaining -= avail_qty
                    inv.pop(0)
                else:
                    cost_of_sale += remaining * avail_cost
                    inv[0][0] -= remaining
                    remaining = 0
            
            # 인벤토리 부족분은 0 처리 (전기 이월 누락 케이스)
            pnl = amount_krw - cost_of_sale - 부대비용
            s['매도횟수'] += 1
            s['매도수량'] += qty
            s['매도금액_원화'] += amount_krw
            s['매도부대비용'] += 부대비용
            s['처분손익'] += pnl
            s['매도원가_합'] += cost_of_sale
            if pnl > 0:
                s['처분이익'] += pnl
            else:
                s['처분손실'] += pnl
    
    # 결과 변환
    rows = []
    for key, s in stocks.items():
        # 잔고
        inv = inventories[key]
        remain_qty = sum(q for q, c in inv)
        remain_cost = sum(q * c for q, c in inv)
        avg_price_remain = (remain_cost / remain_qty) if remain_qty > 0 else 0
        
        rows.append({
            '종목명': s['종목명'],
            '종목코드': s['종목코드'],
            '통화': s['통화'],
            '증권사': s['증권사'],
            '기초수량': s['기초수량'],
            '매수횟수': s['매수횟수'],
            '매수수량': s['매수수량'],
            '총매수(원통화)': 0,
            '총매수(원)': s['매수금액_원화'],
            '평균매수단가(원통화)': 0,
            '평균매수단가(원)': avg_price_remain if remain_qty > 0 else 0,
            '매도횟수': s['매도횟수'],
            '매도수량': s['매도수량'],
            '총매도(원통화)': 0,
            '총매도(원)': s['매도금액_원화'],
            '매도원가(원)': s['매도원가_합'],
            '매도부대비용(원)': s['매도부대비용'],
            '처분손익(원)': s['처분손익'],
            '처분이익(+)': s['처분이익'],
            '처분손실(-)': s['처분손실'],
            '잔고수량': remain_qty,
            '잔고원가(원)': remain_cost,
        })
    
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('처분손익(원)', ascending=False).reset_index(drop=True)
    return df


# ─────────────────────────────────────────
# 증권사별 양도세 계산 방법 매핑
# 출처: 2025-12-23 대한경제 기사 + 시사저널e 2025-01-30
# ─────────────────────────────────────────
BROKER_METHOD_MAP = {
    # 선입선출법 (FIFO) 사용 증권사
    'KB증권': 'FIFO',
    '미래에셋증권': 'FIFO',
    '미래에셋': 'FIFO',
    '키움증권': 'FIFO',
    '하나증권': 'FIFO',
    '신한투자증권': 'FIFO',
    '메리츠증권': 'FIFO',
    '카카오페이증권': 'FIFO',
    
    # 이동평균법 사용 증권사
    '한국투자증권': '이동평균법',
    '한투': '이동평균법',
    'KIS': '이동평균법',
    '토스증권': '이동평균법',
    '토스': '이동평균법',
    '삼성증권': '이동평균법',
    '삼성': '이동평균법',
    '대신증권': '이동평균법',
    'SK증권': '이동평균법',
    
    # 둘 다 선택 가능
    'NH투자증권': '선택가능',
    'NH': '선택가능',
    '나무': '선택가능',
    '나무증권': '선택가능',
    
    # IBK는 자료 부족 — 일단 분류 안 함
}


def get_broker_method(broker_name):
    """증권사명 → 양도세 계산 방법 반환"""
    if not broker_name:
        return None
    # 정확 일치
    if broker_name in BROKER_METHOD_MAP:
        return BROKER_METHOD_MAP[broker_name]
    # 부분 일치 (긴 이름 우선)
    for key in sorted(BROKER_METHOD_MAP.keys(), key=len, reverse=True):
        if key in broker_name or broker_name in key:
            return BROKER_METHOD_MAP[key]
    return None


def compare_tax_methods(trades, user_type='개인', loss_carryforward=0, opening_balance=None):
    """
    세 가지 양도세 계산법 비교 (FIFO vs 이동평균법 vs 총평균법)
    
    국세청 인정 방법:
    - 선입선출법(FIFO): 소득세법 시행령 제162조 제5항 원칙
    - 이동평균법: 증권사가 제공하는 경우 사용 가능 (2022년 국세청 유권해석)
    - 총평균법: 학술적/참고용 (실무 신고 X)
    
    Args:
        trades: 거래 리스트
        user_type: '개인' or '사업자'
        loss_carryforward: 이월결손금
        opening_balance: 기초잔고 리스트 (optional)
    
    Returns:
        dict: 세 방법 비교 + 추천 + 절세효과 + 증권사별 권장 방법
    """
    # FIFO (원칙)
    pnl_fifo = calculate_stock_pnl_fifo(trades, opening_balance=opening_balance)
    tax_fifo = calculate_tax(pnl_fifo, user_type, loss_carryforward)
    
    # 이동평균법
    pnl_moving = calculate_stock_pnl_moving_avg(trades, opening_balance=opening_balance)
    tax_moving = calculate_tax(pnl_moving, user_type, loss_carryforward)
    
    # 총평균법 (참고)
    pnl_avg = calculate_stock_pnl(trades, opening_balance=opening_balance)
    tax_avg = calculate_tax(pnl_avg, user_type, loss_carryforward)
    
    # FIFO vs 이동평균법 — 국세청 인정 2가지만 비교
    tax_f = tax_fifo.get('예상세액') or 0
    tax_m = tax_moving.get('예상세액') or 0
    
    if tax_f <= tax_m:
        recommended = '선입선출법'
        saving = tax_m - tax_f
    else:
        recommended = '이동평균법'
        saving = tax_f - tax_m
    
    # 사용된 증권사 + 권장 방법 정리
    brokers_in_data = set()
    for t in trades:
        if t.get('증권사'):
            brokers_in_data.add(t['증권사'])
    
    broker_methods = []
    for b in sorted(brokers_in_data):
        method = get_broker_method(b)
        broker_methods.append({
            '증권사': b,
            '권장방법': method or '확인 필요',
        })
    
    return {
        '선입선출법': {
            'pnl_df': pnl_fifo,
            'tax_info': tax_fifo,
            '방법명': '선입선출법 (FIFO)',
            '설명': '먼저 매수한 주식을 먼저 매도. 국세청 원칙적 방법. KB·미래에셋·키움·하나·신한·메리츠증권 채택.',
        },
        '이동평균법': {
            'pnl_df': pnl_moving,
            'tax_info': tax_moving,
            '방법명': '이동평균법',
            '설명': '매수 시점마다 평균단가 갱신. 한국투자·토스·삼성·대신·SK증권 채택. NH증권은 두 가지 선택 가능.',
        },
        '총평균법': {
            'pnl_df': pnl_avg,
            'tax_info': tax_avg,
            '방법명': '총평균법 (참고용)',
            '설명': '연간 전체 매수의 평균단가로 일괄 계산. 실무 신고에는 사용되지 않으며 참고용으로만 표시.',
        },
        '추천': recommended,
        '절세효과': saving,
        '증권사별_방법': broker_methods,
    }


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
