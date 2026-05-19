import os
import json
import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")
LEAD_ROLE_NAME = os.getenv("LEAD_ROLE_NAME", "Lead")
DATA_FILE = "award_votes.json"

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"votes": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_lead(member: discord.Member) -> bool:
    return any(role.name.lower() == LEAD_ROLE_NAME.lower() for role in member.roles)


def calculate_objective_score(lifetime_ekp, highest_lifetime_ekp, monthly_ekp, highest_monthly_ekp):
    lifetime_score = 0 if highest_lifetime_ekp <= 0 else (lifetime_ekp / highest_lifetime_ekp) * 30
    monthly_score = 0 if highest_monthly_ekp <= 0 else (monthly_ekp / highest_monthly_ekp) * 30
    return round(lifetime_score, 2), round(monthly_score, 2), round(lifetime_score + monthly_score, 2)


def get_vote(vote_id):
    data = load_data()
    return data["votes"].get(vote_id)


def build_applicant_embed(vote_id, applicant):
    embed = discord.Embed(
        title=f"Armor Award Candidate: {applicant['name']}",
        color=discord.Color.purple()
    )
    embed.add_field(name="Vote ID", value=vote_id, inline=True)
    embed.add_field(name="Class", value=applicant["class_name"], inline=True)
    embed.add_field(name="Type", value=applicant["applicant_type"], inline=True)
    embed.add_field(name="Needs", value=applicant["needs"], inline=False)

    embed.add_field(name="Lifetime EKP", value=f"{applicant['lifetime_ekp']:,}", inline=True)
    embed.add_field(name="30-Day EKP", value=f"{applicant['monthly_ekp']:,}", inline=True)
    embed.add_field(name="Objective Score", value=f"{applicant['objective_score']} / 60", inline=True)

    embed.add_field(
        name="Lead Scoring Command",
        value=(
            f"`/score vote_id:{vote_id} applicant:{applicant['name']} role_value:12 upgrade_impact:13 conduct:9 notes:optional`\n\n"
            "Role Value: /15\n"
            "Upgrade Impact: /15\n"
            "Conduct/Reliability: /10"
        ),
        inline=False
    )
    return embed


def build_ranking_embed(vote_id):
    vote = get_vote(vote_id)
    if not vote:
        return discord.Embed(title="Vote not found", color=discord.Color.red())

    lines = []
    for applicant in vote["applicants"]:
        scores = applicant.get("scores", {})
        if scores:
            subjective_totals = [s["total"] for s in scores.values()]
            avg_subjective = sum(subjective_totals) / len(subjective_totals)
        else:
            avg_subjective = 0

        final_score = applicant["objective_score"] + avg_subjective
        lines.append({
            "name": applicant["name"],
            "objective": applicant["objective_score"],
            "subjective": round(avg_subjective, 2),
            "final": round(final_score, 2),
            "votes": len(scores)
        })

    lines.sort(key=lambda x: x["final"], reverse=True)

    description = ""
    for index, row in enumerate(lines, start=1):
        description += (
            f"**{index}. {row['name']}** — `{row['final']} / 100`\n"
            f"Objective: {row['objective']} / 60 | Lead Avg: {row['subjective']} / 40 | Votes: {row['votes']}\n\n"
        )

    return discord.Embed(
        title=f"Armor Award Rankings — {vote['title']}",
        description=description or "No applicants found.",
        color=discord.Color.gold()
    )


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")


@bot.tree.command(name="new_award_vote", description="Create a new armor award vote")
@app_commands.describe(
    vote_id="Short ID, example: dg-may-2026",
    title="Vote title, example: DG Legs/Boots Award",
    highest_lifetime_ekp="Highest lifetime EKP among eligible applicants",
    highest_monthly_ekp="Highest 30-day EKP among eligible applicants"
)
async def new_award_vote(
    interaction: discord.Interaction,
    vote_id: str,
    title: str,
    highest_lifetime_ekp: int,
    highest_monthly_ekp: int
):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can create award votes.", ephemeral=True)
        return

    data = load_data()
    if vote_id in data["votes"]:
        await interaction.response.send_message("That vote ID already exists.", ephemeral=True)
        return

    data["votes"][vote_id] = {
        "title": title,
        "highest_lifetime_ekp": highest_lifetime_ekp,
        "highest_monthly_ekp": highest_monthly_ekp,
        "applicants": []
    }
    save_data(data)

    await interaction.response.send_message(f"Created award vote: **{title}** with ID `{vote_id}`")


