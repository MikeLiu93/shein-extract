"""Test: 保存 Excel 不能把原文件写坏，图片必须在 add 时就读进内存。

背景（2026-08-06）：员工的汇总表跑完后损坏，文件里躺着 40 张图但没有
[Content_Types].xml。原因是 openpyxl 按路径持有图片、到 wb.save() 才回磁盘
重读，某张读失败就在流式写 zip 的中途抛异常 —— 而 wb.save() 是直接往目标
文件上写的，原内容已经没了。

Run: python test_excel_atomic_save.py
"""
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage

from shein_scraper import save_workbook_atomic, _add_picture_to_cell


def _good_workbook(path: Path, marker: str = "原始数据"):
    wb = Workbook()
    ws = wb.active
    ws["A1"] = marker
    for r in range(2, 200):
        ws.cell(r, 1, f"row{r}")
    wb.save(path)
    return path


def _make_webp(path: Path, size=(120, 160), color=(200, 30, 30)):
    PILImage.new("RGB", size, color).save(path, format="WEBP")
    return path


def _is_openable(path: Path) -> bool:
    try:
        load_workbook(path)
        return True
    except Exception:
        return False


# ── save_workbook_atomic ────────────────────────────────────────────────────

def test_atomic_save_writes_new_content_on_success():
    tmp = Path(tempfile.mkdtemp())
    try:
        target = tmp / "表.xlsx"
        _good_workbook(target, "旧内容")
        wb = Workbook()
        wb.active["A1"] = "新内容"
        save_workbook_atomic(wb, target)
        assert load_workbook(target).active["A1"].value == "新内容"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _HalfWrittenWorkbook:
    """保存到一半就炸的工作簿替身：先写出半截 zip，再抛异常。

    以前这里用「图片文件被删掉」来制造失败，现在保存前会把读不出来的图摘掉，
    那条路不再炸了（见 test_broken_image_is_dropped_instead_of_killing_save），
    所以改用替身来守住原子性本身。
    """
    worksheets = ()

    def save(self, path):
        Path(path).write_bytes(b"PK\x03\x04 half written, no [Content_Types].xml")
        raise OSError("磁盘写到一半没了")


