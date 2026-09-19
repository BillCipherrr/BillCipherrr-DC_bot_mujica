"""播放流程需要的最小環境（不持有 discord.Interaction）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


@dataclass(frozen=True)
class PlayContext:
    """播放流程真正用到的三樣東西：哪個 guild、往哪個文字頻道發訊息、由誰觸發。

    播放會持續數小時，且 after 回呼、重試、閒置計時器都會回頭使用它；
    這裡刻意不持有 Interaction（其 response/followup token 只有 15 分鐘有效，
    播放流程也用不到那些功能），讓依賴範圍一目了然，測試也不必偽造 Interaction。
    `user` 是觸發這一輪播放的人：推薦歌曲的個人偏好，以及語音斷線時要重連到的
    頻道，都以這個人為準。
    """

    guild: discord.Guild
    channel: discord.abc.Messageable | None
    user: discord.Member | discord.User

    @classmethod
    def from_interaction(cls, interaction: discord.Interaction) -> PlayContext:
        return cls(guild=interaction.guild, channel=interaction.channel, user=interaction.user)