@bot.tree.command(name="add_candidate", description="Add a candidate to an armor award vote")
@app_commands.describe(
    vote_id="Vote ID",
    applicant="Toon name",
    class_name="Class, example: Mage",
    applicant_type="Main or Alt",
    needs="Armor needed, example: Legs + Boots",
    lifetime_ekp="Applicant lifetime EKP",
    monthly_ekp="Applicant 30-day EKP",
    discord_user="Optional: Discord user for self-vote blocking"
)
async def add_candidate(
    interaction: discord.Interaction,
    vote_id: str,
    applicant: str,
    class_name: str,
    applicant_type: str,
    needs: str,
    lifetime_ekp: int,
    monthly_ekp: int,
    discord_user: discord.Member | None = None
):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can add candidates.", ephemeral=True)
        return

    data = load_data()
    vote = data["votes"].get(vote_id)
    if not vote:
        await interaction.response.send_message("Vote ID not found.", ephemeral=True)
        return

    for existing in vote["applicants"]:
        if existing["name"].lower() == applicant.lower():
            await interaction.response.send_message("That candidate is already added.", ephemeral=True)
            return

    lt_score, monthly_score, objective_score = calculate_objective_score(
        lifetime_ekp,
        vote["highest_lifetime_ekp"],
        monthly_ekp,
        vote["highest_monthly_ekp"]
    )

    applicant_data = {
        "name": applicant,
        "class_name": class_name,
        "applicant_type": applicant_type,
        "needs": needs,
        "lifetime_ekp": lifetime_ekp,
        "monthly_ekp": monthly_ekp,
        "lifetime_score": lt_score,
        "monthly_score": monthly_score,
        "objective_score": objective_score,
        "discord_user_id": discord_user.id if discord_user else None,
        "scores": {}
    }

    vote["applicants"].append(applicant_data)
    save_data(data)

    await interaction.response.send_message(embed=build_applicant_embed(vote_id, applicant_data))


@bot.tree.command(name="bulk_add_candidates", description="Add multiple candidates to an armor award vote at once")
@app_commands.describe(
    vote_id="Vote ID",
    candidates="One line per candidate: Toon | Class | Main/Alt | Needs | Lifetime EKP | Monthly EKP"
)
async def bulk_add_candidates(
    interaction: discord.Interaction,
    vote_id: str,
    candidates: str
):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can add candidates.", ephemeral=True)
        return

    data = load_data()
    vote = data["votes"].get(vote_id)
    if not vote:
        await interaction.response.send_message("Vote ID not found.", ephemeral=True)
        return

    existing_names = {candidate["name"].lower() for candidate in vote["applicants"]}
    added = []
    skipped = []

    for raw_line in candidates.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = [part.strip() for part in line.split("|")]

        if len(parts) < 6:
            skipped.append(f"`{line}` — wrong format")
            continue

        toon_name = parts[0]
        class_name = parts[1]
        applicant_type = parts[2]
        needs = parts[3]

        try:
            lifetime_ekp = int(parts[4].replace(",", ""))
            monthly_ekp = int(parts[5].replace(",", ""))
        except ValueError:
            skipped.append(f"`{toon_name}` — EKP must be numbers")
            continue

        if toon_name.lower() in existing_names:
            skipped.append(f"`{toon_name}` — already added")
            continue

        lt_score, monthly_score, objective_score = calculate_objective_score(
            lifetime_ekp,
            vote["highest_lifetime_ekp"],
            monthly_ekp,
            vote["highest_monthly_ekp"]
        )

        applicant_data = {
            "name": toon_name,
            "class_name": class_name,
            "applicant_type": applicant_type,
            "needs": needs,
            "lifetime_ekp": lifetime_ekp,
            "monthly_ekp": monthly_ekp,
            "lifetime_score": lt_score,
            "monthly_score": monthly_score,
            "objective_score": objective_score,
            "discord_user_id": None,
            "scores": {}
        }

        vote["applicants"].append(applicant_data)
        existing_names.add(toon_name.lower())
        added.append(f"`{toon_name}` — objective {objective_score} / 60")

    save_data(data)

    message = "**Bulk candidates added:**
"
    message += "
".join(added) if added else "None"

    if skipped:
        message += "

