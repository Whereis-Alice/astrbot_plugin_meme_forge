from __future__ import annotations

import asyncio
import io
import unittest
from types import SimpleNamespace

from astrbot.api import message_components as Comp
from PIL import Image, ImageDraw

from astrbot_plugin_meme_forge.core.collector import ParamsCollector
from astrbot_plugin_meme_forge.core.favorites import (
    FavoriteEntry,
    MemeOutputIndex,
    add_favorite,
    dump_favorites,
    normalize_favorites,
    remove_favorite,
)
from astrbot_plugin_meme_forge.main import MemeForgePlugin


def make_test_image(
    *,
    image_format: str = "PNG",
    size: tuple[int, int] = (320, 180),
    inverted: bool = False,
) -> bytes:
    background = "black" if inverted else "white"
    foreground = "white" if inverted else "black"
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 25, 145, 155), fill=foreground)
    draw.ellipse((185, 45, 285, 145), fill=foreground)
    output = io.BytesIO()
    options = {"quality": 82} if image_format == "JPEG" else {}
    image.save(output, format=image_format, **options)
    return output.getvalue()


class MemeOutputIndexTests(unittest.TestCase):
    def test_matches_reencoded_image_in_the_same_session(self) -> None:
        index = MemeOutputIndex(max_records=20)
        original = make_test_image(image_format="PNG")
        reencoded = make_test_image(image_format="JPEG")
        index.remember(
            original,
            session="test:group:1",
            key="bubble_tea",
            trigger="奶茶",
        )

        matched = index.match(reencoded, session="test:group:1")
        self.assertIsNotNone(matched)
        assert matched is not None
        self.assertEqual(matched.key, "bubble_tea")
        self.assertIsNone(index.match(reencoded, session="test:group:2"))

    def test_different_image_is_not_matched(self) -> None:
        index = MemeOutputIndex(max_records=20)
        index.remember(
            make_test_image(),
            session="test:group:1",
            key="bubble_tea",
            trigger="奶茶",
        )
        self.assertIsNone(
            index.match(
                make_test_image(inverted=True),
                session="test:group:1",
            )
        )

    def test_dump_can_be_loaded_again(self) -> None:
        index = MemeOutputIndex(max_records=20)
        image = make_test_image()
        index.remember(
            image,
            session="test:private:alice",
            key="demo",
            trigger="演示",
        )
        restored = MemeOutputIndex(index.dump(), max_records=20)
        matched = restored.match(image, session="test:private:alice")
        self.assertIsNotNone(matched)
        assert matched is not None
        self.assertEqual((matched.key, matched.trigger), ("demo", "演示"))

    def test_corrupted_persisted_hashes_do_not_break_matching(self) -> None:
        image = make_test_image()
        index = MemeOutputIndex(max_records=20)
        index.remember(
            image,
            session="test:private:alice",
            key="demo",
            trigger="演示",
        )
        valid_record = index.dump()[0]
        corrupted_dhash = {**valid_record, "dhash": "z" * 64}
        corrupted_sha = {**valid_record, "sha256": "z" * 64}

        restored = MemeOutputIndex(
            [corrupted_dhash, corrupted_sha],
            max_records=20,
        )

        self.assertEqual(len(restored.records), 1)
        self.assertIsNone(restored.records[0].dhash)
        self.assertIsNotNone(restored.match(image, session="test:private:alice"))
        self.assertIsNone(
            restored.match(
                make_test_image(image_format="JPEG"),
                session="test:private:alice",
            )
        )


class FavoriteEntryTests(unittest.TestCase):
    def test_add_deduplicates_moves_to_front_and_limits_size(self) -> None:
        favorites = [
            FavoriteEntry(key="one", trigger="一"),
            FavoriteEntry(key="two", trigger="二"),
        ]
        updated, is_new = add_favorite(
            favorites,
            FavoriteEntry(key="three", trigger="三"),
            max_favorites=2,
        )
        self.assertTrue(is_new)
        self.assertEqual([entry.key for entry in updated], ["three", "one"])

        updated, is_new = add_favorite(
            updated,
            FavoriteEntry(key="one", trigger="新的触发词"),
            max_favorites=2,
        )
        self.assertFalse(is_new)
        self.assertEqual(
            updated,
            [
                FavoriteEntry(key="one", trigger="新的触发词"),
                FavoriteEntry(key="three", trigger="三"),
            ],
        )

    def test_normalize_and_remove(self) -> None:
        raw = [
            {"key": "one", "trigger": "一"},
            {"key": "one", "trigger": "重复"},
            {"invalid": True},
        ]
        favorites = normalize_favorites(raw)
        self.assertEqual(favorites, [FavoriteEntry(key="one", trigger="一")])
        self.assertEqual(dump_favorites(favorites), [{"key": "one", "trigger": "一"}])
        updated, removed = remove_favorite(favorites, "one")
        self.assertTrue(removed)
        self.assertEqual(updated, [])


