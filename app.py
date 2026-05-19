"""
멀티 증권사 통합 거래 분석 도구
Streamlit MVP v2 - 양도세 절세 시뮬레이터 포함

실행: streamlit run app.py
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import io

from parsers import parse_toss_pdf, parse_nh_xls
from core import (
    calculate_stock_pnl,
    calculate_dividend,
    calculate_tax,
    get_monthly_trends,
    get_allocation,
    get_current_holdings,
    apply_current_prices,
    simulate_loss_harvesting,
    check_dividend_threshold,
    simulate_corporate_loss_carryforward,
    get_filing_period_info,
)

st.set_page_config(
    page_title="멀티 증권사 거래 분석",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main {padding-top: 1rem;}
    .stMetric {background-color: #f8f9fa; padding: 1rem; border-radius: 0.5rem; border-left: 4px solid #4472C4;}
    .stMetric label {font-weight: 600 !important;}
    h1 {color: #1F3864;}
    h2 {color: #4472C4; border-bottom: 2px solid #D9E1F2; padding-bottom: 0.3rem;}
    .stTabs [data-baseweb="tab-list"] {gap: 8px;}
    .stTabs [data-baseweb="tab"] {height: 50px; padding: 0 24px; background-color: #F2F2F2;}
    .stTabs [aria-selected="true"] {background-color: #4472C4; color: white;}
</style>
""", unsafe_allow_html=True)


with st.sidebar:
    st.title("📊 거래 분석 도구")
    st.caption("멀티 증권사 양도소득 + 절세 시뮬레이터")
    
    filing = get_filing_period_info()
    if filing['상태'] == 'in_period':
        st.error(f"📅 신고 기간 진행 중! **D-{filing['남은일수']}**\n\n{filing['귀속연도']}년 귀속분: ~{filing['신고마감일']}")
    elif filing['상태'] == 'before' and filing['남은일수'] < 60:
        st.warning(f"📅 신고 임박 D-{filing['남은일수']}")
    
    st.divider()
    st.subheader("📥 거래내역 업로드")
    
    toss_files = st.file_uploader("🟦 토스증권 PDF", type=['pdf'], accept_multiple_files=True)
    nh_files = st.file_uploader("🟧 나무증권(NH) xls", type=['xls', 'xlsx'], accept_multiple_files=True)
    kis_files = st.file_uploader("🟥 한투 xls (개발 중)", type=['xls', 'xlsx'],
                                  accept_multiple_files=True, disabled=True)
    
    st.divider()
    st.subheader("👤 신고자 정보")
    user_type = st.radio("신고자 유형", ["개인", "사업자"], horizontal=True)
    
    loss_carryforward = 0
    other_income = 0
    if user_type == "사업자":
        loss_carryforward = st.number_input("이월결손금 (원)", min_value=0, value=0, step=1_000_000, format="%d")
        other_income = st.number_input("기타 영업이익 (원)", min_value=0, value=0, step=1_000_000, format="%d")
    
    st.divider()
    with st.expander("💱 환율 설정 (평가용)"):
        usd_krw = st.number_input("USD/KRW", value=1450.0, step=10.0)
        jpy_krw = st.number_input("JPY/KRW (100엔)", value=950.0, step=10.0)
        hkd_krw = st.number_input("HKD/KRW", value=186.0, step=1.0)
        cny_krw = st.number_input("CNY/KRW", value=200.0, step=1.0)
    
    fx_rates = {'KRW': 1.0, 'USD': usd_krw, 'JPY': jpy_krw, 'HKD': hkd_krw, 'CNY': cny_krw}


st.title("📊 통합 거래 분석 대시보드")
st.caption(f"분석 일자: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  세무사 관점 절세 시뮬레이션 포함")

if filing['상태'] == 'in_period':
    st.error(f"""
    📅 **{filing['귀속연도']}년 귀속 해외주식 양도소득세 확정신고 기간 (D-{filing['남은일수']})**  
    신고: {filing['신고시작일']} ~ {filing['신고마감일']}  
    ⚠️ **국내 비상장주식 양도**가 있으면 **합산 신고** 필요 (양도소득세 신고서 별지)
    """)

all_trades = []
parse_errors = []