**Skipped:**
" + "
".join(skipped)

    await interaction.response.send_message(message[:1900])


@bot.tree.command(name="score", description="Score an armor award candidate")
@app_commands.describe(
    vote_id="Vote ID",
    applicant="Toon name",
    role_value="Clan impact / role value, 0-15",
    upgrade_impact="Upgrade impact, 0-15",
    conduct="Conduct / reliability, 0-10",
    notes="Optional private reasoning note"
)
async def score(
    interaction: discord.Interaction,
    vote_id: str,
    applicant: str,
    role_value: int,
    upgrade_impact: int,
    conduct: int,
    notes: str = ""
):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can score candidates.", ephemeral=True)
        return

    if not (0 <= role_value <= 15 and 0 <= upgrade_impact <= 15 and 0 <= conduct <= 10):
        await interaction.response.send_message("Scores must be: Role 0-15, Upgrade 0-15, Conduct 0-10.", ephemeral=True)
        return

    data = load_data()
    vote = data["votes"].get(vote_id)
    if not vote:
        await interaction.response.send_message("Vote ID not found.", ephemeral=True)
        return

    target = None
    for candidate in vote["applicants"]:
        if candidate["name"].lower() == applicant.lower():
            target = candidate
            break

    if not target:
        await interaction.response.send_message("Candidate not found.", ephemeral=True)
        return

    if target.get("discord_user_id") == interaction.user.id:
        await interaction.response.send_message("You cannot score your own application.", ephemeral=True)
        return

    total = role_value + upgrade_impact + conduct
    target["scores"][str(interaction.user.id)] = {
        "lead_name": interaction.user.display_name,
        "role_value": role_value,
        "upgrade_impact": upgrade_impact,
        "conduct": conduct,
        "total": total,
        "notes": notes
    }

    save_data(data)

    await interaction.response.send_message(
        f"Score submitted for **{target['name']}**: `{total} / 40`",
        ephemeral=True
    )


@bot.tree.command(name="rankings", description="Show armor award rankings")
@app_commands.describe(vote_id="Vote ID")
async def rankings(interaction: discord.Interaction, vote_id: str):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can view rankings.", ephemeral=True)
        return

    await interaction.response.send_message(embed=build_ranking_embed(vote_id))


@bot.tree.command(name="candidate_card", description="Repost a candidate scorecard")
@app_commands.describe(vote_id="Vote ID", applicant="Toon name")
async def candidate_card(interaction: discord.Interaction, vote_id: str, applicant: str):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can view candidate cards.", ephemeral=True)
        return

    vote = get_vote(vote_id)
    if not vote:
        await interaction.response.send_message("Vote ID not found.", ephemeral=True)
        return

    for candidate in vote["applicants"]:
        if candidate["name"].lower() == applicant.lower():
            await interaction.response.send_message(embed=build_applicant_embed(vote_id, candidate))
            return

    await interaction.response.send_message("Candidate not found.", ephemeral=True)


@bot.tree.command(name="score_audit", description="View submitted lead scores for a candidate")
@app_commands.describe(vote_id="Vote ID", applicant="Toon name")
async def score_audit(interaction: discord.Interaction, vote_id: str, applicant: str):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can audit scores.", ephemeral=True)
        return

    vote = get_vote(vote_id)
    if not vote:
        await interaction.response.send_message("Vote ID not found.", ephemeral=True)
        return

    target = None
    for candidate in vote["applicants"]:
        if candidate["name"].lower() == applicant.lower():
            target = candidate
            break

    if not target:
        await interaction.response.send_message("Candidate not found.", ephemeral=True)
        return

    if not target["scores"]:
        await interaction.response.send_message("No scores submitted yet.", ephemeral=True)
        return

    lines = []
    for score_data in target["scores"].values():
        lines.append(
            f"**{score_data['lead_name']}** — {score_data['total']} / 40\n"
            f"Role: {score_data['role_value']} | Upgrade: {score_data['upgrade_impact']} | Conduct: {score_data['conduct']}\n"
            f"Notes: {score_data['notes'] or 'None'}"
        )

    embed = discord.Embed(
        title=f"Score Audit: {target['name']}",
        description="\n\n".join(lines),
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="score_template", description="Get an easy copy/paste scoring template for all candidates")
@app_commands.describe(vote_id="Vote ID")
async def score_template(interaction: discord.Interaction, vote_id: str):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can get scoring templates.", ephemeral=True)
        return

    vote = get_vote(vote_id)
    if not vote:
        await interaction.response.send_message("Vote ID not found.", ephemeral=True)
        return

    if not vote["applicants"]:
        await interaction.response.send_message("No candidates added yet.", ephemeral=True)
        return

    lines = []
    for candidate in vote["applicants"]:
        if candidate.get("discord_user_id") == interaction.user.id:
            lines.append(f"# SKIP SELF: {candidate['name']}")
        else:
            lines.append(f"{candidate['name']} | 0 | 0 | 0 | notes optional")

    template = "