class FavoriteCommandTests(unittest.IsolatedAsyncioTestCase):
    class Event:
        def __init__(
            self,
            image: bytes,
            *,
            sender_id: str = "alice",
            reply_sender: str = "bot",
        ) -> None:
            self.unified_msg_origin = "test:group:100"
            self.sender_id = sender_id
            self.stopped = False
            self.reply = Comp.Reply(
                id="message-1",
                chain=[Comp.Image.fromBytes(image)],
                sender_id=reply_sender,
            )

        def get_messages(self):
            return [self.reply]

        def get_platform_name(self) -> str:
            return "test"

        def get_sender_id(self) -> str:
            return self.sender_id

        def get_self_id(self) -> str:
            return "bot"

        def stop_event(self) -> None:
            self.stopped = True

        @staticmethod
        def plain_result(text: str) -> str:
            return text

    async def asyncSetUp(self) -> None:
        self.image = make_test_image()
        self.meme = SimpleNamespace(
            key="bubble_tea",
            info=SimpleNamespace(keywords=["奶茶"]),
        )
        self.plugin = MemeForgePlugin.__new__(MemeForgePlugin)
        self.plugin.config = {"trigger_prefix": "meme", "max_favorites": 50}
        self.plugin.collector = ParamsCollector({})
        self.plugin._storage_lock = asyncio.Lock()
        self.plugin._output_index = MemeOutputIndex(max_records=20)
        self.plugin._output_index.remember(
            self.image,
            session="test:group:100",
            key="bubble_tea",
            trigger="奶茶",
        )
        self.plugin.engine = SimpleNamespace(
            resolve=lambda value: self.meme
            if value in {"bubble_tea", "奶茶"}
            else None,
            canonical_key=lambda value: "bubble_tea"
            if value in {"bubble_tea", "奶茶"}
            else None,
            get_keywords=lambda meme: list(meme.info.keywords),
        )
        self.storage: dict[str, object] = {}

        async def get_kv_data(key: str, default):
            return self.storage.get(key, default)

        async def put_kv_data(key: str, value) -> None:
            self.storage[key] = value

        self.plugin.get_kv_data = get_kv_data
        self.plugin.put_kv_data = put_kv_data

    async def asyncTearDown(self) -> None:
        await self.plugin.collector.close()

    @staticmethod
    async def collect_results(generator) -> list[str]:
        return [result async for result in generator]

    async def test_reply_favorite_is_persistent_and_user_scoped(self) -> None:
        event = self.Event(self.image)
        results = await self.collect_results(self.plugin.favorite_meme(event))
        self.assertTrue(event.stopped)
        self.assertIn("已收藏：奶茶", results[0])
        self.assertIn("/meme 奶茶", results[0])

        results = await self.collect_results(self.plugin.favorite_list(event))
        self.assertIn("bubble_tea", results[0])
        self.assertIn("/meme 奶茶", results[0])

        other_event = self.Event(self.image, sender_id="bob")
        results = await self.collect_results(self.plugin.favorite_list(other_event))
        self.assertIn("收藏夹还是空的", results[0])

    async def test_rejects_a_reply_to_another_user(self) -> None:
        event = self.Event(self.image, reply_sender="someone-else")
        results = await self.collect_results(self.plugin.favorite_meme(event))
        self.assertIn("只能收藏 Bot 发送的 meme", results[0])

    async def test_reports_the_oldest_favorite_removed_at_capacity(self) -> None:
        self.plugin.config["max_favorites"] = 1
        self.storage["meme_favorites_v1:test:alice"] = [
            {"key": "old", "trigger": "旧收藏"}
        ]

        results = await self.collect_results(
            self.plugin.favorite_meme(self.Event(self.image))
        )

        self.assertIn("收藏已达上限，已移除最早收藏：旧收藏", results[0])
        self.assertEqual(
            self.storage["meme_favorites_v1:test:alice"],
            [{"key": "bubble_tea", "trigger": "奶茶"}],
        )


if __name__ == "__main__":
    unittest.main()
