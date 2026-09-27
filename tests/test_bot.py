import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import discord
from discord import app_commands

from catfish.bot import CatfishClient, lookup
from catfish.data import DataStore, QueryError
from test_data import hero, snapshot


def message(content, *, bot=False, webhook_id=None):
    return SimpleNamespace(
        content=content, author=SimpleNamespace(bot=bot), webhook_id=webhook_id,
        channel=SimpleNamespace(send=AsyncMock()),
    )


def mode_snapshots():
    datasets = {mode: snapshot() for mode in ("aram", "standard")}
    for mode, data in datasets.items():
        data["mode"] = mode
        data["builds"]["zuljin"] = data["builds"]["azmodan"]
    datasets["standard"]["builds"]["zuljin"][1]["win_rate"] = 90
    datasets["standard"]["heroes"].append(hero("gazlowe", "Gazlowe"))
    return datasets


def application(*, enabled=False, limited=False):
    return SimpleNamespace(flags=SimpleNamespace(
        gateway_message_content=enabled, gateway_message_content_limited=limited,
    ))


def remote_command(name, command_type=discord.AppCommandType.chat_input):
    return SimpleNamespace(name=name, type=command_type, delete=AsyncMock())


def interaction():
    response = SimpleNamespace(is_done=Mock(return_value=False), send_message=AsyncMock())

    async def defer(**kwargs):
        response.is_done.return_value = True

    response.defer = AsyncMock(side_effect=defer)
    return SimpleNamespace(response=response, followup=SimpleNamespace(send=AsyncMock()))


