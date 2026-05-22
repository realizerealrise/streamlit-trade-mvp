"""양도세 절세 시뮬레이터

Level 1: 손실실현 추천 (Tax-Loss Harvesting)
Level 3: 250만원 공제 한도 활용
Level 4: 배당·이자 종합과세 모니터링
Level 6: 사업자 이월결손금 활용
"""
import pandas as pd
from collections import defaultdict


BASIC_DEDUCTION = 2_500_000  # 개인 양도소득 기본공제
TAX_RATE = 0.22              # 22% (양도세 20% + 지방세 2%)
DIVIDEND_LIMIT = 20_000_000  # 종합과세 한계 (배당+이자)
DIVIDEND_TAX_RATE = 0.154    # 15.4%


def simulate_loss_harvesting(realized_pnl_df, holdings_with_pnl, user_type='개인'):
    """
    Level 1: 손실실현 시뮬레이션
    
    Args:
        realized_pnl_df: 종목 손익 현황 (이미 매도한 거래)
        holdings_with_pnl: 평가손익 포함 보유 종목 (현재가 입력된 것만)
        user_type: '개인' or '사업자'
    
    Returns:
        dict:
            - 현재실현이익: 양수 (P)
            - 현재실현손실: 음수 (L)
            - 현재순실현손익: P + L
            - 옵션A (현 상태): {과세표준, 예상세금}
            - 옵션B (손실 매도): {매도대상_DataFrame, 추가실현손실, 새과세표준, 새예상세금, 절세효과}
            - 옵션C (250만 한도 활용): {여유공제, 추천매도이익_DataFrame, 무세금실현가능액}
    """
    # 현재 실현 손익 (이미 매도한 것)
    if realized_pnl_df.empty:
        realized_profit = 0
        realized_loss = 0
    else:
        realized_profit = realized_pnl_df['처분이익(+)'].sum()
        realized_loss = realized_pnl_df['처분손실(-)'].sum()  # 음수
    realized_net = realized_profit + realized_loss
    
    # 옵션 A: 현 상태 유지
    if user_type == '개인':
        deduction_a = min(BASIC_DEDUCTION, max(realized_net, 0))
    else:
        deduction_a = 0
    taxable_a = max(realized_net - deduction_a, 0)
    tax_a = round(taxable_a * TAX_RATE) if user_type == '개인' else None
    
    # 옵션 B: 미실현 손실 종목 모두 매도
    if holdings_with_pnl.empty or '평가손익(원)' not in holdings_with_pnl.columns:
        loss_candidates = pd.DataFrame()
        additional_loss = 0
    else:
        # 입력된 종목 중 평가손실인 것
        loss_candidates = holdings_with_pnl[
            (holdings_with_pnl['입력여부'] == True) &
            (holdings_with_pnl['평가손익(원)'] < 0)
        ].copy()
        additional_loss = loss_candidates['평가손익(원)'].sum() if not loss_candidates.empty else 0
    
    new_net_b = realized_net + additional_loss  # additional_loss는 음수
    if user_type == '개인':
        deduction_b = min(BASIC_DEDUCTION, max(new_net_b, 0))
    else:
        deduction_b = 0
    taxable_b = max(new_net_b - deduction_b, 0)
    tax_b = round(taxable_b * TAX_RATE) if user_type == '개인' else None
    
    # 절세 효과
    savings = (tax_a - tax_b) if (tax_a is not None and tax_b is not None) else 0
    
    # 종목별 절세 효과 계산 — 한계 효과(marginal) 방식
    # 종목별로 매도했을 때 실제 줄어드는 세금만큼 정확히 산정
    if not loss_candidates.empty and user_type == '개인':
        loss_candidates = loss_candidates.copy()
        # 손실 금액 큰 순서대로 정렬 (절대값 큰 게 먼저)
        loss_candidates = loss_candidates.sort_values('평가손익(원)', ascending=True)
        
        # 순차적으로 매도했을 때의 marginal 절세 효과
        cumulative_loss = 0
        marginal_savings = []
        prev_tax = tax_a
        
        for _, row in loss_candidates.iterrows():
            cumulative_loss += row['평가손익(원)']  # 음수 누적
            cur_net = realized_net + cumulative_loss
            cur_ded = min(BASIC_DEDUCTION, max(cur_net, 0))
            cur_taxable = max(cur_net - cur_ded, 0)
            cur_tax = round(cur_taxable * TAX_RATE)
            marginal_savings.append(prev_tax - cur_tax)
            prev_tax = cur_tax
        
        loss_candidates['절세효과(원)'] = marginal_savings
    
    # 옵션 C: 250만 한도 활용 (이익 종목 매도해 무세금 실현)
    if user_type == '개인':
        remaining_deduction = max(BASIC_DEDUCTION - max(realized_net, 0), 0)
    else:
        remaining_deduction = 0
    
    if (holdings_with_pnl.empty or '평가손익(원)' not in holdings_with_pnl.columns
            or remaining_deduction == 0):
        gain_candidates = pd.DataFrame()
        tax_free_realizable = 0
    else:
        gain_candidates = holdings_with_pnl[
            (holdings_with_pnl['입력여부'] == True) &
            (holdings_with_pnl['평가손익(원)'] > 0)
        ].copy()
        if not gain_candidates.empty:
            gain_candidates = gain_candidates.sort_values('평가손익(원)', ascending=False)
        total_gain = gain_candidates['평가손익(원)'].sum() if not gain_candidates.empty else 0
        tax_free_realizable = min(total_gain, remaining_deduction)
    
    return {
        '현재실현이익': realized_profit,
        '현재실현손실': realized_loss,
        '현재순실현손익': realized_net,
        '옵션A': {
            '순실현손익': realized_net,
            '기본공제': deduction_a,
            '과세표준': taxable_a,
            '예상세금': tax_a,
        },
        '옵션B': {
            '추가실현손실': additional_loss,
            '새순실현손익': new_net_b,
            '기본공제': deduction_b,
            '과세표준': taxable_b,
            '예상세금': tax_b,
            '절세효과': savings,
            '매도대상': loss_candidates,
        },
        '옵션C': {
            '여유공제': remaining_deduction,
            '무세금실현가능액': tax_free_realizable,
            '추천이익종목': gain_candidates,
        },
    }


