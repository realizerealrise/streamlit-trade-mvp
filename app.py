"""
멀티 증권사 통합 거래 분석 도구
Streamlit MVP

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
)

# ─────────────────────────── 페이지 설정 ───────────────────────────
st.set_page_config(
    page_title="멀티 증권사 거래 분석",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 스타일링
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


# ─────────────────────────── 사이드바 ───────────────────────────
with st.sidebar:
    st.title("📊 거래 분석 도구")
    st.caption("멀티 증권사 양도소득 정산 도구")
    
    st.divider()
    st.subheader("📥 거래내역 업로드")
    
    toss_files = st.file_uploader(
        "🟦 토스증권 PDF",
        type=['pdf'],
        accept_multiple_files=True,
        help="토스증권 앱 > 더보기 > 거래내역서 다운로드"
    )
    
    nh_files = st.file_uploader(
        "🟧 나무증권(NH) xls",
        type=['xls', 'xlsx'],
        accept_multiple_files=True,
        help="나무증권 > 종합거래내역 다운로드"
    )
    
    kis_files = st.file_uploader(
        "🟥 한국투자증권 xls",
        type=['xls', 'xlsx'],
        accept_multiple_files=True,
        help="한투 HTS > 거래내역 다운로드"
    )
    
    st.divider()
    st.subheader("👤 신고자 정보")
    
    user_type = st.radio("신고자 유형", ["개인", "사업자"], horizontal=True)
    
    loss_carryforward = 0
    if user_type == "사업자":
        loss_carryforward = st.number_input(
            "이월결손금 (원)",
            min_value=0, value=0, step=1_000_000, format="%d",
            help="직전 15년치 이월결손금 잔액 (당해 소득 80% 한도 차감)"
        )
    
    st.divider()
    with st.expander("💱 환율 설정"):
        usd_krw = st.number_input("USD/KRW", value=1450.0, step=10.0)
        jpy_krw = st.number_input("JPY/KRW (100엔)", value=950.0, step=10.0)


# ─────────────────────────── 메인 ───────────────────────────
st.title("📊 통합 거래 분석 대시보드")
st.caption(f"분석 일자: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# 파일 파싱
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

if parse_errors:
    for err in parse_errors:
        st.error(err)

# 거래 없으면 안내 화면
if not all_trades:
    st.info("👈 사이드바에서 거래내역 파일을 업로드하면 자동 분석이 시작됩니다.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        ### 📥 1. 거래내역 업로드
        - 토스증권 PDF
        - 나무증권(NH) xls
        - 한투 xls
        - 여러 파일 동시 가능
        """)
    with col2:
        st.markdown("""
        ### 🔄 2. 자동 분석
        - 증권사별 양식 자동 인식
        - 종목별 손익 계산
        - 환차익 분리
        - 평균단가법 적용
        """)
    with col3:
        st.markdown("""
        ### 📤 3. 결과 활용
        - 양도세 정산표
        - 종목별 손익 현황
        - 홈택스 업로드 엑셀
        - PDF 신고 자료
        """)
    
    st.stop()


# ─────────────────────────── 분석 ───────────────────────────
trades_df = pd.DataFrame(all_trades)
trades_df['거래일자'] = pd.to_datetime(trades_df['거래일자'], errors='coerce')
trades_df = trades_df.sort_values('거래일자').reset_index(drop=True)

pnl_df = calculate_stock_pnl(all_trades)
div_info = calculate_dividend(all_trades)
tax_info = calculate_tax(pnl_df, user_type, loss_carryforward)
allocation = get_allocation(pnl_df)
monthly = get_monthly_trends(all_trades)

# 핵심 KPI
st.subheader("핵심 지표")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("📊 통합 거래", f"{len(all_trades):,}건")
col2.metric("💰 처분이익(+)", f"₩{tax_info['처분이익']:,.0f}")
col3.metric("💸 처분손실(-)", f"₩{tax_info['처분손실']:,.0f}")
col4.metric("💎 배당·이자·분배금", f"₩{div_info['합계']:,.0f}")
col5.metric(
    "💼 예상 양도세" if user_type == '개인' else "💼 과세표준",
    f"₩{tax_info['예상세액']:,.0f}" if tax_info['예상세액'] else f"₩{tax_info['과세표준']:,.0f}",
    help="개인: 250만원 공제 후 22%" if user_type == '개인' else "사업자: 이월결손금 차감 후"
)


# ─────────────────────────── 탭 ───────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 대시보드",
    "💰 종목 손익",
    "💼 양도세 정산",
    "💎 배당·이자",
    "📋 거래내역",
    "📥 다운로드",
])


