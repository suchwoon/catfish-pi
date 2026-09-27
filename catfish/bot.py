"""Two guided slash commands, with literal chat shortcuts for mode aliases."""

import asyncio
import io
import logging

import discord
from discord import app_commands

from .data import MODES, DataStore, QueryError, find_hero, recommended_builds, source_note, tier_rows
from .heroes import display_name
from .query import MODE_LABELS, parse_query
from .render import render_builds, render_tier_list

log = logging.getLogger(__name__)


def image_embed(title: str, description: str, filename: str, data: bytes) -> tuple[discord.Embed, discord.File]:
    embed = discord.Embed(title=title, description=description, colour=0x9D7BFF)
    embed.set_image(url=f"attachment://{filename}")
    return embed, discord.File(io.BytesIO(data), filename=filename)


async def lookup(store: DataStore, query: str) -> tuple[discord.Embed, discord.File]:
    mode, hero_name = parse_query(query)
    return await lookup_mode(store, mode, hero_name)


async def lookup_mode(store: DataStore, mode: str, hero_name: str | None = None) -> tuple[discord.Embed, discord.File]:
    snapshot = await asyncio.to_thread(store.snapshot, mode)
    if hero_name is None:
        image = await asyncio.to_thread(render_tier_list, snapshot, tier_rows(snapshot))
        description = (
            f"전체 {len(snapshot['heroes'])}명 · 승률 구간별 S/A/B/C/D · 같은 티어는 승률순\n"
            f"{source_note(snapshot)}"
        )
        return image_embed(f"{MODE_LABELS[mode]} · 전체 영웅 티어표", description, f"{mode}-tiers.png", image)

    hero = find_hero(snapshot, hero_name)
    builds = recommended_builds(snapshot, hero)
    image = await asyncio.to_thread(render_builds, snapshot, hero, builds)
    candidate_count = len(snapshot["builds"][hero["short_name"]])
    description = (
        f"{MODES[mode]} · 후보 {candidate_count}개 중 {len(builds)}개\n"
        "게임 수가 적으면 승률 변동이 큽니다.\n"
        f"{source_note(snapshot)}"
    )
    return image_embed(f"{display_name(hero)} · 추천 빌드", description, "builds.png", image)


class HotsCommands(app_commands.Group):
    def __init__(self, store: DataStore):
        super().__init__(name="히오스", description="무영대·빠대 전체 티어표와 영웅 빌드")
        self.store = store

    # Use free text so stale autocomplete choices cannot replace a Korean name
    # while its last syllable is still being composed by the input method.
    @app_commands.command(name="무영대", description="전체 티어표 · 영웅 이름을 입력하면 빌드")
    @app_commands.rename(hero_name="영웅")
    @app_commands.describe(hero_name="영웅 이름 입력 (예: 줄진), 비우면 전체 티어표")
    async def aram(self, interaction: discord.Interaction, hero_name: str | None = None) -> None:
        await self.send_result(interaction, "aram", hero_name)

    @app_commands.command(name="빠대", description="빠대·영리 전체 티어표 · 영웅 이름을 입력하면 빌드")
    @app_commands.rename(hero_name="영웅")
    @app_commands.describe(hero_name="영웅 이름 입력 (예: 줄진), 비우면 전체 티어표")
    async def standard(self, interaction: discord.Interaction, hero_name: str | None = None) -> None:
        await self.send_result(interaction, "standard", hero_name)

    async def send_result(self, interaction: discord.Interaction, mode: str, hero_name: str | None) -> None:
        await interaction.response.defer(thinking=True)
        embed, file = await lookup_mode(self.store, mode, hero_name)
        await interaction.followup.send(embed=embed, file=file)


class CatfishClient(discord.Client):
    def __init__(self, store: DataStore, guild_id: int | None = None):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.store = store
        self.guild_id = guild_id
        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(HotsCommands(store))
        self.tree.on_error = self.command_error

    async def setup_hook(self) -> None:
        flags = self.application.flags
        if not (flags.gateway_message_content or flags.gateway_message_content_limited):
            raise QueryError(
                "채팅 명령을 읽으려면 Discord Developer Portal의 Bot 설정에서 "
                "Message Content Intent를 켜고 봇을 다시 실행해 주세요."
            )
        scopes = [None]
        if self.guild_id:
            scopes.append(discord.Object(id=self.guild_id))
        for guild in scopes:
            for command in await self.tree.fetch_commands(guild=guild):
                stale_global = guild is None and self.guild_id is not None and command.name == "히오스"
                if command.type == discord.AppCommandType.chat_input and (command.name == "히오스상세" or stale_global):
                    await command.delete()
                    log.info("Removed legacy slash command: %s", command.name)
        if self.guild_id:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            commands = await self.tree.sync(guild=guild)
        else:
            commands = await self.tree.sync()
        log.info("Registered %s command group(s): /히오스 무영대, /히오스 빠대", len(commands))

    async def on_ready(self) -> None:
        log.info("Catfish ready: %s · /히오스 슬래시 명령과 채팅 단축 입력", self.user)

    async def command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, QueryError):
            message = str(original)
        else:
            log.error("Hots slash command failed", exc_info=(type(original), original, original.__traceback__))
            message = "조회 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id is not None:
            return
        parts = message.content.split(maxsplit=1)
        if not parts or parts[0] != "/히오스":
            return
        query = parts[1] if len(parts) == 2 else ""
        try:
            embed, file = await lookup(self.store, query)
        except QueryError as error:
            await message.channel.send(str(error))
        except Exception:
            log.exception("Hots lookup failed")
            await message.channel.send("조회 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
        else:
            await message.channel.send(embed=embed, file=file)