def check_dividend_threshold(trades):
    """
    Level 4: 배당·이자 종합과세 한계 체크
    
    Args:
        trades: 통합 거래 내역
    
    Returns:
        dict: 종합과세 모니터링 정보
    """
    div = sum(t['원화환산금액'] for t in trades if t['거래구분'] == '배당')
    dist = sum(t['원화환산금액'] for t in trades if t['거래구분'] == '분배금')
    interest = sum(t['원화환산금액'] for t in trades if t['거래구분'] == '이자')
    total = div + dist + interest
    
    usage_rate = total / DIVIDEND_LIMIT if DIVIDEND_LIMIT > 0 else 0
    remaining = max(DIVIDEND_LIMIT - total, 0)
    
    if total > DIVIDEND_LIMIT:
        status = 'exceeded'
        status_message = '종합과세 대상 (확정신고 필요)'
    elif usage_rate > 0.8:
        status = 'warning'
        status_message = '한계 근접 (80% 이상)'
    else:
        status = 'safe'
        status_message = '분리과세 (원천징수로 종료)'
    
    return {
        '배당금': div,
        '분배금': dist,
        '이자': interest,
        '합계': total,
        '한계': DIVIDEND_LIMIT,
        '여유': remaining,
        '사용률': usage_rate,
        '상태': status,
        '안내': status_message,
    }


def simulate_corporate_loss_carryforward(taxable_income, loss_carryforward, corp_tax_rate=0.09):
    """
    Level 6: 법인 이월결손금 활용 시뮬레이션
    
    Args:
        taxable_income: 당해 과세소득 (양도+영업)
        loss_carryforward: 이월결손금 잔액
        corp_tax_rate: 법인세율 (2억 이하 9%, 그 이상 19%/21%/24%/25%)
    
    Returns:
        dict: 결손금 활용 시뮬 결과
    """
    if taxable_income <= 0:
        return {
            '당해과세소득': taxable_income,
            '결손금차감': 0,
            '차감후과세표준': max(taxable_income, 0),
            '법인세율': corp_tax_rate,
            '활용시_세금': 0,
            '미활용시_세금': 0,
            '절세효과': 0,
            '이월잔여': loss_carryforward,
        }
    
    # 80% 한도 차감
    max_offset = min(taxable_income * 0.8, loss_carryforward)
    
    # 활용 시
    taxable_with = taxable_income - max_offset
    tax_with = round(taxable_with * corp_tax_rate)
    
    # 미활용 시
    tax_without = round(taxable_income * corp_tax_rate)
    
    return {
        '당해과세소득': taxable_income,
        '결손금차감': max_offset,
        '차감후과세표준': taxable_with,
        '법인세율': corp_tax_rate,
        '활용시_세금': tax_with,
        '미활용시_세금': tax_without,
        '절세효과': tax_without - tax_with,
        '이월잔여': loss_carryforward - max_offset,
    }


def get_filing_period_info(today=None):
    """
    5월 신고기 안내 정보
    
    Returns:
        dict:
            - 신고시작일, 신고마감일, 남은일수
            - 신고연도 (귀속분)
    """
    from datetime import date
    if today is None:
        today = date.today()
    
    current_year = today.year
    # 양도세 확정신고: 매년 5월 1일 ~ 5월 31일 (전년도 귀속분)
    filing_start = date(current_year, 5, 1)
    filing_end = date(current_year, 5, 31)
    
    if today < filing_start:
        days_until = (filing_start - today).days
        status = 'before'
        target_year = current_year - 1
    elif today <= filing_end:
        days_until = (filing_end - today).days
        status = 'in_period'
        target_year = current_year - 1
    else:
        # 신고기간 지나서 다음 해 신고 안내
        next_filing_start = date(current_year + 1, 5, 1)
        days_until = (next_filing_start - today).days
        status = 'after'
        target_year = current_year
    
    return {
        '오늘': today.isoformat(),
        '귀속연도': target_year,
        '신고시작일': filing_start.replace(year=target_year + 1).isoformat(),
        '신고마감일': filing_end.replace(year=target_year + 1).isoformat(),
        '남은일수': days_until,
        '상태': status,
    }