# ── 탭 1: 대시보드 ──
with tab1:
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.markdown("### 📊 종목별 처분손익 TOP 15")
        if not pnl_df.empty:
            top_pnl = pnl_df[pnl_df['처분손익(원)'] != 0].head(15)
            colors = ['#006100' if x > 0 else '#C00000' for x in top_pnl['처분손익(원)']]
            fig = go.Figure(go.Bar(
                x=top_pnl['처분손익(원)'],
                y=top_pnl['종목명'],
                orientation='h',
                marker_color=colors,
                text=[f"₩{x:,.0f}" for x in top_pnl['처분손익(원)']],
                textposition='auto',
            ))
            fig.update_layout(
                height=500, margin=dict(l=0, r=0, t=20, b=0),
                xaxis_title="처분손익 (₩)", yaxis=dict(autorange='reversed'),
                font=dict(family="Arial"),
            )
            st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        st.markdown("### 💱 자산 배분")
        if allocation['by_currency']:
            fig = go.Figure(go.Pie(
                labels=list(allocation['by_currency'].keys()),
                values=list(allocation['by_currency'].values()),
                hole=0.45,
                marker=dict(colors=['#4472C4', '#ED7D31', '#A5A5A5']),
            ))
            fig.update_layout(
                title="통화별 비중", height=240,
                margin=dict(l=0, r=0, t=40, b=0),
                font=dict(family="Arial"),
            )
            st.plotly_chart(fig, use_container_width=True)
        
        if allocation['by_broker']:
            fig = go.Figure(go.Pie(
                labels=list(allocation['by_broker'].keys()),
                values=list(allocation['by_broker'].values()),
                hole=0.45,
                marker=dict(colors=['#4472C4', '#70AD47', '#FFC000', '#7030A0']),
            ))
            fig.update_layout(
                title="증권사별 비중", height=240,
                margin=dict(l=0, r=0, t=40, b=0),
                font=dict(family="Arial"),
            )
            st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("### 📅 월별 거래 추이")
    if monthly:
        months = list(monthly.keys())
        buy = [monthly[m]['매수'] for m in months]
        sell = [monthly[m]['매도'] for m in months]
        div = [monthly[m]['배당이자'] for m in months]
        
        fig = go.Figure()
        fig.add_trace(go.Bar(name='매수', x=months, y=buy, marker_color='#4472C4'))
        fig.add_trace(go.Bar(name='매도', x=months, y=sell, marker_color='#ED7D31'))
        fig.add_trace(go.Bar(name='배당·이자', x=months, y=div, marker_color='#70AD47'))
        fig.update_layout(
            barmode='group', height=350,
            xaxis_title="월", yaxis_title="금액 (₩)",
            margin=dict(l=0, r=0, t=20, b=0),
            font=dict(family="Arial"),
        )
        st.plotly_chart(fig, use_container_width=True)


# ── 탭 2: 종목 손익 ──
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
                '매수수량': '{:,.4f}',
                '매도수량': '{:,.4f}',
                '잔고수량': '{:,.4f}',
                '평균매수단가(원)': '{:,.0f}',
                '매도원가(원)': '{:,.0f}',
                '처분손익(원)': '{:+,.0f}',
                '처분이익(+)': '{:,.0f}',
                '처분손실(-)': '{:,.0f}',
                '잔고원가(원)': '{:,.0f}',
            }).map(
                lambda v: 'color: #006100; font-weight: bold' if isinstance(v, (int, float)) and v > 0 else 
                          ('color: #C00000; font-weight: bold' if isinstance(v, (int, float)) and v < 0 else ''),
                subset=['처분손익(원)']
            ),
            height=600, use_container_width=True
        )


# ── 탭 3: 양도세 정산 ──
with tab3:
    st.markdown("### 💼 양도소득 정산")
    st.caption(f"신고자 유형: **{user_type}**" + (f"  |  이월결손금: ₩{loss_carryforward:,}" if user_type == '사업자' else ""))
    
    tax_data = pd.DataFrame([
        {"항목": "① 처분이익 (양수 합계)", "금액": tax_info['처분이익'], "설명": "처분손익이 (+)인 종목들의 합"},
        {"항목": "② 처분손실 (음수 합계)", "금액": tax_info['처분손실'], "설명": "처분손익이 (-)인 종목들의 합"},
        {"항목": "③ 순처분손익 (① + ②)", "금액": tax_info['순처분손익'], "설명": "이익 - 손실"},
        {"항목": "④ 기본공제 (개인만 250만원)", "금액": tax_info['기본공제'], "설명": "해외주식 양도소득 연 250만원"},
        {"항목": "⑤ 이월결손금 차감 (사업자만)", "금액": tax_info['이월결손금차감'], "설명": "사업자: 직전 15년, 80% 한도"},
        {"항목": "⑥ 과세표준 (③ - ④ - ⑤)", "금액": tax_info['과세표준'], "설명": "실제 세금 대상 금액"},
    ])
    
    st.dataframe(
        tax_data.style.format({'금액': '{:+,.0f}'}).map(
            lambda v: 'background-color: #FFF2CC; font-weight: bold' if isinstance(v, (int, float)) else '',
            subset=['금액']
        ),
        hide_index=True, use_container_width=True, height=250
    )
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("⑦ 적용 세율", tax_info['세율_설명'])
    with col2:
        if tax_info['예상세액'] is not None:
            st.metric("⑧ 예상 세액", f"₩{tax_info['예상세액']:,}")
        else:
            st.info("법인세는 법인 전체 소득에서 별도 산정")
    
    st.warning("""
    ⚠️ **주의사항**
    - 본 도구는 양도차익만 산정합니다. 실제 세금 신고 전 세무 전문가와 상담하세요.
    - 개인 양도세: 매년 5월 종합소득세 신고 기간에 별도로 양도소득세 확정신고 필요.
    - 통화별 분리 산정: USD와 KRW의 처분손익이 통합 집계 (환차익 일부 포함).
    """)