if toss_files:
    for f in toss_files:
        try:
            trades = parse_toss_pdf(f)
            all_trades.extend(trades)
            st.sidebar.success(f"✅ 토스 {f.name}: {len(trades)}건")
        except Exception as e:
            parse_errors.append(f"토스 {f.name}: {e}")

if nh_files:
    for f in nh_files:
        try:
            trades = parse_nh_xls(f)
            all_trades.extend(trades)
            st.sidebar.success(f"✅ 나무 {f.name}: {len(trades)}건")
        except Exception as e:
            parse_errors.append(f"나무 {f.name}: {e}")

for err in parse_errors:
    st.error(err)

if not all_trades:
    st.info("👈 사이드바에서 거래내역 파일을 업로드하면 자동 분석이 시작됩니다.")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("### 📥 1. 거래내역 업로드\n- 토스 PDF / 나무 xls\n- 한투 xls (곧)")
    with col2:
        st.markdown("### 🔄 2. 자동 분석\n- 종목별 손익\n- 환차익 분리\n- 평균단가법")
    with col3:
        st.markdown("### 💼 3. 절세 시뮬\n- 손실 매도 추천\n- 250만 활용\n- 종합과세 알람\n- 법인 결손금")
    st.stop()


trades_df = pd.DataFrame(all_trades)
trades_df['거래일자'] = pd.to_datetime(trades_df['거래일자'], errors='coerce')
trades_df = trades_df.sort_values('거래일자').reset_index(drop=True)

pnl_df = calculate_stock_pnl(all_trades)
div_info = calculate_dividend(all_trades)
tax_info = calculate_tax(pnl_df, user_type, loss_carryforward)
allocation = get_allocation(pnl_df)
monthly = get_monthly_trends(all_trades)
holdings_df = get_current_holdings(all_trades)
div_check = check_dividend_threshold(all_trades)

if 'current_prices' not in st.session_state:
    st.session_state.current_prices = {}

st.subheader("핵심 지표")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("📊 통합 거래", f"{len(all_trades):,}건")
col2.metric("💰 처분이익(+)", f"₩{tax_info['처분이익']:,.0f}")
col3.metric("💸 처분손실(-)", f"₩{tax_info['처분손실']:,.0f}")
col4.metric("💎 배당·이자·분배금", f"₩{div_info['합계']:,.0f}")
col5.metric(
    "💼 예상 양도세" if user_type == '개인' else "💼 과세표준",
    f"₩{tax_info['예상세액']:,.0f}" if tax_info['예상세액'] else f"₩{tax_info['과세표준']:,.0f}",
)


tab1, tab_tax, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 대시보드", "💼 절세 시뮬레이터", "💰 종목 손익",
    "📋 양도세 정산", "💎 배당·이자", "📜 거래내역", "📥 다운로드",
])