class BotTests(unittest.IsolatedAsyncioTestCase):
    def client(self, store=None, guild_id=None):
        client = CatfishClient(store if store is not None else DataStore(), guild_id)
        self.addAsyncCleanup(client.close)
        return client

    async def test_message_intents_and_exact_slash_menu_with_optional_hero(self):
        store = DataStore()
        client = self.client(store)
        self.assertIs(client.store, store)
        self.assertTrue(client.intents.guilds)
        self.assertTrue(client.intents.messages)
        self.assertTrue(client.intents.message_content)
        self.assertFalse(client.intents.members)
        self.assertFalse(client.intents.presences)
        commands = client.tree.get_commands()
        self.assertEqual([command.name for command in commands], ["히오스"])
        command = commands[0].to_dict(client.tree)
        self.assertEqual(command["type"], discord.AppCommandType.chat_input.value)
        self.assertEqual([option["name"] for option in command["options"]], ["무영대", "빠대"])
        for subcommand in command["options"]:
            self.assertEqual(subcommand["type"], discord.AppCommandOptionType.subcommand.value)
            self.assertEqual(len(subcommand["options"]), 1)
            option = subcommand["options"][0]
            self.assertEqual(option["name"], "영웅")
            self.assertEqual(option["type"], discord.AppCommandOptionType.string.value)
            self.assertFalse(option["required"])
            self.assertFalse(option.get("autocomplete", False))
            self.assertFalse(option.get("choices"))

    async def test_slash_namespace_dispatches_both_modes_with_or_without_hero(self):
        datasets = mode_snapshots()
        for data in datasets.values():
            data["builds"]["xul"] = data["builds"]["azmodan"]
        store = SimpleNamespace(snapshot=Mock(side_effect=datasets.__getitem__))
        client = self.client(store)
        group = client.tree.get_command("히오스")
        for command_name, mode in (("무영대", "aram"), ("빠대", "standard")):
            for hero_name, expected_slug in ((None, None), ("줄진", "zuljin"), ("줄", "xul")):
                with self.subTest(command_name=command_name, hero_name=hero_name):
                    store.snapshot.reset_mock()
                    request = interaction()
                    namespace = SimpleNamespace(**({"영웅": hero_name} if hero_name else {}))
                    with patch("catfish.bot.render_builds", return_value=b"BUILDS") as builds, \
                            patch("catfish.bot.render_tier_list", return_value=b"TIERS") as tiers:
                        await group.get_command(command_name)._invoke_with_namespace(request, namespace)
                    store.snapshot.assert_called_once_with(mode)
                    request.response.defer.assert_awaited_once_with(thinking=True)
                    request.followup.send.assert_awaited_once()
                    result = request.followup.send.await_args.kwargs
                    self.addCleanup(result["file"].close)
                    self.assertIsInstance(result["embed"], discord.Embed)
                    if hero_name is None:
                        builds.assert_not_called()
                        tiers.assert_called_once()
                        self.assertIs(tiers.call_args.args[0], datasets[mode])
                        self.assertIn("전체 영웅 티어표", result["embed"].title)
                    else:
                        tiers.assert_not_called()
                        builds.assert_called_once()
                        self.assertIs(builds.call_args.args[0], datasets[mode])
                        self.assertEqual(builds.call_args.args[1]["short_name"], expected_slug)
                        self.assertEqual(result["embed"].title, f"{hero_name} · 추천 빌드")

    async def test_slash_query_error_after_defer_is_readable_and_ephemeral(self):
        client = self.client()
        command = client.tree.get_command("히오스").get_command("빠대")
        request = interaction()
        with patch("catfish.bot.lookup_mode", new=AsyncMock(side_effect=QueryError("영웅을 찾을 수 없습니다"))), \
                self.assertRaises(app_commands.CommandInvokeError) as raised:
            await command._invoke_with_namespace(request, SimpleNamespace(**{"영웅": "없는영웅"}))
        await client.tree.on_error(request, raised.exception)
        request.response.defer.assert_awaited_once()
        request.response.send_message.assert_not_awaited()
        request.followup.send.assert_awaited_once_with("영웅을 찾을 수 없습니다", ephemeral=True)

    async def test_slash_error_before_defer_uses_initial_ephemeral_response(self):
        client = self.client()
        command = client.tree.get_command("히오스").get_command("무영대")
        for error, expected in (
            (QueryError("데이터가 아직 없습니다"), "데이터가 아직 없습니다"),
            (RuntimeError("private detail"), "조회 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."),
        ):
            with self.subTest(error=type(error).__name__):
                request = interaction()
                wrapped = app_commands.CommandInvokeError(command, error)
                if isinstance(error, QueryError):
                    await client.tree.on_error(request, wrapped)
                else:
                    with self.assertLogs("catfish.bot", level="ERROR"):
                        await client.tree.on_error(request, wrapped)
                request.response.send_message.assert_awaited_once_with(expected, ephemeral=True)
                request.followup.send.assert_not_awaited()

    async def test_four_forms_and_aliases_use_correct_snapshot_and_response(self):
        datasets = mode_snapshots()
        aliases = [("무영대", "aram"), ("ㅁㅇㄷ", "aram"), ("빠대", "standard"),
                   ("ㅃㄷ", "standard"), ("영리", "standard"), ("ㅇㄹ", "standard")]
        for alias, mode in aliases:
            for hero_query in (False, True):
                with self.subTest(alias=alias, hero_query=hero_query):
                    store = SimpleNamespace(snapshot=Mock(side_effect=datasets.__getitem__))
                    with patch("catfish.bot.render_builds", return_value=b"BUILDS") as builds, \
                            patch("catfish.bot.render_tier_list", return_value=b"TIERS") as tiers:
                        embed, file = await lookup(store, f"줄진 {alias}" if hero_query else alias)
                    self.addCleanup(file.close)
                    store.snapshot.assert_called_once_with(mode)
                    self.assertIsInstance(embed, discord.Embed)
                    self.assertIsInstance(file, discord.File)
                    if hero_query:
                        tiers.assert_not_called()
                        self.assertIs(builds.call_args.args[0], datasets[mode])
                        self.assertEqual(builds.call_args.args[1]["short_name"], "zuljin")
                        recommendations = builds.call_args.args[2]
                        self.assertEqual(len(recommendations), 2 if mode == "aram" else 1)
                        self.assertEqual(file.filename, "builds.png")
                        self.assertIn("줄진", embed.title)
                        self.assertEqual(embed.fields, [])
                        self.assertEqual(embed.image.url, "attachment://builds.png")
                        self.assertIn(f"후보 4개 중 {len(recommendations)}개", embed.description)
                        self.assertIn("무작위 영웅 대전" if mode == "aram" else "빠른 대전 & 영웅 리그",
                                      embed.description)
                        self.assertIn("게임 수가 적으면 승률 변동이 큽니다.", embed.description)
                        self.assertIn("수집 2026-09-27 07:00 KST", embed.description)
                        self.assertIn("패치 2.55.17.98025", embed.description)
                        self.assertIn("Heroes Profile 저장 데이터", embed.description)
                        self.assertNotIn("승률 1위", embed.description)
                        self.assertNotIn("선택 수 1위", embed.description)
                        if mode == "aram":
                            self.assertEqual(
                                [(row["win_rate"], row["games_played"]) for row in recommendations],
                                [(80, 5), (60, 500)],
                            )
                            self.assertEqual(recommendations[0]["recommendation_labels"], ("승률 1위",))
                            self.assertEqual(recommendations[1]["recommendation_labels"], ("선택 수 1위",))
                        else:
                            self.assertEqual(recommendations[0]["win_rate"], 90)
                            self.assertEqual(recommendations[0]["games_played"], 500)
                            self.assertEqual(recommendations[0]["recommendation_labels"],
                                             ("승률 1위", "선택 수 1위"))
                    else:
                        builds.assert_not_called()
                        self.assertIs(tiers.call_args.args[0], datasets[mode])
                        self.assertCountEqual(
                            [row for rows in tiers.call_args.args[1].values() for row in rows],
                            datasets[mode]["heroes"],
                        )
                        self.assertEqual(file.filename, f"{mode}-tiers.png")
                        self.assertEqual(embed.image.url, f"attachment://{mode}-tiers.png")
                        self.assertEqual(embed.title,
                                         f"{'무영대' if mode == 'aram' else '빠대'} · 전체 영웅 티어표")

    async def test_tier_image_includes_all_ninety_heroes(self):
        data = snapshot()
        data["heroes"] = [hero(f"hero{i}", f"Hero {i}", 40 + i % 21, i) for i in range(90)]
        with patch("catfish.bot.render_tier_list", return_value=b"PNG") as render:
            embed, file = await lookup(SimpleNamespace(snapshot=Mock(return_value=data)), "무영대")
        self.addCleanup(file.close)
        tiers = render.call_args.args[1]
        self.assertEqual(list(tiers), ["S", "A", "B", "C", "D"])
        self.assertEqual(sum(map(len, tiers.values())), 90)
        self.assertIn("90명", embed.description)

    async def test_invalid_forms_do_not_load_data(self):
        store = SimpleNamespace(snapshot=Mock())
        for query in ("", "줄진", "줄진 모르는모드", "빠대 전체 통계", "무영대 줄진", "줄진 빠대 무영대"):
            with self.subTest(query=query), self.assertRaises(QueryError):
                await lookup(store, query)
        store.snapshot.assert_not_called()

    async def test_lookup_preserves_readable_data_errors(self):
        cases = [
            ("무영대", Mock(side_effect=QueryError("무영대 데이터가 아직 없습니다")), "무영대 데이터가 아직 없습니다"),
            ("없는영웅 무영대", Mock(return_value=snapshot()), "해당 영웅이 이 모드의 데이터에 없습니다"),
            ("줄진 무영대", Mock(return_value=snapshot()), "빌드 데이터가 아직 없습니다"),
        ]
        for query, snapshot_mock, error in cases:
            with self.subTest(query=query), self.assertRaisesRegex(QueryError, error):
                await lookup(SimpleNamespace(snapshot=snapshot_mock), query)

    async def test_message_dispatches_only_query_and_sends_embed_and_file(self):
        client = self.client()
        embed, file = object(), object()
        for content, query in [("/히오스 무영대", "무영대"), ("/히오스 빠대", "빠대"),
                               ("/히오스 줄진 무영대", "줄진 무영대"),
                               ("/히오스\t줄진 빠대", "줄진 빠대"), ("/히오스", "")]:
            with self.subTest(content=content):
                request = message(content)
                with patch("catfish.bot.lookup", new=AsyncMock(return_value=(embed, file))) as handler:
                    await client.on_message(request)
                handler.assert_awaited_once_with(client.store, query)
                request.channel.send.assert_awaited_once_with(embed=embed, file=file)

    async def test_unrelated_messages_bots_and_webhooks_are_ignored(self):
        client = self.client()
        requests = [message(content) for content in
                    ("안녕", "히오스 빠대", "/히오스상세", "/히오스줄진 빠대", "/히오스/빠대")]
        requests.extend([message("/히오스 빠대", bot=True), message("/히오스 빠대", webhook_id=123)])
        with patch("catfish.bot.lookup", new=AsyncMock()) as handler:
            for request in requests:
                await client.on_message(request)
                request.channel.send.assert_not_awaited()
        handler.assert_not_awaited()

    async def test_query_error_is_sent_as_plain_readable_message(self):
        client = self.client()
        request = message("/히오스 없는영웅 빠대")
        with patch("catfish.bot.lookup", new=AsyncMock(side_effect=QueryError("영웅을 찾을 수 없습니다"))):
            await client.on_message(request)
        request.channel.send.assert_awaited_once_with("영웅을 찾을 수 없습니다")

    async def test_unexpected_lookup_error_sends_generic_message(self):
        client = self.client()
        request = message("/히오스 빠대")
        with patch("catfish.bot.lookup", new=AsyncMock(side_effect=RuntimeError("private detail"))), \
                self.assertLogs("catfish.bot", level="ERROR"):
            await client.on_message(request)
        request.channel.send.assert_awaited_once_with("조회 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")

    async def test_setup_cleans_stale_commands_and_updates_active_guild_command(self):
        client = self.client(guild_id=123)
        global_commands = [remote_command("히오스"), remote_command("히오스상세"), remote_command("다른명령")]
        guild_commands = [remote_command("히오스"), remote_command("히오스상세"),
                          remote_command("히오스", discord.AppCommandType.user)]
        with patch.object(CatfishClient, "application", new_callable=PropertyMock,
                          return_value=application(enabled=True)), \
                patch.object(client.tree, "fetch_commands", new=AsyncMock(
                    side_effect=[global_commands, guild_commands])) as fetch, \
                patch.object(client.tree, "copy_global_to", wraps=client.tree.copy_global_to) as copy, \
                patch.object(client.tree, "sync", new=AsyncMock()) as sync:
            await client.setup_hook()
        self.assertEqual(fetch.await_count, 2)
        scopes = [call.kwargs.get("guild") for call in fetch.await_args_list]
        self.assertIsNone(scopes[0])
        self.assertEqual(scopes[1].id, 123)
        for command in global_commands[:2]:
            command.delete.assert_awaited_once_with()
        global_commands[2].delete.assert_not_awaited()
        guild_commands[0].delete.assert_not_awaited()
        guild_commands[1].delete.assert_awaited_once_with()
        guild_commands[2].delete.assert_not_awaited()
        copy.assert_called_once()
        self.assertEqual(copy.call_args.kwargs["guild"].id, 123)
        sync.assert_awaited_once()
        self.assertEqual(sync.await_args.kwargs["guild"].id, 123)
        self.assertEqual([command.name for command in client.tree.get_commands(guild=scopes[1])], ["히오스"])

    async def test_setup_accepts_limited_message_content_flag_without_guild(self):
        client = self.client()
        commands = [remote_command("히오스"), remote_command("히오스상세"), remote_command("다른명령")]
        with patch.object(CatfishClient, "application", new_callable=PropertyMock,
                          return_value=application(limited=True)), \
                patch.object(client.tree, "fetch_commands", new=AsyncMock(return_value=commands)) as fetch, \
                patch.object(client.tree, "copy_global_to") as copy, \
                patch.object(client.tree, "sync", new=AsyncMock()) as sync:
            await client.setup_hook()
        fetch.assert_awaited_once()
        self.assertIsNone(fetch.await_args.kwargs.get("guild"))
        commands[0].delete.assert_not_awaited()
        commands[1].delete.assert_awaited_once_with()
        commands[2].delete.assert_not_awaited()
        copy.assert_not_called()
        sync.assert_awaited_once_with()

    async def test_missing_message_content_flag_blocks_legacy_cleanup(self):
        client = self.client(guild_id=123)
        with patch.object(CatfishClient, "application", new_callable=PropertyMock,
                          return_value=application()), \
                patch.object(client.tree, "fetch_commands", new=AsyncMock()) as fetch, \
                self.assertRaisesRegex(QueryError, "Message Content Intent"):
            await client.setup_hook()
        fetch.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
