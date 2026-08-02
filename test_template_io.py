"""Test: run_excel.py 的中文模板读写层。
Run: python test_template_io.py
"""
from openpyxl import Workbook

import run_excel
from run_excel import (_sheet_matches_template, _read_pending_rows,
                       _write_result_row, EXPECTED_HEADERS,
                       COL_DATE, COL_STATUS, COL_WEB_PRICE, COL_SHEIN_TITLE,
                       COL_EBAY_TITLE, COL_EBAY_PRICE, COL_STOCK)


def _template_sheet():
    wb = Workbook()
    ws = wb.active
    ws.title = "ZR1"
    for c, h in enumerate(EXPECTED_HEADERS, 1):
        ws.cell(1, c).value = h
    return wb, ws


def test_expected_headers_are_the_thirteen_chinese_names():
    assert EXPECTED_HEADERS == [
        "编号", "链接", "原价", "运费", "变体",
        "日期", "状态", "图片", "希音价格", "希音标题",
        "eBay标题", "eBay价格", "库存"], EXPECTED_HEADERS


def test_sheet_matches_only_when_b1_is_lianjie():
    wb, ws = _template_sheet()
    assert _sheet_matches_template(ws) is True
    ws.cell(1, 2).value = "Website"
    assert _sheet_matches_template(ws) is False


def test_old_english_sheet_is_rejected():
    wb = Workbook()
    ws = wb.active
    for c, h in enumerate(["Seq", "Website", "Price", "Date", "Status"], 1):
        ws.cell(1, c).value = h
    assert _sheet_matches_template(ws) is False
    assert _read_pending_rows(ws) == []


def test_reads_only_rows_with_url_and_empty_date_status():
    wb, ws = _template_sheet()
    ws.append([1, "http://a", 10.0, 2.99, "Black / M"])                  # 待处理
    ws.append([2, "http://b", None, None, None])                        # 待处理，C/D/E 空
    ws.append([3, "http://c", None, None, None, "2026-08-01", "Done"])   # 已完成
    ws.append([4, None, None, None, None])                              # 没链接
    ws.append([5, "http://e", None, None, None, "2026-08-01", None])     # 只有日期
    ws.append([6, "http://f", None, None, None, None, "Failed"])         # 只有状态
    pending = _read_pending_rows(ws)
    assert [p["seq"] for p in pending] == [1, 2], pending
    assert pending[0] == {"row": 2, "seq": 1, "url": "http://a",
                          "price": 10.0, "shipping": 2.99,
                          "variant_filter": "Black / M"}
    assert pending[1]["price"] is None
    assert pending[1]["shipping"] is None
    assert pending[1]["variant_filter"] == ""


def test_skips_rows_with_bad_seq_or_bad_numbers():
    wb, ws = _template_sheet()
    ws.append([None, "http://a", None, None, None])        # 没编号
    ws.append(["abc", "http://b", None, None, None])       # 编号非数字
    ws.append([3, "http://c", "十块", None, None])          # 原价非数字
    ws.append([4, "http://d", None, "免运费", None])         # 运费非数字
    ws.append([5, "http://e", 9.9, 0, None])               # 好行
    pending = _read_pending_rows(ws)
    assert [p["seq"] for p in pending] == [5], pending
    assert pending[0]["shipping"] == 0.0


def test_url_is_stripped():
    wb, ws = _template_sheet()
    ws.append([1, "  http://a  ", None, None, None])
    assert _read_pending_rows(ws)[0]["url"] == "http://a"


def test_write_result_row_writes_f_through_m():
    wb, ws = _template_sheet()
    ws.append([1, "http://a", None, None, None])
    _write_result_row(ws, row=2, date="2026-08-02", status="Done",
                      picture_path=None, web_price="9.99–14.99",
                      shein_title="Raw Title", ebay_title="eBay Title",
                      ebay_price=18.19, stock="Black-M: 12")
    assert ws.cell(2, COL_DATE).value == "2026-08-02"
    assert ws.cell(2, COL_STATUS).value == "Done"
    assert ws.cell(2, COL_WEB_PRICE).value == "9.99–14.99"
    assert ws.cell(2, COL_SHEIN_TITLE).value == "Raw Title"
    assert ws.cell(2, COL_EBAY_TITLE).value == "eBay Title"
    assert ws.cell(2, COL_EBAY_PRICE).value == 18.19
    assert ws.cell(2, COL_STOCK).value == "Black-M: 12"


def test_write_result_row_failed_writes_only_date_and_status():
    wb, ws = _template_sheet()
    ws.append([1, "http://a", None, None, None])
    _write_result_row(ws, row=2, date="2026-08-02", status="Failed")
    assert ws.cell(2, COL_DATE).value == "2026-08-02"
    assert ws.cell(2, COL_STATUS).value == "Failed"
    for col in (COL_WEB_PRICE, COL_SHEIN_TITLE, COL_EBAY_TITLE,
                COL_EBAY_PRICE, COL_STOCK):
        assert ws.cell(2, col).value is None, col


def test_numeric_web_price_stays_numeric():
    wb, ws = _template_sheet()
    ws.append([1, "http://a", None, None, None])
    _write_result_row(ws, row=2, date="2026-08-02", status="Done",
                      web_price=12.99)
    v = ws.cell(2, COL_WEB_PRICE).value
    assert isinstance(v, float) and v == 12.99, repr(v)


if __name__ == "__main__":
    test_expected_headers_are_the_thirteen_chinese_names()
    test_sheet_matches_only_when_b1_is_lianjie()
    test_old_english_sheet_is_rejected()
    test_reads_only_rows_with_url_and_empty_date_status()
    test_skips_rows_with_bad_seq_or_bad_numbers()
    test_url_is_stripped()
    test_write_result_row_writes_f_through_m()
    test_write_result_row_failed_writes_only_date_and_status()
    test_numeric_web_price_stays_numeric()
    print("ALL PASS")