def test_atomic_save_leaves_original_intact_when_save_raises():
    """核心保证：保存中途炸了，原文件必须一个字节都没变。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        target = tmp / "重要总表.xlsx"
        _good_workbook(target, "员工积累了几个月的数据")
        before = target.read_bytes()

        try:
            save_workbook_atomic(_HalfWrittenWorkbook(), target)
            raised = False
        except Exception:
            raised = True

        assert raised, "保存该失败却成功了，测试前提不成立"
        assert target.read_bytes() == before, "原文件被改动了"
        assert _is_openable(target), "原文件损坏了"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_atomic_save_leaves_no_temp_files_behind():
    tmp = Path(tempfile.mkdtemp())
    try:
        target = tmp / "表.xlsx"
        _good_workbook(target)
        try:
            save_workbook_atomic(_HalfWrittenWorkbook(), target)
        except Exception:
            pass
        leftovers = [p.name for p in tmp.iterdir() if p.name != target.name]
        assert leftovers == [], f"留下了临时文件: {leftovers}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_broken_image_is_dropped_instead_of_killing_save():
    """图片读不出来只该少一张图，整张表还得存下去。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        img = _make_webp(tmp / "victim.webp")
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "别丢了我"
        ws.add_image(XLImage(str(img)), "H2")   # 按路径持有，不是 _add_picture_to_cell
        img.unlink()                            # 保存时 _data() 读不到

        target = tmp / "out.xlsx"
        save_workbook_atomic(wb, target)        # 不该抛
        assert load_workbook(target).active["A1"].value == "别丢了我"
        media = [n for n in zipfile.ZipFile(target).namelist()
                 if n.startswith("xl/media/")]
        assert media == [], media
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_workbook_is_verified_before_anything_touches_the_destination():
    """openpyxl 绝不能直接往目标目录里流式写。

    目标一般是 Google Drive 的虚拟盘：刚写完的大文件立刻读回来经常还没落地，
    `zipfile.ZipFile()` 直接 BadZipFile —— 文件是好的，是「写完马上读回」这一眼
    不可靠（2026-08-17 现场，57MB 的总表）。所以自检必须在本地盘上做完，
    目标盘只接一次已经验证过的整文件拷贝。
    """
    import shein_scraper
    tmp = Path(tempfile.mkdtemp())
    try:
        dest_dir = tmp / "云盘"
        dest_dir.mkdir()
        target = dest_dir / "总表.xlsx"

        written_to = []
        orig = shein_scraper._write_workbook_to_temp

        def spy(wb, path):
            written_to.append(Path(path))
            return orig(wb, path)

        shein_scraper._write_workbook_to_temp = spy
        try:
            wb = Workbook()
            wb.active["A1"] = "x"
            save_workbook_atomic(wb, target)
        finally:
            shein_scraper._write_workbook_to_temp = orig

        assert written_to, "根本没调用 _write_workbook_to_temp"
        for p in written_to:
            assert dest_dir not in p.parents, f"openpyxl 直接写进了目标目录: {p}"
        assert _is_openable(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_save_survives_a_destination_that_lies_on_read_back():
    """目标盘刚写完的文件读回来头一下是坏的 —— 保存仍然必须成功。

    Google Drive 虚拟盘上 57MB 的总表就是这样：`wb.save(tmp)` 成功，紧接着
    `zipfile.ZipFile(tmp)` 抛 BadZipFile（2026-08-17 现场）。文件其实是好的，
    是那一眼读回来不可靠。3.9.0 的 `_verify_xlsx_integrity` 对 `BadZipFile`
    做了短暂重试，一两次之后 Drive 就把真实字节服务出来了。
    """
    import shein_scraper
    tmp = Path(tempfile.mkdtemp())
    try:
        dest_dir = tmp / "云盘"
        dest_dir.mkdir()
        target = dest_dir / "总表.xlsx"

        real_zipfile = shein_scraper.zipfile.ZipFile
        lie_counts: dict = {}

        class LyingOnFirstZipFile(real_zipfile):
            """前 2 次假读失败，第 3 次服务真实字节 —— 模拟 Drive 瞬时假读。"""
            def __init__(self, file, *a, **kw):
                key = str(file)
                if dest_dir in Path(key).parents:
                    n = lie_counts.get(key, 0)
                    lie_counts[key] = n + 1
                    if n < 2:
                        raise zipfile.BadZipFile("File is not a zip file")
                super().__init__(file, *a, **kw)

        shein_scraper.zipfile.ZipFile = LyingOnFirstZipFile
        try:
            img = _make_webp(tmp / "img_001.webp")
            wb = Workbook()
            wb.active["A1"] = "抓了一整轮的结果"
            _add_picture_to_cell(wb.active, 2, 8, img)
            save_workbook_atomic(wb, target)
        finally:
            shein_scraper.zipfile.ZipFile = real_zipfile

        assert _is_openable(target)
        assert load_workbook(target).active["A1"].value == "抓了一整轮的结果"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_atomic_save_creates_file_that_did_not_exist():
    tmp = Path(tempfile.mkdtemp())
    try:
        target = tmp / "全新.xlsx"
        wb = Workbook()
        wb.active["A1"] = "x"
        save_workbook_atomic(wb, target)
        assert target.is_file() and _is_openable(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── _add_picture_to_cell 必须在 add 时就把字节读进内存 ────────────────────────

def test_picture_bytes_are_read_eagerly_not_at_save_time():
    """add 完之后把源文件删掉，保存仍然要成功 —— 证明字节已经在内存里。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        img = _make_webp(tmp / "img_001.webp")
        wb = Workbook()
        ws = wb.active
        h = _add_picture_to_cell(ws, 2, 8, img)
        assert h > 0, "图片没嵌进去"
        img.unlink()                       # 源文件消失

        target = tmp / "out.xlsx"
        save_workbook_atomic(wb, target)   # 不该抛
        z = zipfile.ZipFile(target)
        media = [n for n in z.namelist() if n.startswith("xl/media/")]
        assert len(media) == 1, media
        assert "[Content_Types].xml" in z.namelist()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unreadable_image_is_skipped_not_raised():
    """坏图只该少一张图，不该把整次保存拖下水。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        bad = tmp / "img_001.webp"
        bad.write_bytes("这不是图片".encode("utf-8"))
        wb = Workbook()
        ws = wb.active
        assert _add_picture_to_cell(ws, 2, 8, bad) == 0
        assert len(ws._images) == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_image_file_is_skipped():
    wb = Workbook()
    ws = wb.active
    assert _add_picture_to_cell(ws, 2, 8, Path("__no_such_image__.webp")) == 0
    assert len(ws._images) == 0


def test_webp_is_converted_so_excel_can_show_it():
    """Excel 不认 webp。嵌进去的必须是 Excel 认的格式（现在是 jpeg）。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        img = _make_webp(tmp / "img_001.webp")
        wb = Workbook()
        _add_picture_to_cell(wb.active, 2, 8, img)
        target = tmp / "out.xlsx"
        save_workbook_atomic(wb, target)
        media = [n for n in zipfile.ZipFile(target).namelist()
                 if n.startswith("xl/media/")]
        assert media and all(n.lower().endswith((".jpeg", ".jpg", ".png"))
                             for n in media), media
        assert _is_openable(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── 图片体积：够看就行，别把表撑到 Web 版打不开 ──────────────────────────────

def _big_photo(path: Path, size=(1200, 1600)):
    """造一张接近真实商品图尺寸的图（有细节，不然压完太小测不出问题）。"""
    im = PILImage.new("RGB", size)
    px = im.load()
    for y in range(0, size[1], 4):
        for x in range(0, size[0], 4):
            c = ((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256)
            for dy in range(4):
                for dx in range(4):
                    if x + dx < size[0] and y + dy < size[1]:
                        px[x + dx, y + dy] = c
    im.save(path, format="WEBP", quality=95)
    return path


def test_embedded_picture_is_small():
    """一张原图 1200×1600 的商品图，嵌进去不该还是几百 KB。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        img = _big_photo(tmp / "img_001.webp")
        wb = Workbook()
        ws = wb.active
        assert _add_picture_to_cell(ws, 2, 8, img) > 0
        target = tmp / "out.xlsx"
        save_workbook_atomic(wb, target)

        z = zipfile.ZipFile(target)
        media = [n for n in z.namelist() if n.startswith("xl/media/")]
        assert len(media) == 1, media
        stored = z.getinfo(media[0]).file_size
        assert stored < 60_000, f"嵌进去的图还是太大: {stored} 字节"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_picture_is_still_big_enough_to_look_at():
    """够看就行，但别糊到没法看：存下来的像素不能低于显示尺寸。"""
    from shein_scraper import PICTURE_MAX_HEIGHT_PX
    tmp = Path(tempfile.mkdtemp())
    try:
        img = _big_photo(tmp / "img_001.webp")
        wb = Workbook()
        ws = wb.active
        _add_picture_to_cell(ws, 2, 8, img)
        xl_img = ws._images[0]
        assert xl_img.height <= PICTURE_MAX_HEIGHT_PX, xl_img.height

        target = tmp / "out.xlsx"
        save_workbook_atomic(wb, target)
        z = zipfile.ZipFile(target)
        name = [n for n in z.namelist() if n.startswith("xl/media/")][0]
        with PILImage.open(BytesIO(z.read(name))) as stored:
            # 至少和显示尺寸一样大（实际存 2 倍），且保持原图长宽比
            assert stored.height >= xl_img.height, (stored.size, xl_img.height)
            assert abs(stored.width / stored.height - 1200 / 1600) < 0.02, stored.size
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_oversized_legacy_images_get_shrunk_on_save():
    """历史文件里的大 PNG，保存时顺手压小 —— 员工那份 57MB 的总表靠这个瘦身。"""
    from shein_scraper import PICTURE_MAX_BYTES
    tmp = Path(tempfile.mkdtemp())
    try:
        raw = BytesIO()
        with PILImage.open(_big_photo(tmp / "src.webp")) as im:
            im.save(raw, format="PNG")          # 老代码就是这么存的：整张原图 PNG
        raw.seek(0)
        assert len(raw.getvalue()) > PICTURE_MAX_BYTES

        wb = Workbook()
        wb.active.add_image(XLImage(raw), "H2")
        target = tmp / "out.xlsx"
        save_workbook_atomic(wb, target)

        z = zipfile.ZipFile(target)
        name = [n for n in z.namelist() if n.startswith("xl/media/")][0]
        assert z.getinfo(name).file_size < PICTURE_MAX_BYTES, z.getinfo(name).file_size
        assert _is_openable(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_workbook_with_images_can_be_saved_twice():
    """多 sheet 时每个 sheet 跑完存一次 —— 第二次不能因为图片被 close 掉而炸。

    openpyxl 的 Image._data() 读完字节就 fp.close()，而 fp 就是 ref 那个
    BytesIO。第一次 save 之后同一个 wb 再存就 ValueError: I/O operation on
    closed file，整轮在第二个 sheet 上中断（2026-08-17 现场）。
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        img = _make_webp(tmp / "img_001.webp")
        wb = Workbook()
        ws1 = wb.active
        ws1.title = "Test1"
        ws2 = wb.create_sheet("Test2")
        _add_picture_to_cell(ws1, 2, 8, img)
        target = tmp / "总表.xlsx"

        save_workbook_atomic(wb, target)          # sheet1 跑完
        _add_picture_to_cell(ws2, 2, 8, img)
        save_workbook_atomic(wb, target)          # sheet2 跑完 —— 以前在这里炸
        save_workbook_atomic(wb, target)          # 再来一次也要活着

        z = zipfile.ZipFile(target)
        media = [n for n in z.namelist() if n.startswith("xl/media/")]
        assert len(media) == 2, media
        assert "[Content_Types].xml" in z.namelist()
        assert _is_openable(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reloaded_workbook_images_survive_repeated_saves():
    """load_workbook 读出来的图也是 BytesIO ref —— 同样要能反复存。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        img = _make_webp(tmp / "img_001.webp")
        wb = Workbook()
        _add_picture_to_cell(wb.active, 2, 8, img)
        target = tmp / "已有图的总表.xlsx"
        save_workbook_atomic(wb, target)

        wb2 = load_workbook(target)
        assert len(wb2.active._images) == 1
        save_workbook_atomic(wb2, target)
        save_workbook_atomic(wb2, target)
        media = [n for n in zipfile.ZipFile(target).namelist()
                 if n.startswith("xl/media/")]
        assert len(media) == 1, media
        assert _is_openable(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_many_images_all_land():
    """60 张图全部落盘，且清单完整 —— 就是出事的那个规模。"""
    tmp = Path(tempfile.mkdtemp())
    try:
        wb = Workbook()
        ws = wb.active
        for i in range(1, 61):
            p = _make_webp(tmp / f"img_{i:03d}.webp", color=(i * 3 % 256, 40, 90))
            assert _add_picture_to_cell(ws, i + 1, 8, p) > 0
        target = tmp / "out.xlsx"
        save_workbook_atomic(wb, target)
        z = zipfile.ZipFile(target)
        media = [n for n in z.namelist() if n.startswith("xl/media/")]
        assert len(media) == 60, len(media)
        assert "[Content_Types].xml" in z.namelist()
        assert _is_openable(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_atomic_save_writes_new_content_on_success()
    test_atomic_save_leaves_original_intact_when_save_raises()
    test_atomic_save_leaves_no_temp_files_behind()
    test_workbook_is_verified_before_anything_touches_the_destination()
    test_save_survives_a_destination_that_lies_on_read_back()
    test_atomic_save_creates_file_that_did_not_exist()
    test_broken_image_is_dropped_instead_of_killing_save()
    test_picture_bytes_are_read_eagerly_not_at_save_time()
    test_unreadable_image_is_skipped_not_raised()
    test_missing_image_file_is_skipped()
    test_webp_is_converted_so_excel_can_show_it()
    test_embedded_picture_is_small()
    test_picture_is_still_big_enough_to_look_at()
    test_oversized_legacy_images_get_shrunk_on_save()
    test_workbook_with_images_can_be_saved_twice()
    test_reloaded_workbook_images_survive_repeated_saves()
    test_many_images_all_land()
    print("ALL PASS")
