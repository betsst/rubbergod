from bs4 import BeautifulSoup
import discord
import datetime
from discord.ext import commands
import re
import requests

from config import app_config as config, messages
from repository import review_repo
import utils

config = config.Config
messages = messages.Messages
review_repo = review_repo.ReviewRepository()


class Review(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rev = Review_helper(bot)

    async def check_member(self, ctx):
        """Check if user is allowed to add/remove new review."""
        guild = self.bot.get_guild(config.guild_id)
        member = guild.get_member(ctx.message.author.id)
        if member is None:
            await ctx.send(utils.fill_message("review_not_on_server", user=ctx.message.author.mention))
            return False
        roles = member.roles
        verify = False
        for role in roles:
            if config.verification_role_id == role.id:
                verify = True
            if role.id in config.review_forbidden_roles:
                await ctx.send(utils.fill_message("review_add_denied", user=ctx.message.author.id))
                return False
        if not verify:
            await ctx.send(utils.fill_message("review_add_denied", user=ctx.message.author.id))
            return False
        return True

    @commands.cooldown(rate=5, per=20.0, type=commands.BucketType.user)
    @commands.group(aliases=["review"])
    async def reviews(self, ctx):
        """Group of commands for reviews.
        If not subcommand is invoked, try to find subject reviews specified by first argument
        """
        if ctx.invoked_subcommand is None:
            # show reviews
            args = ctx.message.content.split()[1:]
            if not args:
                await ctx.send(messages.review_format)
                return
            subject = args[0]
            embed = self.rev.list_reviews(subject.lower())
            if not embed:
                await ctx.send(messages.review_wrong_subject)
                return
            msg = await ctx.send(embed=embed)
            footer = msg.embeds[0].footer.text.split("|")[0]
            if msg.embeds[0].description[-1].isnumeric():
                if footer != "Review: 1/1 ":
                    await msg.add_reaction("⏪")
                    await msg.add_reaction("◀")
                    await msg.add_reaction("▶")
                await msg.add_reaction("👍")
                await msg.add_reaction("🛑")
                await msg.add_reaction("👎")
                if msg.embeds[0].fields[3].name == "Text page":
                    await msg.add_reaction("🔼")
                    await msg.add_reaction("🔽")

    @reviews.command()
    async def add(self, ctx, subject=None, tier: int = None, *args):
        """Add new review for `subject`"""
        if not await self.check_member(ctx):
            return
        if subject is None or tier is None:
            await ctx.send(messages.review_add_format)
            return
        if tier < 0 or tier > 4:
            await ctx.send(messages.review_tier)
            return
        author = ctx.message.author.id
        anonym = False
        if not ctx.guild:  # DM
            anonym = True
        if args:
            args = " ".join(args)
        args_len = len(args)
        if args_len == 0:
            args = None
        if not self.rev.add_review(author, subject.lower(), tier, anonym, args):
            await ctx.send(messages.review_wrong_subject)
        else:
            await ctx.send(messages.review_added)

    @reviews.command()
    async def remove(self, ctx, subject=None, id: int = None):
        """Remove review from DB. User is just allowed to remove his own review
        For admin it is possible to use 'id' as subject shorcut and delete review by its ID
        """
        if not await self.check_member(ctx):
            return
        if subject is None:
            if ctx.author.id == config.admin_id:
                await ctx.send(messages.review_remove_format_admin)
            else:
                await ctx.send(messages.review_remove_format)
        elif subject == "id":
            if ctx.author.id == config.admin_id:
                if id is None:
                    await ctx.send(messages.review_remove_id_format)
                else:
                    review_repo.remove(id)
                    await ctx.send(messages.review_remove_success)
            else:
                await ctx.send(utils.fill_message("insufficient_rights", user=ctx.author.id))
        else:
            subject = subject.lower()
            if self.rev.remove(str(ctx.message.author.id), subject):
                await ctx.send(messages.review_remove_success)
            else:
                await ctx.send(messages.review_remove_error)

    @commands.cooldown(rate=5, per=20.0, type=commands.BucketType.user)
    @commands.group()
    @commands.check(utils.is_bot_owner)
    async def subject(self, ctx):
        """Group of commands for managing subjects in DB"""
        if ctx.invoked_subcommand is None:
            await ctx.send(messages.subject_format)
            return

    @subject.command(name="add")
    async def subject_add(self, ctx, *subjects):
        """Manually adding subjects to DB"""
        for subject in subjects:
            subject = subject.lower()
            review_repo.add_subject(subject)
        await ctx.send(f"Zkratky `{subjects}` byli přidány.")

    @subject.command(name="remove")
    async def subject_remove(self, ctx, *subjects):
        """Manually removing subjects to DB"""
        for subject in subjects:
            subject = subject.lower()
            review_repo.get_subject(subject).delete()
        await ctx.send(f"Zkratky `{subjects}` byli odebrány.")

    @subject.command()
    async def update(self, ctx):
        """Updates subjects from web"""
        async with ctx.channel.typing():
            if not self.rev.update_subject_types("https://www.fit.vut.cz/study/program/18/.cs", False):
                await ctx.send(messages.subject_update_error)
                return
            for id in range(31, 47):
                if not self.rev.update_subject_types(f"https://www.fit.vut.cz/study/field/{id}/.cs", True):
                    await ctx.send(messages.subject_update_error)
                    return
            await ctx.send(messages.subject_update_success)

    @commands.command(aliases=["skratka", "zkratka", "wtf"])
    async def shortcut(self, ctx, shortcut=None):
        """Informations about subject specified by its shorcut"""
        if not shortcut:
            await ctx.send(utils.fill_message("shorcut_format", command=ctx.invoked_with))
            return
        subject = review_repo.get_subject_details(shortcut.lower())
        if not subject:
            await ctx.send(messages.review_wrong_subject)
            return
        embed = discord.Embed(title=subject.shortcut, description=subject.name)
        embed.add_field(name="Semestr", value=subject.semester)
        embed.add_field(name="Typ", value=subject.type)
        if subject.year:
            embed.add_field(name="Ročník", value=subject.year)
        embed.add_field(name="Kredity", value=subject.credits)
        embed.add_field(name="Ukončení", value=subject.end)
        embed.add_field(name="Karta předmětu", value=subject.card, inline=False)
        embed.timestamp = datetime.datetime.now(tz=datetime.timezone.utc)
        embed.set_footer(icon_url=ctx.author.avatar_url, text=ctx.author)
        await ctx.send(embed=embed)

    @commands.command()
    async def tierboard(self, ctx, type="V", sem="Z", year=""):
        """Board of suject based on average tier from reviews"""
        # TODO autochange sem based on week command?
        degree = None
        type = type.upper()
        if type == "HELP":
            await ctx.send(messages.tierboard_help)
            return
        sem = sem.upper()
        for role in ctx.author.roles:
            if "BIT" in role.name:
                degree = "BIT"
                if not year and type == "P":
                    if role.name == "4BIT+":
                        year = "3BIT"
                    elif role.name == "0BIT":
                        year = "1BIT"
                    else:
                        year = role.name
                break
            if "MIT" in role.name:
                degree = "MIT"
                if not year and type == "P":
                    year = ""
                    # TODO get programme from DB? or find all MIT P?
                break
        if not degree and not year:
            await ctx.send(messages.tierboard_missing_year)
            return
        board = review_repo.get_tierboard(type, sem, degree, year)
        output = ""
        cnt = 1
        for line in board:
            output += f"{cnt} - **{line.shortcut}**: {round(line.avg_tier, 1)}\n"
            cnt += 1
        embed = discord.Embed(title="Tierboard", description=output)
        embed.timestamp = datetime.datetime.now(tz=datetime.timezone.utc)
        embed.add_field(name="Semester", value=sem)
        embed.add_field(name="Typ", value=type)
        if year:
            degree = year
        embed.add_field(name="Program", value=degree)
        embed.set_footer(icon_url=ctx.author.avatar_url, text=f"{ctx.author} | ?tierboard help")
        await ctx.send(embed=embed)

    @reviews.error
    @subject.error
    async def review_error(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            await ctx.send(messages.review_add_format)
        if isinstance(error, commands.CheckFailure):
            await ctx.send(utils.fill_message("insufficient_rights", user=ctx.author.id))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        ctx = await utils.reaction_get_ctx(self.bot, payload)
        if ctx is None:
            return

        if (
            ctx["message"].embeds
            and ctx["message"].embeds[0].title is not discord.Embed.Empty
            and re.match(".* reviews", ctx["message"].embeds[0].title)
        ):
            subject = ctx["message"].embeds[0].title.split(" ", 1)[0].lower()
            footer = ctx["message"].embeds[0].footer.text.split("|")[0]
            pos = footer.find("/")
            try:
                page = int(footer[8:pos])
                max_page = int(footer[(pos + 1) :])
            except ValueError:
                await ctx["message"].edit(content=messages.reviews_page_e, embed=None)
                return
            description = ctx["message"].embeds[0].description
            if ctx["emoji"] in ["◀", "▶", "⏪"]:
                next_page = utils.pagination_next(ctx["emoji"], page, max_page)
                if next_page:
                    review = review_repo.get_subject_reviews(subject)
                    if review.count() >= next_page:
                        review = review.all()[next_page - 1].Review
                        next_page = str(next_page) + "/" + str(max_page)
                        embed = self.rev.make_embed(review, subject, description, next_page)
                        if embed.fields[3].name == "Text page":
                            await ctx["message"].add_reaction("🔼")
                            await ctx["message"].add_reaction("🔽")
                        else:
                            for emote in ctx["message"].reactions:
                                if emote.emoji == "🔼":
                                    await ctx["message"].remove_reaction("🔼", self.bot.user)
                                    await ctx["message"].remove_reaction("🔽", self.bot.user)
                                    break
                        await ctx["message"].edit(embed=embed)
            elif ctx["emoji"] in ["👍", "👎", "🛑"]:
                review = review_repo.get_subject_reviews(subject)[page - 1].Review
                if str(ctx["member"].id) != review.member_ID:
                    review_id = review.id
                    if ctx["emoji"] == "👍":
                        self.rev.add_vote(review_id, True, str(ctx["member"].id))
                    elif ctx["emoji"] == "👎":
                        self.rev.add_vote(review_id, False, str(ctx["member"].id))
                    elif ctx["emoji"] == "🛑":
                        review_repo.remove_vote(review_id, str(ctx["member"].id))
                    page = str(page) + "/" + str(max_page)
                    embed = self.rev.make_embed(review, subject, description, page)
                    await ctx["message"].edit(embed=embed)
            elif ctx["emoji"] in ["🔼", "🔽"]:
                if ctx["message"].embeds[0].fields[3].name == "Text page":
                    review = review_repo.get_subject_reviews(subject)
                    if review:
                        review = review[page - 1].Review
                        text_page = ctx["message"].embeds[0].fields[3].value
                        pos = ctx["message"].embeds[0].fields[3].value.find("/")
                        max_text_page = int(text_page[(pos + 1) :])
                        text_page = int(text_page[:pos])
                        next_text_page = utils.pagination_next(ctx["emoji"], text_page, max_text_page)
                        if next_text_page:
                            page = str(page) + "/" + str(max_page)
                            embed = self.rev.make_embed(review, subject, description, page)
                            embed = self.rev.change_text_page(review, embed, next_text_page, max_text_page)
                            await ctx["message"].edit(embed=embed)
            if ctx["message"].guild:  # cannot remove reaction in DM
                await ctx["message"].remove_reaction(ctx["emoji"], ctx["member"])


class Review_helper:
    """Helper class for reviews"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def make_embed(self, review, subject, description, page):
        """Create new embed for reviews"""
        embed = discord.Embed(title=f"{subject.upper()} reviews", description=description)
        colour = 0x6D6A69
        id = 0
        if review is not None:
            guild = self.bot.get_guild(config.guild_id)
            if review.anonym:
                author = "Anonym"
            else:
                author = guild.get_member(int(review.member_ID))
            embed.add_field(name="Author", value=author)
            embed.add_field(name="Tier", value=review.tier)
            embed.add_field(name="Date", value=review.date)
            text = review.text_review
            if text is not None:
                text_len = len(text)
                if text_len > 1024:
                    pages = text_len // 1024 + (text_len % 1024 > 0)
                    text = review.text_review[:1024]
                    embed.add_field(name="Text page", value=f"1/{pages}", inline=False)
                embed.add_field(name="Text", value=text, inline=False)
            likes = review_repo.get_votes_count(review.id, True)
            embed.add_field(name="Likes", value=f"👍{likes}")
            dislikes = review_repo.get_votes_count(review.id, False)
            embed.add_field(name="Dislikes", value=f"👎{dislikes}")
            diff = likes - dislikes
            if diff > 0:
                colour = 0x34CB0B
            elif diff < 0:
                colour = 0xCB410B
            id = review.id
            embed.add_field(name="Help", value=messages.reviews_reaction_help, inline=False)
        embed.set_footer(text=f"Review: {page} | ID: {id}")
        embed.timestamp = datetime.datetime.now(tz=datetime.timezone.utc)
        embed.colour = colour
        return embed

    def change_text_page(self, review, embed, new_page, max_page):
        """Function for scrolling in reviews text field"""
        text_index = 1024 * (new_page - 1)
        if len(review.text_review) < 1024 * new_page:
            text = review.text_review[text_index:]
        else:
            text = review.text_review[text_index : 1024 * new_page]
        embed.set_field_at(3, name="Text page", value=f"{new_page}/{max_page}")
        embed.set_field_at(4, name="Text", value=text, inline=False)
        return embed

    def add_review(self, author_id, subject, tier, anonym, text):
        """Add new review, if review with same author and subject exists -> update"""
        if not review_repo.get_subject(subject):
            return False
        update = review_repo.get_review_by_author_subject(author_id, subject)
        if update:
            review_repo.update_review(update.id, tier, anonym, text)
        else:
            review_repo.add_review(author_id, subject, tier, anonym, text)
        return True

    def list_reviews(self, subject):
        result = review_repo.get_subject(subject).first()
        if not result:
            return None
        reviews = review_repo.get_subject_reviews(subject)
        tier_cnt = reviews.count()
        name = review_repo.get_subject_details(subject).name
        if tier_cnt == 0:
            description = f"{name}\n*No reviews*"
            review = None
            page = "1/1"
        else:
            review = reviews[0].Review
            description = f"{name}\n**Average tier:** {round(reviews[0].avg_tier)}"
            page = f"1/{tier_cnt}"
        return self.make_embed(review, subject, description, page)

    def remove(self, author, subject):
        """Remove review from DB"""
        result = review_repo.get_review_by_author_subject(author, subject)
        if result:
            review_repo.remove(result.id)
            return True
        else:
            return False

    def add_vote(self, review_id, vote: bool, author):
        """Add/update vote for review"""
        relevance = review_repo.get_vote_by_author(review_id, author)
        if not relevance or relevance.vote != vote:
            review_repo.add_vote(review_id, vote, author)

    def update_subject_types(self, link, MIT):
        """Send request to `link`, parse page and find all subjects.
        Add new subjects to DB, if subject already exists update its years.
        For MITAI links please set `MIT` to True. 
        If update succeeded return True, otherwise False
        """
        response = requests.get(link)
        if response.status_code != 200:
            return False
        soup = BeautifulSoup(response.content, "html.parser")
        tables = soup.select("table")

        # remove last table with information about PVT and PVA subjects (applicable mainly for BIT)
        if len(tables) % 2:
            tables = tables[:-1]

        # specialization shortcut for correct year definition in DB
        specialization = soup.select("main p strong")[0].get_text()

        sem = 1
        year = 1
        for table in tables:
            rows = table.select("tbody tr")
            for row in rows:
                shortcut = row.find_all("th")[0].get_text()
                # update subject DB
                if not review_repo.get_subject(shortcut.lower()).first():
                    review_repo.add_subject(shortcut.lower())
                columns = row.find_all("td")
                type = columns[2].get_text()
                degree = "BIT"
                for_year = "VBIT"
                if type == "P":
                    if MIT and year > 2:
                        # any year
                        for_year = f"L{specialization}"
                    else:
                        for_year = f"{year}{specialization}"
                else:
                    if MIT:
                        for_year = "VMIT"
                if MIT:
                    degree = "MIT"
                detail = review_repo.get_subject_details(shortcut.lower())
                semester = "Z"
                if sem == 2:
                    semester = "L"
                if not detail:
                    # subject not in DB
                    review_repo.set_subject_details(
                        shortcut,
                        columns[0].get_text(),  # name
                        columns[1].get_text(),  # credits
                        semester,
                        columns[3].get_text(),  # end
                        columns[0].find("a").attrs["href"],  # link
                        type,
                        for_year,
                        degree,
                    )
                elif for_year not in detail.year.split(", "):
                    # subject already in DB with different year (applicable mainly for MIT)
                    if detail.type != type:
                        type += f", {detail.type}"
                    if detail.year:
                        for_year += f", {detail.year}"
                    review_repo.update_subject_type(shortcut, type, for_year)
                elif semester not in detail.semester.split(", "):
                    # subject already in DB with different semester (e.g. RET)
                    semester += f", {detail.semester}"
                    review_repo.update_subject_sem(shortcut, semester)
                elif degree not in detail.degree.split(", "):
                    # subject already in DB with different degree (e.g. RET)
                    degree += f", {detail.degree}"
                    review_repo.update_subject_degree(shortcut, degree)
            sem += 1
            if sem == 3:
                year += 1
                sem = 1
        return True


def setup(bot):
    bot.add_cog(Review(bot))
