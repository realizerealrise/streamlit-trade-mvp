"""토스증권 PDF 거래내역 파서"""
import re
import pdfplumber

DATE_PATTERN = re.compile(r'^(\d{4}\.\d{2}\.\d{2})')
ISIN_PATTERN = re.compile(r'\(([A-Z]{2}[A-Z0-9]{10})\)')


def clean_stock_name(name):
    """PDF 줄바꿈으로 어색해진 종목명 정리"""
    name = name.replace(' 배 ', '배 ').replace(' 배', '배')
    name = name.replace('인버스ETF', '인버스 ETF').replace('숏ETF', '숏 ETF').replace('롱ETF', '롱 ETF')
    return name.strip()


def parse_toss_pdf(file_obj):
    """
    토스증권 거래내역서 PDF → 거래 리스트
    
    Args:
        file_obj: Streamlit uploaded_file 또는 파일 경로
    
    Returns:
        list of dict: 통합 양식 거래 데이터
    """
    all_lines = []
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            for line in text.split('\n'):
                line = line.strip()
                if line:
                    all_lines.append(line)
    
    # 거래 그룹핑 (날짜로 시작하는 라인 + 다음 줄들)
    trades_raw = []
    i = 0
    while i < len(all_lines):
        line = all_lines[i]
        if DATE_PATTERN.match(line):
            group = [line]
            j = i + 1
            while j < len(all_lines) and not DATE_PATTERN.match(all_lines[j]):
                nxt = all_lines[j]
                if nxt.startswith('거래일자') or '/ 8' in nxt or '거래내역' in nxt or '발급' in nxt:
                    break
                group.append(nxt)
                j += 1
            trades_raw.append(group)
            i = j
        else:
            i += 1
    
    # 각 거래 파싱
    parsed = []
    for group in trades_raw:
        line1 = group[0]
        line2 = ' '.join(group[1:]) if len(group) > 1 else ''
        
        isin_in_l1 = ISIN_PATTERN.search(line1)
        isin_in_l2 = ISIN_PATTERN.search(line2)
        
        if isin_in_l1:
            isin = isin_in_l1.group(1)
            line1_clean = ISIN_PATTERN.sub('', line1).strip()
            extra_name = ''
        elif isin_in_l2:
            isin = isin_in_l2.group(1)
            before_isin = line2[:isin_in_l2.start()].strip()
            extra_name = before_isin
            line1_clean = line1
        else:
            continue
        
        parts = line1_clean.split()
        if len(parts) < 3:
            continue
        date = parts[0]
        action = parts[1]
        
        rest = ' '.join(parts[2:])
        rate_match = re.search(r'(\d{1,3},\d{3}\.\d+)', rest)
        if not rate_match:
            continue
        
        stock_name = rest[:rate_match.start()].strip()
        if extra_name:
            stock_name = (stock_name + ' ' + extra_name).strip()
        stock_name = clean_stock_name(stock_name)
        
        nums_part = rest[rate_match.start():].strip()
        nums = nums_part.replace(',', '').split()
        dollar_nums = re.findall(r'\$\s*(-?\d+\.?\d*)', line2)
        
        # 통합 양식으로 변환
        action_unified = '매수' if action == '구매' else '매도'
        
        parsed.append({
            '거래일자': date.replace('.', '-'),
            '증권사': '토스',
            '통화': 'USD',
            '시장': '해외',
            '거래구분': action_unified,
            '종목명': stock_name,
            '종목코드': isin,
            '수량': float(nums[1]) if len(nums) > 1 else 0,
            '단가': float(dollar_nums[1]) if len(dollar_nums) > 1 else 0,
            '거래금액': float(dollar_nums[0]) if len(dollar_nums) > 0 else 0,
            '환율': float(nums[0]) if len(nums) > 0 else 0,
            '원화환산금액': float(nums[2]) if len(nums) > 2 else 0,
            '수수료(원)': float(nums[4]) if len(nums) > 4 else 0,
            '세금(원)': float(nums[5]) if len(nums) > 5 else 0,
            '비고': '',
        })
    
    return parsed