# ── 탭 4: 배당·이자 ──
with tab4:
    st.markdown("### 💎 배당·이자·분배금 수익")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 배당금", f"₩{div_info['배당금']:,.0f}")
    col2.metric("📊 ETF 분배금", f"₩{div_info['분배금']:,.0f}")
    col3.metric("🏦 예탁금 이자", f"₩{div_info['이자']:,.0f}")
    col4.metric("💎 합계", f"₩{div_info['합계']:,.0f}", help="종합소득 정산 대상")
    
    if div_info['상세']:
        st.markdown("#### 상세 내역")
        div_df = pd.DataFrame(div_info['상세'])
        display_cols = ['거래일자', '증권사', '거래구분', '종목명', '거래금액', '비고']
        div_df = div_df[display_cols].sort_values('거래일자', ascending=False)
        st.dataframe(
            div_df.style.format({'거래금액': '₩{:,.0f}'}),
            hide_index=True, use_container_width=True, height=400
        )
    
    st.info("""
    💡 **종합소득세 안내**
    - 배당소득세 (국내): 원천징수 15.4% → 통상 자동 차감
    - 배당+이자 연 2,000만원 초과 시 → 종합과세 (확정신고)
    - ETF 분배금: 배당소득세와 동일
    """)


# ── 탭 5: 거래내역 ──
with tab5:
    st.markdown("### 📋 통합 거래내역")
    
    # 필터
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        brokers = ['전체'] + sorted(trades_df['증권사'].unique().tolist())
        broker_filter = st.selectbox("증권사", brokers)
    with col2:
        types = ['전체'] + sorted(trades_df['거래구분'].unique().tolist())
        type_filter = st.selectbox("거래구분", types)
    with col3:
        currencies = ['전체'] + sorted(trades_df['통화'].unique().tolist())
        curr_filter = st.selectbox("통화", currencies)
    with col4:
        stocks = ['전체'] + sorted(trades_df['종목명'].unique().tolist())
        stock_filter = st.selectbox("종목명", stocks)
    
    # 필터링
    filtered = trades_df.copy()
    if broker_filter != '전체': filtered = filtered[filtered['증권사'] == broker_filter]
    if type_filter != '전체': filtered = filtered[filtered['거래구분'] == type_filter]
    if curr_filter != '전체': filtered = filtered[filtered['통화'] == curr_filter]
    if stock_filter != '전체': filtered = filtered[filtered['종목명'] == stock_filter]
    
    st.caption(f"전체 {len(trades_df):,}건 중 {len(filtered):,}건 표시")
    
    display_cols = ['거래일자', '증권사', '통화', '거래구분', '종목명', '종목코드',
                    '수량', '단가', '거래금액', '환율', '원화환산금액', '수수료(원)', '비고']
    
    st.dataframe(
        filtered[display_cols].style.format({
            '거래일자': lambda d: d.strftime('%Y-%m-%d') if pd.notnull(d) else '',
            '수량': '{:,.4f}',
            '단가': '{:,.4f}',
            '거래금액': '{:,.2f}',
            '환율': '{:,.2f}',
            '원화환산금액': '₩{:,.0f}',
            '수수료(원)': '₩{:,.0f}',
        }),
        hide_index=True, use_container_width=True, height=500
    )


# ── 탭 6: 다운로드 ──
with tab6:
    st.markdown("### 📥 결과 다운로드")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("#### 📊 통합 분석 엑셀")
        st.caption("종목 손익, 거래 내역, 양도세 정산 등 전체 분석 결과")
        
        if st.button("⬇️ 엑셀 생성", use_container_width=True, type="primary"):
            with st.spinner("엑셀 생성 중..."):
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    trades_df.to_excel(writer, sheet_name='거래내역', index=False)
                    pnl_df.to_excel(writer, sheet_name='종목손익', index=False)
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
        st.markdown("#### 🏛 홈택스 양식 (해외주식)")
        st.caption("해외주식 양도소득세 확정신고용 23컬럼 엑셀")
        st.button("⬇️ 생성 예정", disabled=True, use_container_width=True, help="외주 개발 단계에서 추가")
    
    with col3:
        st.markdown("#### 📄 PDF 신고 자료")
        st.caption("세무사에게 전달할 양도세 신고 요약 PDF")
        st.button("⬇️ 생성 예정", disabled=True, use_container_width=True, help="외주 개발 단계에서 추가")

# 푸터
st.divider()
st.caption("⚠️ 본 도구는 양도차익 산정용입니다. 실제 세금 신고는 세무 전문가와 상담하세요.")
