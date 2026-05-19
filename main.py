import os

        try:
            role_value = int(parts[1])
            upgrade_impact = int(parts[2])
            conduct = int(parts[3])
        except ValueError:
            skipped.append(f"`{toon_name}` — invalid score")
            continue

        if not (0 <= role_value <= 15 and 0 <= upgrade_impact <= 15 and 0 <= conduct <= 10):
            skipped.append(f"`{toon_name}` — score out of range")
            continue

        target = candidates_by_name.get(toon_name.lower())

        if not target:
            skipped.append(f"`{toon_name}` — candidate not found")
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


@bot.tree.command(name="rankings", description="Show rankings")
@app_commands.describe(vote_id="Vote ID")
async def rankings(interaction: discord.Interaction, vote_id: str):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can use this.", ephemeral=True)
        return

    embed = build_ranking_embed(vote_id)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="vote_summary", description="Show vote summary")
@app_commands.describe(vote_id="Vote ID")
async def vote_summary(interaction: discord.Interaction, vote_id: str):
    if not is_lead(interaction.user):
        await interaction.response.send_message("Only leads can use this.", ephemeral=True)
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
            f"Needs: {candidate['needs']} | Objective: {candidate['objective_score']} / 60 | Scores: {score_count}"
        )

    embed = discord.Embed(
        title=f"Vote Summary — {vote['title']}",
        description="

".join(lines),
        color=discord.Color.teal()
    )

    embed.add_field(
        name="Easy Workflow",
        value=(
            "1. `/score_template`
"
            "2. Fill in scores
"
            "3. Paste into `/bulk_score`
"
            "4. Check `/rankings`"
        ),
        inline=False
    )

    await interaction.response.send_message(embed=embed)


if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable")


bot.run(TOKEN)
