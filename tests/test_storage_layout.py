import asyncio

from opendms.storage import LocalStorage, layout


def test_file_key_folder_and_collisions(tmp_path):
    st = LocalStorage(str(tmp_path))

    async def go():
        k, n = await layout.file_key(st, 7, None, "a.pdf", b"one")
        assert (k, n) == ("dokumenti/DVS-7/datnes/a.pdf", "a.pdf")
        await st.put(k, b"one")
        # same bytes → same key; different bytes → suffixed name
        assert await layout.file_key(st, 7, None, "a.pdf", b"one") == (k, "a.pdf")
        k2, n2 = await layout.file_key(st, 7, None, "a.pdf", b"two")
        assert (k2, n2) == ("dokumenti/DVS-7/datnes/a-2.pdf", "a-2.pdf")
        uid = "LV-DOK:05-0000:2026:01a13172-0000-7000-8000-000000000000"
        k3, _ = await layout.file_key(st, 7, uid, "a.pdf", b"x")
        assert k3.startswith("dokumenti/LV-DOK_05-0000_2026_01a13172") and k3.endswith("/datnes/a.pdf")

    asyncio.run(go())