".join(lines)

    message = (
        "Copy this, replace the 0s with scores, then paste it into `/bulk_score`.

"
        "Format: `Toon | Role /15 | Upgrade /15 | Conduct /10 | Notes`

"
        f"```txt
{template}
```"
    )

    await interaction.response.send_message(message[:1900], ephemeral=True)


@bot.tree.command(name="vote_summary", description="Show simple vote setup and progress")
@app_commands.describe(vote_id="Vote ID")
async def vote_summary(interaction: discord.Interaction, vote_id: str):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can view vote summaries.", ephemeral=True)
        return

    vote = get_vote(vote_id)
    if not vote:
        await interaction.response.send_message("Vote ID not found.", ephemeral=True)
        return

    lines = []
    for candidate in vote["applicants"]:
        score_count = len(candidate.get("scores", {}))
        lines.append(
            f"**{candidate['name']}** — {candidate['class_name']} {candidate['applicant_type']}
"
            f"Needs: {candidate['needs']} | Objective: {candidate['objective_score']} / 60 | Lead Scores: {score_count}"
        )

    embed = discord.Embed(
        title=f"Vote Summary — {vote['title']}",
        description="

".join(lines) or "No candidates added yet.",
        color=discord.Color.teal()
    )
    embed.add_field(
        name="Easy Lead Workflow",
        value="1. `/score_template`
2. Fill in scores
3. Paste into `/bulk_score`
4. Check `/rankings`",
        inline=False
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="bulk_score", description="Score multiple armor award candidates at once")
@app_commands.describe(
    vote_id="Vote ID",
    scores="One line per candidate: Toon | role /15 | upgrade /15 | conduct /10 | optional notes"
)
async def bulk_score(
    interaction: discord.Interaction,
    vote_id: str,
    scores: str
):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can score candidates.", ephemeral=True)
        return

    data = load_data()
    vote = data["votes"].get(vote_id)
    if not vote:
        await interaction.response.send_message("Vote ID not found.", ephemeral=True)
        return

    candidates_by_name = {
        candidate["name"].lower(): candidate
        for candidate in vote["applicants"]
    }

    submitted = []
    skipped = []

    for raw_line in scores.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        parts = [part.strip() for part in line.split("|")]

        if len(parts) < 4:
            skipped.append(f"`{line}` — wrong format")
            continue

        toon_name = parts[0]
        notes = parts[4] if len(parts) >= 5 else ""

        try:
            role_value = int(parts[1])
            upgrade_impact = int(parts[2])
            conduct = int(parts[3])
        except ValueError:
            skipped.append(f"`{toon_name}` — scores must be numbers")
            continue

        if not (0 <= role_value <= 15 and 0 <= upgrade_impact <= 15 and 0 <= conduct <= 10):
            skipped.append(f"`{toon_name}` — score out of range")
            continue

        target = candidates_by_name.get(toon_name.lower())
        if not target:
            skipped.append(f"`{toon_name}` — candidate not found")
            continue

        if target.get("discord_user_id") == interaction.user.id:
            skipped.append(f"`{toon_name}` — cannot score yourself")
            continue

        total = role_value + upgrade_impact + conduct
        target["scores"][str(interaction.user.id)] = {
            "lead_name": interaction.user.display_name,
            "role_value": role_value,
            "upgrade_impact": upgrade_impact,
            "conduct": conduct,
            "total": total,
            "notes": notes
        }

        submitted.append(f"`{toon_name}` — {total} / 40")

    save_data(data)

    message = "**Bulk scores submitted:**
"
    message += "
".join(submitted) if submitted else "None"

    if skipped:
        message += "

**Skipped:**
" + "
".join(skipped)

    await interaction.response.send_message(message[:1900], ephemeral=True)


if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")

bot.run(TOKEN)