with tab1:
    col1, col2 = st.columns([3, 2])
    with col1:
        st.markdown("### 📊 종목별 처분손익 TOP 15")
        if not pnl_df.empty:
            top_pnl = pnl_df[pnl_df['처분손익(원)'] != 0].head(15)
            colors = ['#006100' if x > 0 else '#C00000' for x in top_pnl['처분손익(원)']]
            fig = go.Figure(go.Bar(
                x=top_pnl['처분손익(원)'], y=top_pnl['종목명'], orientation='h',
                marker_color=colors,
                text=[f"₩{x:,.0f}" for x in top_pnl['처분손익(원)']], textposition='auto',
            ))
            fig.update_layout(height=500, margin=dict(l=0, r=0, t=20, b=0),
                              xaxis_title="처분손익 (₩)", yaxis=dict(autorange='reversed'))
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("### 💱 자산 배분")
        if allocation['by_currency']:
            fig = go.Figure(go.Pie(
                labels=list(allocation['by_currency'].keys()),
                values=list(allocation['by_currency'].values()),
                hole=0.45, marker=dict(colors=['#4472C4', '#ED7D31', '#A5A5A5']),
            ))
            fig.update_layout(title="통화별 비중", height=240, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)
        
        if allocation['by_broker']:
            fig = go.Figure(go.Pie(
                labels=list(allocation['by_broker'].keys()),
                values=list(allocation['by_broker'].values()),
                hole=0.45, marker=dict(colors=['#4472C4', '#70AD47', '#FFC000', '#7030A0']),
            ))
            fig.update_layout(title="증권사별 비중", height=240, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("### 📅 월별 거래 추이")
    if monthly:
        months = list(monthly.keys())
        fig = go.Figure()
        fig.add_trace(go.Bar(name='매수', x=months, y=[monthly[m]['매수'] for m in months], marker_color='#4472C4'))
        fig.add_trace(go.Bar(name='매도', x=months, y=[monthly[m]['매도'] for m in months], marker_color='#ED7D31'))
        fig.add_trace(go.Bar(name='배당·이자', x=months, y=[monthly[m]['배당이자'] for m in months], marker_color='#70AD47'))
        fig.update_layout(barmode='group', height=350, xaxis_title="월", yaxis_title="금액 (₩)")
        st.plotly_chart(fig, use_container_width=True)


# ── 💼 절세 시뮬레이터 (핵심 신규 탭) ──
with tab_tax:
    st.markdown("## 💼 양도세 절세 시뮬레이터")
    st.caption(f"신고자 유형: **{user_type}** · 세무사 관점 절세 옵션 자동 분석")
    
    with st.expander("💎 배당·이자 종합과세 모니터링 (Level 4)", expanded=False):
        st.progress(min(div_check['사용률'], 1.0))
        st.caption(f"₩{div_check['합계']:,.0f} / ₩{div_check['한계']:,.0f} (사용률 {div_check['사용률']*100:.2f}%, 여유 ₩{div_check['여유']:,.0f})")
        if div_check['상태'] == 'safe':
            st.success(f"✅ {div_check['안내']}")
        elif div_check['상태'] == 'warning':
            st.warning(f"⚠️ {div_check['안내']}")
        else:
            st.error(f"🚨 {div_check['안내']}")
    
    st.divider()
    st.markdown("### 📥 보유 종목 현재가 입력")
    st.caption("미실현 손익 계산용. 두 가지 방법 중 선택")
    
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**방법 1.** 엑셀로 일괄 업로드")
        if not holdings_df.empty:
            template_df = holdings_df[['종목명', '종목코드', '통화', '평균매수가(원통화)']].copy()
            template_df['현재가(원통화)'] = ''
            buffer = io.BytesIO()
            template_df.to_excel(buffer, index=False, engine='openpyxl')
            buffer.seek(0)
            st.download_button(
                "📥 양식 다운로드", buffer,
                file_name="현재가_입력양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        
        price_file = st.file_uploader("📤 작성한 양식 업로드", type=['xlsx'])
        if price_file:
            try:
                price_df = pd.read_excel(price_file)
                count = 0
                for _, row in price_df.iterrows():
                    if pd.notna(row.get('현재가(원통화)')):
                        try:
                            price = float(row['현재가(원통화)'])
                            if price > 0:
                                key = (row['통화'], row['종목코드'] if pd.notna(row.get('종목코드')) and row['종목코드'] else row['종목명'])
                                st.session_state.current_prices[key] = price
                                count += 1
                        except (ValueError, TypeError):
                            pass
                st.success(f"✅ {count}개 종목 현재가 적용")
            except Exception as e:
                st.error(f"파일 읽기 실패: {e}")
    
    with col_b:
        st.markdown("**방법 2.** 표에서 직접 입력")
        st.caption("아래 표에서 현재가를 직접 입력하세요.")
    
    if not holdings_df.empty:
        st.markdown("#### 보유 종목 목록 (현재가 직접 입력 가능)")
        
        edit_df = holdings_df[['종목명', '종목코드', '통화', '증권사', '보유수량', '평균매수가(원통화)']].copy()
        edit_df['현재가(원통화)'] = 0.0
        for idx, row in edit_df.iterrows():
            key = (row['통화'], row['종목코드'] if row['종목코드'] else row['종목명'])
            if key in st.session_state.current_prices:
                edit_df.at[idx, '현재가(원통화)'] = st.session_state.current_prices[key]
        
        edited = st.data_editor(
            edit_df,
            column_config={
                '종목명': st.column_config.TextColumn('종목명', disabled=True),
                '종목코드': st.column_config.TextColumn('종목코드', disabled=True),
                '통화': st.column_config.TextColumn('통화', disabled=True),
                '증권사': st.column_config.TextColumn('증권사', disabled=True),
                '보유수량': st.column_config.NumberColumn('보유수량', disabled=True, format="%.4f"),
                '평균매수가(원통화)': st.column_config.NumberColumn('평균매수가', disabled=True, format="%.2f"),
                '현재가(원통화)': st.column_config.NumberColumn('현재가 입력 ✏️', min_value=0.0, format="%.2f"),
            },
            hide_index=True, use_container_width=True, num_rows="fixed",
            key="price_editor",
        )
        
        for idx, row in edited.iterrows():
            key = (row['통화'], row['종목코드'] if row['종목코드'] else row['종목명'])
            if row['현재가(원통화)'] and row['현재가(원통화)'] > 0:
                st.session_state.current_prices[key] = row['현재가(원통화)']
        
        st.divider()
        
        holdings_with_pnl = apply_current_prices(holdings_df, st.session_state.current_prices, fx_rates)
        entered = holdings_with_pnl[holdings_with_pnl['입력여부'] == True]
        
        st.markdown(f"### 📊 시뮬레이션 결과 ({len(entered)}/{len(holdings_df)} 종목 입력)")
        
        if entered.empty:
            st.info("👆 위 표에서 보유 종목의 현재가를 입력해주세요.")
        else:
            sim = simulate_loss_harvesting(pnl_df, holdings_with_pnl, user_type)
            
            loss_count = (entered['평가손익(원)'] < 0).sum()
            gain_count = (entered['평가손익(원)'] > 0).sum()
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("💵 실현이익", f"₩{sim['현재실현이익']:,.0f}")
            c2.metric("💸 실현손실", f"₩{sim['현재실현손실']:,.0f}")
            c3.metric(f"📉 미실현 손실 ({loss_count}종목)", 
                      f"₩{entered[entered['평가손익(원)']<0]['평가손익(원)'].sum():,.0f}")
            c4.metric(f"📈 미실현 이익 ({gain_count}종목)",
                      f"₩{entered[entered['평가손익(원)']>0]['평가손익(원)'].sum():,.0f}")
            
            st.markdown("### 시나리오 비교")
            col_a, col_b = st.columns(2)
            
            with col_a:
                st.markdown("#### 📌 옵션 A · 현 상태 유지")
                if user_type == '개인':
                    st.markdown(f"""
                    | 항목 | 금액 |
                    |---|---:|
                    | 순 실현손익 | ₩{sim['옵션A']['순실현손익']:,.0f} |
                    | 250만 공제 | -₩{sim['옵션A']['기본공제']:,.0f} |
                    | **과세표준** | **₩{sim['옵션A']['과세표준']:,.0f}** |
                    | **예상 세금 (22%)** | **₩{sim['옵션A']['예상세금']:,.0f}** |
                    """)
                else:
                    st.markdown(f"""
                    | 항목 | 금액 |
                    |---|---:|
                    | 순 실현손익 | ₩{sim['옵션A']['순실현손익']:,.0f} |
                    | 과세표준 | ₩{sim['옵션A']['과세표준']:,.0f} |
                    | 세금 | 법인세 합산 (별도) |
                    """)
            
            with col_b:
                st.markdown("#### 🎯 옵션 B · 손실 종목 매도")
                if user_type == '개인':
                    st.markdown(f"""
                    | 항목 | 금액 |
                    |---|---:|
                    | 추가 실현손실 | ₩{sim['옵션B']['추가실현손실']:,.0f} |
                    | 새 순실현손익 | ₩{sim['옵션B']['새순실현손익']:,.0f} |
                    | 250만 공제 | -₩{sim['옵션B']['기본공제']:,.0f} |
                    | **새 과세표준** | **₩{sim['옵션B']['과세표준']:,.0f}** |
                    | **새 예상 세금 (22%)** | **₩{sim['옵션B']['예상세금']:,.0f}** |
                    """)
                else:
                    st.markdown(f"""
                    | 항목 | 금액 |
                    |---|---:|
                    | 추가 실현손실 | ₩{sim['옵션B']['추가실현손실']:,.0f} |
                    | 새 순실현손익 | ₩{sim['옵션B']['새순실현손익']:,.0f} |
                    """)
            
            if sim['옵션B']['절세효과'] and sim['옵션B']['절세효과'] > 0:
                st.success(f"### 💰 절세 효과: ₩{sim['옵션B']['절세효과']:,.0f}")
            
            if not sim['옵션B']['매도대상'].empty:
                st.markdown("#### 💡 손실 실현 추천 종목 (매도 권장 — 노란색 강조)")
                rec_cols = ['종목명', '종목코드', '통화', '증권사', '보유수량', 
                            '평균매수가(원통화)', '현재가(원통화)', '평가손익(원)']
                if '절세효과(원)' in sim['옵션B']['매도대상'].columns:
                    rec_cols.append('절세효과(원)')
                rec = sim['옵션B']['매도대상'][rec_cols].copy()
                
                fmt_dict = {
                    '보유수량': '{:,.4f}',
                    '평균매수가(원통화)': '{:,.2f}',
                    '현재가(원통화)': '{:,.2f}',
                    '평가손익(원)': '₩{:+,.0f}',
                }
                if '절세효과(원)' in rec.columns:
                    fmt_dict['절세효과(원)'] = '₩{:+,.0f}'
                
                st.dataframe(
                    rec.style.format(fmt_dict).apply(
                        lambda row: ['background-color: #FFF2CC' for _ in row], axis=1
                    ),
                    hide_index=True, use_container_width=True,
                )
            
            if user_type == '개인' and sim['옵션C']['여유공제'] > 0:
                st.markdown("---")
                st.markdown("#### 🆓 옵션 C · 250만 공제 한도 활용 (무세금 이익 실현)")
                st.info(f"""
                - 남은 공제 한도: **₩{sim['옵션C']['여유공제']:,.0f}**
                - 무세금 실현 가능 금액: **₩{sim['옵션C']['무세금실현가능액']:,.0f}**
                """)
                if not sim['옵션C']['추천이익종목'].empty:
                    gain_rec = sim['옵션C']['추천이익종목'][['종목명', '통화', '증권사', '평가손익(원)']].copy()
                    st.dataframe(
                        gain_rec.style.format({'평가손익(원)': '₩{:+,.0f}'}),
                        hide_index=True, use_container_width=True,
                    )
    
    if user_type == '사업자' and loss_carryforward > 0:
        st.divider()
        st.markdown("### 🏢 법인 이월결손금 활용 시뮬레이션 (Level 6)")
        
        annual_income = max(tax_info['순처분손익'], 0) + other_income
        corp_sim = simulate_corporate_loss_carryforward(annual_income, loss_carryforward)
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 결손금 미활용")
            st.markdown(f"""
            | 항목 | 금액 |
            |---|---:|
            | 과세소득 | ₩{corp_sim['당해과세소득']:,.0f} |
            | 법인세율 | {corp_sim['법인세율']*100:.0f}% |
            | **예상 세금** | **₩{corp_sim['미활용시_세금']:,.0f}** |
            """)
        with c2:
            st.markdown("#### 결손금 활용 (추천)")
            st.markdown(f"""
            | 항목 | 금액 |
            |---|---:|
            | 80% 한도 차감 | -₩{corp_sim['결손금차감']:,.0f} |
            | 차감 후 과세표준 | ₩{corp_sim['차감후과세표준']:,.0f} |
            | **예상 세금** | **₩{corp_sim['활용시_세금']:,.0f}** |
            | 이월 잔여 | ₩{corp_sim['이월잔여']:,.0f} |
            """)
        
        if corp_sim['절세효과'] > 0:
            st.success(f"💰 절세 효과: ₩{corp_sim['절세효과']:,.0f}")
    
    st.divider()
    st.warning("""
    ### ⚠️ 본 시뮬레이션은 참고 자료입니다 (면책 안내)
    
    - 본 도구는 **세무 자문이나 투자 권유가 아닙니다.** 표시된 절세 효과는 입력 데이터 기준 자동 계산값입니다.
    - 매도 권장 표시는 양도세 절감만 고려한 산정이며, **종목의 향후 전망 / 손실 회복 가능성은 별도 판단**이 필요합니다.
    - 미실현 손익은 사용자가 입력한 현재가 기준입니다. 실제 매도가는 시장 변동으로 달라질 수 있습니다.
    - 연말 (12월 30일 체결 기준) 이후 매도분은 **다음 해 손익**으로 분류됩니다.
    - **국내 비상장주식 양도**가 있는 경우 해외주식 양도소득과 **합산 신고**가 필요합니다 (양도소득세 신고서 별지).
    - 실제 세금 신고 전 **세무 전문가**와 상담하세요.
    """)


with tab2:
    st.markdown("### 💰 종목별 손익 현황")
    col1, col2, col3 = st.columns(3)
    col1.metric("매매 종목 수", f"{len(pnl_df)}개")
    col2.metric("총 매수", f"₩{pnl_df['총매수(원)'].sum():,.0f}")
    col3.metric("총 매도", f"₩{pnl_df['총매도(원)'].sum():,.0f}")
    
    if not pnl_df.empty:
        display_cols = ['종목명', '종목코드', '통화', '증권사',
                        '매수횟수', '매수수량', '평균매수단가(원)',
                        '매도횟수', '매도수량', '매도원가(원)',
                        '처분손익(원)', '처분이익(+)', '처분손실(-)',
                        '잔고수량', '잔고원가(원)']
        st.dataframe(
            pnl_df[display_cols].style.format({
                '매수수량': '{:,.4f}', '매도수량': '{:,.4f}', '잔고수량': '{:,.4f}',
                '평균매수단가(원)': '{:,.0f}', '매도원가(원)': '{:,.0f}',
                '처분손익(원)': '{:+,.0f}', '처분이익(+)': '{:,.0f}', '처분손실(-)': '{:,.0f}',
                '잔고원가(원)': '{:,.0f}',
            }).map(
                lambda v: 'color: #006100; font-weight: bold' if isinstance(v, (int, float)) and v > 0 else 
                          ('color: #C00000; font-weight: bold' if isinstance(v, (int, float)) and v < 0 else ''),
                subset=['처분손익(원)']
            ),
            height=600, use_container_width=True
        )


with tab3:
    st.markdown("### 📋 양도소득 정산")
    st.caption(f"신고자 유형: **{user_type}**" + (f"  |  이월결손금: ₩{loss_carryforward:,}" if user_type == '사업자' else ""))
    
    tax_data = pd.DataFrame([
        {"항목": "① 처분이익", "금액": tax_info['처분이익']},
        {"항목": "② 처분손실", "금액": tax_info['처분손실']},
        {"항목": "③ 순처분손익", "금액": tax_info['순처분손익']},
        {"항목": "④ 기본공제 (개인 250만)", "금액": tax_info['기본공제']},
        {"항목": "⑤ 이월결손금 차감", "금액": tax_info['이월결손금차감']},
        {"항목": "⑥ 과세표준", "금액": tax_info['과세표준']},
    ])
    
    st.dataframe(
        tax_data.style.format({'금액': '{:+,.0f}'}).map(
            lambda v: 'background-color: #FFF2CC; font-weight: bold' if isinstance(v, (int, float)) else '',
            subset=['금액']
        ),
        hide_index=True, use_container_width=True, height=250
    )
    
    col1, col2 = st.columns(2)
    col1.metric("⑦ 적용 세율", tax_info['세율_설명'])
    if tax_info['예상세액'] is not None:
        col2.metric("⑧ 예상 세액", f"₩{tax_info['예상세액']:,}")
    
    st.info("""
    💡 **신고 안내**
    - 매년 5월 1일 ~ 31일: 전년도 귀속 해외주식 양도소득세 확정신고
    - **국내 비상장주식 양도가 있으면 합산 신고** (양도소득세 신고서 별지 작성)
    - 통화별 환차익은 자동 합산되어 신고됩니다
    """)


with tab4:
    st.markdown("### 💎 배당·이자·분배금 수익")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 배당금", f"₩{div_info['배당금']:,.0f}")
    col2.metric("📊 ETF 분배금", f"₩{div_info['분배금']:,.0f}")
    col3.metric("🏦 예탁금 이자", f"₩{div_info['이자']:,.0f}")
    col4.metric("💎 합계", f"₩{div_info['합계']:,.0f}")
    
    st.markdown("#### 종합과세 한계 진행도")
    st.progress(min(div_check['사용률'], 1.0))
    st.caption(f"₩{div_check['합계']:,.0f} / ₩{div_check['한계']:,.0f} (사용률 {div_check['사용률']*100:.2f}%)")
    
    if div_info['상세']:
        st.markdown("#### 상세 내역")
        div_df = pd.DataFrame(div_info['상세'])
        display_cols = ['거래일자', '증권사', '거래구분', '종목명', '거래금액', '비고']
        div_df = div_df[display_cols].sort_values('거래일자', ascending=False)
        st.dataframe(
            div_df.style.format({'거래금액': '₩{:,.0f}'}),
            hide_index=True, use_container_width=True, height=400
        )


with tab5:
    st.markdown("### 📜 통합 거래내역")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        broker_filter = st.selectbox("증권사", ['전체'] + sorted(trades_df['증권사'].unique().tolist()))
    with col2:
        type_filter = st.selectbox("거래구분", ['전체'] + sorted(trades_df['거래구분'].unique().tolist()))
    with col3:
        curr_filter = st.selectbox("통화", ['전체'] + sorted(trades_df['통화'].unique().tolist()))
    with col4:
        stock_filter = st.selectbox("종목명", ['전체'] + sorted(trades_df['종목명'].unique().tolist()))
    
    filtered = trades_df.copy()
    if broker_filter != '전체': filtered = filtered[filtered['증권사'] == broker_filter]
    if type_filter != '전체': filtered = filtered[filtered['거래구분'] == type_filter]
    if curr_filter != '전체': filtered = filtered[filtered['통화'] == curr_filter]
    if stock_filter != '전체': filtered = filtered[filtered['종목명'] == stock_filter]
    
    st.caption(f"전체 {len(trades_df):,}건 중 {len(filtered):,}건")
    
    display_cols = ['거래일자', '증권사', '통화', '거래구분', '종목명', '종목코드',
                    '수량', '단가', '거래금액', '환율', '원화환산금액', '수수료(원)', '비고']
    st.dataframe(
        filtered[display_cols].style.format({
            '거래일자': lambda d: d.strftime('%Y-%m-%d') if pd.notnull(d) else '',
            '수량': '{:,.4f}', '단가': '{:,.4f}', '거래금액': '{:,.2f}',
            '환율': '{:,.2f}', '원화환산금액': '₩{:,.0f}', '수수료(원)': '₩{:,.0f}',
        }),
        hide_index=True, use_container_width=True, height=500
    )


with tab6:
    st.markdown("### 📥 결과 다운로드")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("#### 📊 통합 분석 엑셀")
        if st.button("⬇️ 엑셀 생성", use_container_width=True, type="primary"):
            with st.spinner("엑셀 생성 중..."):
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    trades_df.to_excel(writer, sheet_name='거래내역', index=False)
                    pnl_df.to_excel(writer, sheet_name='종목손익', index=False)
                    if not holdings_df.empty:
                        holdings_df.to_excel(writer, sheet_name='보유종목', index=False)
                    tax_data.to_excel(writer, sheet_name='양도세정산', index=False)
                    if div_info['상세']:
                        pd.DataFrame(div_info['상세']).to_excel(writer, sheet_name='배당이자', index=False)
                buffer.seek(0)
                st.download_button(
                    "📥 다운로드", buffer,
                    file_name=f"통합분석_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
    with col2:
        st.markdown("#### 🏛 홈택스 양식")
        st.button("⬇️ 홈택스 양식 (개발 예정)", disabled=True, use_container_width=True, key="dl_hometax")
    with col3:
        st.markdown("#### 📄 PDF 신고 자료")
        st.button("⬇️ PDF 신고서 (개발 예정)", disabled=True, use_container_width=True, key="dl_pdf")


st.divider()
st.caption("⚠️ 본 도구는 세무 자문이 아닙니다. 실제 세금 신고는 세무 전문가와 상담하세요. · 국내 비상장주식 양도가 있으면 합산 신고 필요")
