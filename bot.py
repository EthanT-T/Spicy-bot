class ModalSupport(discord.ui.Modal, title="Ouvrir un ticket support"):
    sujet = discord.ui.TextInput(
        label="Sujet de ton ticket",
        style=discord.TextStyle.short,
        placeholder="Ex: Problème en jeu, question boutique...",
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        
        # --- MODIFICATION ICI : On utilise ID_CATEGORIE_SUPPORT ---
        categorie = guild.get_channel(ID_CATEGORIE_SUPPORT) if ID_CATEGORIE_SUPPORT else None
        
        pseudo_clean = re.sub(r'[^a-z0-9]', '', interaction.user.display_name.lower()) or str(interaction.user.id)[:6]
        nom_salon = f"ticket-{pseudo_clean}"

        existant = discord.utils.get(guild.text_channels, name=nom_salon)
        if existant:
            return await interaction.followup.send(f"❌ Tu as déjà un ticket support ouvert : {existant.mention}", ephemeral=True)

        overwrites = get_ticket_overwrites(guild, interaction.user)

        try:
            ticket = await guild.create_text_channel(name=nom_salon, category=categorie, overwrites=overwrites)
            await interaction.followup.send(f"✅ Ton ticket a été créé : {ticket.mention}", ephemeral=True)

            embed = discord.Embed(
                title=f"🛠️ Ticket Support",
                description=f"Bonjour {interaction.user.mention},\n\nMerci d'avoir contacté le support. Un membre de la Spicy Team va te répondre.\n\n**Sujet :** {self.sujet.value}",
                color=0xf1c40f
            )
            
            mention_staff = f"<@&{ID_ROLE_SPICY_TEAM}>" if ID_ROLE_SPICY_TEAM else ""
            await ticket.send(f"{interaction.user.mention} {mention_staff}", embed=embed, view=TicketCloseView())
        except Exception as e:
            await interaction.followup.send("❌ Erreur lors de la création.", ephemeral=True)
            print(f"Erreur Ticket Support: {e}")